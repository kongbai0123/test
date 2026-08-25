"""Persistent, non-blocking camera capture for the GTK live preview."""

from __future__ import annotations

import glob
import copy
import json
import logging
import os
import threading
import time
from collections import deque
from fractions import Fraction
from typing import Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import cv2
import numpy as np

from src.engine.camera_capabilities import (
    empty_capabilities,
    enumerate_v4l2_capabilities,
    fourcc_from_value,
    is_usb_video_device,
    normalize_nvidia_capabilities,
    select_mode_for_fps,
    video_device_name,
)

logger = logging.getLogger("CaptureEngine.Camera")

NVIDIA_CAMERA_STATUS_URL = "http://127.0.0.1:8000/camera/status"
NVIDIA_CAMERA_CAPABILITIES_URL = "http://127.0.0.1:8000/camera/capabilities"
NVIDIA_CAMERA_STREAM_URL = "http://127.0.0.1:8000/video_feed"
NVIDIA_CAMERA_FPS_URL = "http://127.0.0.1:8000/camera/fps"
NVIDIA_CAMERA_DEVICE_NAME = "NVIDIA 相機服務"
NVIDIA_RECORDING_SOURCE = "nvidia_stream"
V4L2_RECORDING_SOURCE_PREFIX = "v4l2:"


class CameraStream:
    """Continuously reads the first working physical camera on a worker thread."""

    def __init__(
        self,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        nvidia_stream_url: str = NVIDIA_CAMERA_STREAM_URL,
    ) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self.nvidia_stream_url = nvidia_stream_url
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_sequence = 0
        self._frame_times = deque(maxlen=max(15, min(self.fps * 2, 120)))
        self._measured_fps = 0.0
        self._source_width = width
        self._source_height = height
        self._configured_fps = float(fps)
        self._connected = False
        self._device_name: Optional[str] = None
        self._active_source_kind: Optional[str] = None
        self._active_device_path: Optional[str] = None
        self._preferred_pixel_format = "MJPG"
        self._capabilities = empty_capabilities()
        self._error = "鏡頭尚未啟動"

    @staticmethod
    def _is_jetson() -> bool:
        return os.path.exists("/etc/nv_tegra_release")

    def _fetch_nvidia_status(self) -> Optional[dict]:
        """Read source settings from the loopback-only NVIDIA owner service."""
        try:
            with urlopen(NVIDIA_CAMERA_STATUS_URL, timeout=0.7) as response:
                if response.status != 200:
                    return None
                payload = json.loads(response.read().decode("utf-8"))
            with self._lock:
                self._source_width = int(payload.get("width", self._source_width))
                self._source_height = int(payload.get("height", self._source_height))
                self._configured_fps = float(payload.get("fps", self._configured_fps))
            return payload
        except Exception:
            return None

    def _nvidia_service_available(self) -> bool:
        """Return whether the boot-time NVIDIA service can be reached."""
        return self._fetch_nvidia_status() is not None

    def _nvidia_camera_connected(self) -> bool:
        """Return whether the owner service reports a real, connected CSI camera."""
        status = self._fetch_nvidia_status()
        return bool(status and status.get("connected") is True)

    def _fetch_nvidia_capabilities(self, connected: bool) -> Optional[dict]:
        """Read declared CSI modes from the sole owner without opening CAM0."""
        try:
            with urlopen(NVIDIA_CAMERA_CAPABILITIES_URL, timeout=0.9) as response:
                if response.status != 200:
                    return None
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                return None
            return normalize_nvidia_capabilities(payload, connected=connected)
        except Exception:
            return None

    @staticmethod
    def _is_usb_video_device(path: str) -> bool:
        """Identify a USB/UVC V4L2 node without mistaking Jetson CSI for USB."""
        return is_usb_video_device(path)

    @staticmethod
    def _video_device_label(path: str, is_usb: bool) -> str:
        node = os.path.basename(path)
        device_name = video_device_name(path)
        source_type = "USB 攝影機" if is_usb else "V4L2 攝影機"
        return f"{source_type}：{device_name or node} ({path})"

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def is_stopping(self) -> bool:
        """Return whether a live worker is draining after a stop request."""
        with self._lifecycle_lock:
            return bool(
                self._thread
                and self._thread.is_alive()
                and self._stop_event.is_set()
            )

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def status(self) -> Tuple[bool, Optional[str], str]:
        with self._lock:
            return self._connected, self._device_name, self._error

    @property
    def uses_nvidia_service(self) -> bool:
        with self._lock:
            return self._connected and self._active_source_kind == NVIDIA_RECORDING_SOURCE

    @property
    def recording_source(self) -> Optional[str]:
        """Return the exact source the recorder must open after preview handoff."""
        with self._lock:
            if not self._connected:
                return None
            if self._active_source_kind == NVIDIA_RECORDING_SOURCE:
                return NVIDIA_RECORDING_SOURCE
            if self._active_source_kind == "usb_v4l2" and self._active_device_path:
                return f"{V4L2_RECORDING_SOURCE_PREFIX}{self._active_device_path}"
            return None

    def get_frame(self) -> Optional[np.ndarray]:
        """Return the newest BGR frame without ever waiting for the camera."""
        with self._lock:
            return None if self._latest_frame is None else self._latest_frame.copy()

    def get_frame_snapshot(
        self,
        after_sequence: int = -1,
    ) -> Optional[Tuple[int, np.ndarray]]:
        """Return the newest frame reference without copying pixel memory.

        The returned array must be treated as read-only. OpenCV allocates a new
        array for each capture, so replacing ``_latest_frame`` does not mutate a
        snapshot already being processed by the preview worker.
        """
        with self._lock:
            if self._latest_frame is None or self._frame_sequence <= after_sequence:
                return None
            return self._frame_sequence, self._latest_frame

    @property
    def measured_fps(self) -> float:
        """Rolling FPS measured from frames actually received by this application."""
        with self._lock:
            return self._measured_fps

    @property
    def configured_fps(self) -> float:
        """FPS requested from the physical source, distinct from receive rate."""
        with self._lock:
            return self._configured_fps

    @property
    def source_settings(self) -> Tuple[int, int, float]:
        with self._lock:
            return self._source_width, self._source_height, self._configured_fps

    @property
    def capabilities(self) -> dict:
        """Return a thread-safe snapshot of declared, negotiated and measured data."""
        with self._lock:
            snapshot = copy.deepcopy(self._capabilities)
            device = snapshot.setdefault("device", {})
            device["connected"] = self._connected
            current = snapshot.get("current")
            if self._connected:
                if not isinstance(current, dict):
                    current = {}
                    snapshot["current"] = current
                current.update(
                    {
                        "received_width": self._source_width,
                        "received_height": self._source_height,
                        "configured_fps": self._configured_fps,
                        "measured_fps": round(self._measured_fps, 3),
                        "status": "receiving",
                    }
                )
            elif isinstance(current, dict) and current.get("status") in (
                "receiving",
                "negotiated",
            ):
                current["status"] = "last_negotiated"
            return snapshot

    def _store_frame(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        with self._lock:
            self._latest_frame = frame
            self._frame_sequence += 1
            self._source_height, self._source_width = frame.shape[:2]
            self._frame_times.append(now)
            if len(self._frame_times) >= 5:
                elapsed = self._frame_times[-1] - self._frame_times[0]
                if elapsed > 0:
                    self._measured_fps = (len(self._frame_times) - 1) / elapsed

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = None
            self._stop_event.clear()
            thread = threading.Thread(target=self._run, name="camera-preview", daemon=True)
            self._thread = thread
            thread.start()

    def stop(self) -> bool:
        with self._lifecycle_lock:
            self._stop_event.set()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            # FFMPEG's read timeout is 2.5 seconds. Never detach a live consumer
            # thread and then accidentally open a second HTTP stream.
            thread.join(timeout=4.0)
        stopped = not thread or not thread.is_alive()
        with self._lifecycle_lock:
            if stopped and self._thread is thread:
                self._thread = None
        with self._lock:
            self._connected = False
            self._latest_frame = None
            self._frame_times.clear()
            self._measured_fps = 0.0
            if stopped:
                self._device_name = None
                self._active_source_kind = None
                self._active_device_path = None
        return stopped

    def request_nvidia_fps(self, requested_fps: int) -> dict:
        """Ask the sole CSI owner to clamp/apply FPS; caller owns reconnect."""
        request = Request(
            NVIDIA_CAMERA_FPS_URL,
            data=json.dumps({"fps": int(requested_fps)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        try:
            with urlopen(request, timeout=10.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8")).get("detail", str(error))
            except Exception:
                detail = str(error)
            raise RuntimeError(detail) from error

        # Newer NVIDIA service versions return a non-blocking operation. Keep
        # polling its explicit state so an eventual commit is never mistaken
        # for a definitive timeout failure.
        if payload.get("status") in ("pending", "running"):
            operation_id = payload.get("operation_id")
            if not operation_id:
                raise RuntimeError("相機服務未回傳設定操作編號")
            deadline = time.monotonic() + 90.0
            operation_url = f"{NVIDIA_CAMERA_FPS_URL}/{quote(operation_id, safe='')}"
            while time.monotonic() < deadline:
                time.sleep(0.25)
                with urlopen(operation_url, timeout=5.0) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("status") == "succeeded":
                    payload = payload.get("result") or {}
                    break
                if payload.get("status") == "failed":
                    raise RuntimeError(payload.get("error") or "相機設定失敗")
            else:
                raise RuntimeError(
                    f"相機設定仍在執行（操作編號：{operation_id}），請稍後查看目前設定"
                )
        elif payload.get("status") == "succeeded":
            payload = payload.get("result") or {}

        if not all(key in payload for key in ("width", "height", "fps")):
            raise RuntimeError("相機服務回傳的設定結果不完整")
        with self._lock:
            self._source_width = int(payload["width"])
            self._source_height = int(payload["height"])
            self._configured_fps = float(payload["fps"])
            if self._capabilities.get("device", {}).get("backend") == "nvidia_csi":
                current = self._capabilities.get("current")
                if not isinstance(current, dict):
                    current = {}
                    self._capabilities["current"] = current
                current.update(
                    {
                        "width": self._source_width,
                        "height": self._source_height,
                        "fps": self._configured_fps,
                        "pixel_format": current.get("pixel_format", "NV12"),
                        "status": "negotiated",
                    }
                )
        return payload

    @staticmethod
    def _set_v4l2_mode(cap, selection: dict) -> dict:
        """Submit a normalized mode request to an already opened V4L2 handle."""
        set_results = {}
        pixel_format = str(selection.get("pixel_format") or "").upper()
        if len(pixel_format) == 4 and pixel_format.isprintable():
            set_results["pixel_format"] = bool(
                cap.set(
                    cv2.CAP_PROP_FOURCC,
                    cv2.VideoWriter_fourcc(*pixel_format),
                )
            )
        else:
            set_results["pixel_format"] = None
        set_results["width"] = bool(
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(selection["width"]))
        )
        set_results["height"] = bool(
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(selection["height"]))
        )
        set_results["fps"] = bool(
            cap.set(cv2.CAP_PROP_FPS, float(selection["fps"]))
        )
        return set_results

    def request_usb_fps(
        self,
        requested_fps: int,
        *,
        validation_seconds: float = 3.0,
    ) -> dict:
        """Atomically configure USB while preventing preview from reopening it."""
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("請先停止攝影機預覽再套用 USB 模式")
            return self._request_usb_fps_stopped(
                requested_fps,
                validation_seconds=validation_seconds,
            )

    def _request_usb_fps_stopped(
        self,
        requested_fps: int,
        *,
        validation_seconds: float,
    ) -> dict:
        """Negotiate and briefly validate a selected USB/V4L2 camera mode.

        The lifecycle lock is held by the caller. Preferences
        are committed only after the device returns at least one real frame, so
        an unplugged or rejected mode cannot silently replace the last working
        configuration.
        """
        with self._lock:
            capabilities = copy.deepcopy(self._capabilities)
        device = capabilities.get("device")
        if not isinstance(device, dict) or device.get("backend") not in (
            "usb_v4l2",
            "v4l2",
        ):
            raise RuntimeError("目前沒有可設定的 USB 攝影機能力資料")
        path = str(device.get("path") or "")
        if not path.startswith("/dev/video") or not path[len("/dev/video") :].isdigit():
            raise RuntimeError("USB 攝影機裝置路徑無效")
        if self._is_jetson() and not self._is_usb_video_device(path):
            raise RuntimeError("拒絕把 Jetson CSI 節點當作 USB 攝影機設定")

        selection = select_mode_for_fps(capabilities, requested_fps)
        if selection is None:
            raise RuntimeError("攝影機沒有可套用的解析度／FPS 模式")

        cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            raise RuntimeError(f"無法開啟 USB 攝影機 {path}")

        frame = None
        frame_times = []
        set_results = {}
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            set_results = self._set_v4l2_mode(cap, selection)
            started = time.monotonic()
            deadline = started + max(0.0, min(float(validation_seconds), 5.0))
            failures = 0
            while len(frame_times) < 240:
                ok, candidate = cap.read()
                now = time.monotonic()
                if ok and candidate is not None and candidate.size:
                    frame = candidate
                    frame_times.append(now)
                    failures = 0
                else:
                    failures += 1
                    if failures >= 10:
                        break
                if validation_seconds <= 0 or now >= deadline:
                    break
            if frame is None:
                raise RuntimeError("USB 攝影機接受設定後沒有輸出影像")

            actual_width = int(
                self._capture_property(cap, cv2.CAP_PROP_FRAME_WIDTH, frame.shape[1])
            )
            actual_height = int(
                self._capture_property(cap, cv2.CAP_PROP_FRAME_HEIGHT, frame.shape[0])
            )
            actual_fps = self._capture_property(
                cap,
                cv2.CAP_PROP_FPS,
                float(selection["fps"]),
            )
            actual_fourcc = fourcc_from_value(
                self._capture_property(cap, cv2.CAP_PROP_FOURCC)
            ) or str(selection.get("pixel_format") or "UNKNOWN")
        finally:
            cap.release()

        measured_fps = 0.0
        if len(frame_times) >= 2:
            elapsed = frame_times[-1] - frame_times[0]
            if elapsed > 0:
                measured_fps = (len(frame_times) - 1) / elapsed
        if len(frame_times) < 2:
            validation_status = "frame_received"
        elif measured_fps >= max(0.1, actual_fps * 0.85):
            validation_status = "validated"
        else:
            validation_status = "degraded"

        selected_fps = float(selection["fps"])
        selected_pixel_format = str(selection.get("pixel_format") or "UNKNOWN")
        received_width = int(frame.shape[1])
        received_height = int(frame.shape[0])
        fps_tolerance = max(0.05, abs(selected_fps) * 0.01)
        negotiation_adjusted = (
            actual_width != int(selection["width"])
            or actual_height != int(selection["height"])
            or abs(actual_fps - selected_fps) > fps_tolerance
            or (
                actual_fourcc != "UNKNOWN"
                and selected_pixel_format != "UNKNOWN"
                and actual_fourcc.upper() != selected_pixel_format.upper()
            )
            or received_width != actual_width
            or received_height != actual_height
        )
        actual_fps_fraction = Fraction(str(actual_fps)).limit_denominator(1_000_000)
        selected_request = {
            "mode_id": selection.get("mode_id"),
            "width": int(selection["width"]),
            "height": int(selection["height"]),
            "fps": selected_fps,
            "fps_rational": copy.deepcopy(selection.get("fps_rational")),
            "pixel_format": selected_pixel_format,
        }

        result = dict(selection)
        result.update(
            {
                "width": actual_width,
                "height": actual_height,
                "fps": actual_fps,
                "fps_rational": {
                    "numerator": actual_fps_fraction.numerator,
                    "denominator": actual_fps_fraction.denominator,
                },
                "pixel_format": actual_fourcc,
                "connected": True,
                "selected": selected_request,
                "negotiated": {
                    "width": actual_width,
                    "height": actual_height,
                    "fps": actual_fps,
                    "fps_rational": {
                        "numerator": actual_fps_fraction.numerator,
                        "denominator": actual_fps_fraction.denominator,
                    },
                    "pixel_format": actual_fourcc,
                    "received_width": received_width,
                    "received_height": received_height,
                    "adjusted": negotiation_adjusted,
                    "set_results": set_results,
                    "status": "negotiated",
                },
                "measured": {
                    "fps": round(measured_fps, 3),
                    "sample_frames": len(frame_times),
                    "status": validation_status,
                },
                "validation_status": validation_status,
                "measured_fps": round(measured_fps, 3),
                "negotiation_adjusted": negotiation_adjusted,
            }
        )
        with self._lock:
            self.width = actual_width
            self.height = actual_height
            self.fps = max(1, int(round(actual_fps)))
            self._source_width = actual_width
            self._source_height = actual_height
            self._configured_fps = actual_fps
            self._preferred_pixel_format = actual_fourcc
            current = self._capabilities.get("current")
            if not isinstance(current, dict):
                current = {}
                self._capabilities["current"] = current
            current.update(result["negotiated"])
            current["requested"] = {
                "fps": requested_fps,
                "mode_id": selection.get("mode_id"),
                "selection": copy.deepcopy(selected_request),
            }
            current["measured"] = copy.deepcopy(result["measured"])
        return result

    def request_camera_fps(self, requested_fps: int) -> dict:
        """Apply an FPS target through the current source's proper owner."""
        with self._lock:
            backend = self._capabilities.get("device", {}).get("backend")
        if backend == "nvidia_csi":
            return self.request_nvidia_fps(requested_fps)
        if backend in ("usb_v4l2", "v4l2"):
            return self.request_usb_fps(requested_fps)
        raise RuntimeError("目前攝影機沒有可套用的能力資料")

    def _candidate_devices(self):
        # The NVIDIA service is the sole CSI owner. Consume its MJPEG output instead
        # of attempting a second nvarguscamerasrc capture session.
        is_jetson = self._is_jetson()
        if is_jetson and self._nvidia_camera_connected():
            yield self.nvidia_stream_url, cv2.CAP_FFMPEG, NVIDIA_CAMERA_DEVICE_NAME

        # On Jetson, only positively identified USB/UVC nodes are safe fallbacks.
        # /dev/video0 on this machine is IMX219 CSI and must remain service-owned.
        paths = sorted(glob.glob("/dev/video*"))
        for path in paths:
            is_usb = self._is_usb_video_device(path)
            if is_jetson and not is_usb:
                continue
            yield path, cv2.CAP_V4L2, self._video_device_label(path, is_usb)

        if not paths and os.name != "posix":
            # This fallback also keeps virtual/test camera backends usable.
            for index in range(4):
                yield index, cv2.CAP_ANY, f"Camera #{index}"

    def _fallback_nvidia_capabilities(self, status: Optional[dict]) -> dict:
        """Build an explicitly unverified model for an older owner service."""
        status = status or {}
        width = int(status.get("width", self.width))
        height = int(status.get("height", self.height))
        fps = float(status.get("fps", self.fps))
        return normalize_nvidia_capabilities(
            {
                "provenance": "fallback",
                "min_fps": fps,
                "max_fps": fps,
                "integer_fps_only": fps.is_integer(),
                "modes": [
                    {
                        "id": f"nvidia-csi:cam0:fallback:{width}x{height}",
                        "width": width,
                        "height": height,
                        "min_fps": fps,
                        "max_fps": fps,
                        "pixel_format": "NV12",
                        "provenance": "fallback",
                        "status": "unverified",
                    }
                ],
                "current": status,
            },
            connected=bool(status.get("connected", True)),
        )

    @staticmethod
    def _capture_property(cap, property_id: int, fallback: float = 0.0) -> float:
        try:
            value = float(cap.get(property_id))
            return value if value > 0 else float(fallback)
        except (TypeError, ValueError, OverflowError):
            return float(fallback)

    def _open_camera(self):
        with self._lock:
            self._active_source_kind = None
            self._active_device_path = None
        for device, backend, display_name in self._candidate_devices():
            if self._stop_event.is_set():
                return None, None
            candidate_capabilities = None
            requested_usb_mode = None
            if backend == cv2.CAP_V4L2 and isinstance(device, str):
                candidate_capabilities = enumerate_v4l2_capabilities(
                    device,
                    fallback_width=self.width,
                    fallback_height=self.height,
                    fallback_fps=self.fps,
                    # CameraStream only treats positively identified UVC nodes
                    # as USB capabilities, including on non-Jetson Linux.
                    require_usb=True,
                )
                requested_usb_mode = select_mode_for_fps(
                    candidate_capabilities,
                    self.fps,
                )
            if backend == cv2.CAP_FFMPEG:
                cap = cv2.VideoCapture(
                    device,
                    backend,
                    [
                        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                        2000,
                        cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                        2500,
                    ],
                )
            else:
                cap = cv2.VideoCapture(device, backend)
            if not cap.isOpened():
                cap.release()
                continue
            if backend == cv2.CAP_V4L2:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if requested_usb_mode is not None:
                    # The selector uses the device's own advertised modes and
                    # chooses maximum pixels at the nearest legal FPS.
                    self._set_v4l2_mode(cap, requested_usb_mode)
                else:
                    # Older/uncooperative V4L2 drivers retain the established
                    # safe request path; the read-back remains marked fallback.
                    fallback_mode = {
                        "width": self.width,
                        "height": self.height,
                        "fps": self.fps,
                        "pixel_format": self._preferred_pixel_format,
                    }
                    self._set_v4l2_mode(cap, fallback_mode)
            ok, frame = cap.read()
            if ok and frame is not None and frame.size:
                nvidia_status = None
                if backend == cv2.CAP_FFMPEG:
                    # The service can keep returning a valid offline JPEG after
                    # CAM0 disappears. A definite disconnected status must reject it.
                    nvidia_status = self._fetch_nvidia_status()
                    if nvidia_status is not None and nvidia_status.get("connected") is not True:
                        cap.release()
                        continue
                if backend == cv2.CAP_V4L2:
                    actual_width = int(
                        self._capture_property(cap, cv2.CAP_PROP_FRAME_WIDTH, frame.shape[1])
                    )
                    actual_height = int(
                        self._capture_property(cap, cv2.CAP_PROP_FRAME_HEIGHT, frame.shape[0])
                    )
                    actual_fps = self._capture_property(cap, cv2.CAP_PROP_FPS, self.fps)
                    actual_fourcc = fourcc_from_value(
                        self._capture_property(cap, cv2.CAP_PROP_FOURCC)
                    )
                    if candidate_capabilities is None:
                        candidate_capabilities = empty_capabilities(
                            device_id=f"v4l2:{device}",
                            name=display_name,
                            backend="usb_v4l2",
                            path=str(device),
                            connected=True,
                            provenance="fallback",
                            status="unverified",
                        )
                    current = candidate_capabilities.get("current")
                    if not isinstance(current, dict):
                        current = {}
                        candidate_capabilities["current"] = current
                    current.update(
                        {
                            "width": actual_width,
                            "height": actual_height,
                            "fps": actual_fps,
                            "pixel_format": actual_fourcc or "UNKNOWN",
                            "status": "negotiated",
                            "provenance": "opencv_v4l2",
                        }
                    )
                    candidate_capabilities.setdefault("device", {})["connected"] = True
                    with self._lock:
                        self.width = actual_width
                        self.height = actual_height
                        self.fps = max(1, int(round(actual_fps)))
                        self._configured_fps = actual_fps
                        self._preferred_pixel_format = actual_fourcc or self._preferred_pixel_format
                        self._active_source_kind = "usb_v4l2"
                        self._active_device_path = str(device)
                        self._capabilities = copy.deepcopy(candidate_capabilities)
                else:
                    candidate_capabilities = self._fetch_nvidia_capabilities(connected=True)
                    if candidate_capabilities is None:
                        candidate_capabilities = self._fallback_nvidia_capabilities(
                            nvidia_status
                        )
                    current = candidate_capabilities.get("current")
                    if not isinstance(current, dict):
                        current = {}
                        candidate_capabilities["current"] = current
                    current.setdefault("width", frame.shape[1])
                    current.setdefault("height", frame.shape[0])
                    current.setdefault("fps", self._configured_fps)
                    current.setdefault("pixel_format", "NV12")
                    current["status"] = "negotiated"
                    candidate_capabilities.setdefault("device", {})["connected"] = True
                    with self._lock:
                        self._active_source_kind = NVIDIA_RECORDING_SOURCE
                        self._active_device_path = None
                        self._capabilities = copy.deepcopy(candidate_capabilities)
                self._store_frame(frame)
                return cap, display_name
            cap.release()
        return None, None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            cap, device = self._open_camera()
            if cap is None:
                nvidia_status = self._fetch_nvidia_status() if self._is_jetson() else None
                with self._lock:
                    self._connected = False
                    self._device_name = None
                    self._active_source_kind = None
                    self._active_device_path = None
                    self._latest_frame = None
                    self._frame_times.clear()
                    self._measured_fps = 0.0
                    if self._is_jetson() and nvidia_status is None:
                        self._error = (
                            "NVIDIA 相機服務未啟動，且未偵測到可讀取的 USB 攝影機；"
                            "為避免 CSI Camera 0 衝突，不會直接開啟 CAM0"
                        )
                    elif self._is_jetson() and nvidia_status.get("connected") is not True:
                        self._error = "CAM0 目前無影像，且未偵測到可讀取的 USB 攝影機"
                    elif self._is_jetson():
                        self._error = "CAM0 已連線但串流無法讀取，且沒有可用的 USB 攝影機"
                    else:
                        self._error = "未偵測到可讀取的攝影機，請檢查連接或裝置權限"
                self._stop_event.wait(2.0)
                continue

            logger.info("Live camera preview opened: %s", device)
            with self._lock:
                self._connected = True
                self._device_name = device
                self._error = ""

            failures = 0
            last_nvidia_check = time.monotonic()
            try:
                while not self._stop_event.is_set():
                    ok, frame = cap.read()
                    if ok and frame is not None and frame.size:
                        failures = 0
                        self._store_frame(frame)
                    else:
                        failures += 1
                        if failures >= 10:
                            break
                        time.sleep(0.03)

                    # A disconnected CSI service still emits an offline JPEG, so
                    # cap.read() alone cannot detect loss. A transient status timeout
                    # does not interrupt a valid stream; only an explicit false does.
                    if device == NVIDIA_CAMERA_DEVICE_NAME:
                        now = time.monotonic()
                        if now - last_nvidia_check >= 1.0:
                            last_nvidia_check = now
                            nvidia_status = self._fetch_nvidia_status()
                            if (
                                nvidia_status is not None
                                and nvidia_status.get("connected") is not True
                                and not nvidia_status.get("reconfiguring", False)
                            ):
                                break
            finally:
                cap.release()
                with self._lock:
                    self._connected = False
                    self._device_name = None
                    self._active_source_kind = None
                    self._active_device_path = None
                    self._latest_frame = None
                    self._frame_times.clear()
                    self._measured_fps = 0.0
                    if not self._stop_event.is_set():
                        self._error = "攝影機訊號中斷，正在重新連線"
