import math
import os
import stat
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Tuple

import cv2
import numpy as np
import yaml

from camera_capabilities import (
    CAMERA_MAX_FPS,
    CAMERA_MIN_FPS,
    IMX219_SENSOR_MODES,
    CameraCapabilityCatalog,
    discover_nvidia_csi_capabilities,
)


class CameraBusyError(RuntimeError):
    pass


@dataclass(frozen=True)
class CameraSelection:
    requested_fps: int
    fps: int
    width: int
    height: int
    mode_max_fps: int
    mode_min_fps: int = CAMERA_MIN_FPS
    mode_id: str = "known-imx219"
    sensor_mode_index: Optional[int] = None
    provenance: str = "known_table"
    pixel_format: str = "NV12"

    @property
    def clamped(self) -> bool:
        return self.requested_fps != self.fps


@dataclass
class CameraOperation:
    selection: CameraSelection
    operation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "pending"
    result: Optional[dict] = None
    error: Optional[str] = None
    done: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict:
        return {
            "operation_id": self.operation_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }


def select_imx219_settings(requested_fps: int) -> CameraSelection:
    """Clamp to the physical 2..60 FPS range and retain maximum pixels."""
    requested = int(requested_fps)
    fps = max(CAMERA_MIN_FPS, min(CAMERA_MAX_FPS, requested))
    for width, height, max_fps in IMX219_SENSOR_MODES:
        if fps <= max_fps:
            return CameraSelection(requested, fps, width, height, max_fps)
    width, height, max_fps = IMX219_SENSOR_MODES[-1]
    return CameraSelection(requested, fps, width, height, max_fps)


class CameraReader:
    def __init__(self, config_path=None):
        if config_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "config", "camera.yaml")

        self.config_path = config_path
        self.source = 0
        self.width = 1280
        self.height = 720
        self.fps = 30
        self._requested_fps = self.fps
        self._capabilities: Optional[CameraCapabilityCatalog] = None
        self._current_mode_id: Optional[str] = None
        self.is_mock = False
        self.load_config()

        self.cap = None
        self._connected = False
        self._reconfiguring = False
        self.latest_frame = None
        self.frame_sequence = 0
        self.running = False
        self.thread = None

        self._state_lock = threading.RLock()
        self.frame_condition = threading.Condition(self._state_lock)
        self._lifecycle_lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._operation_gate = threading.Lock()
        self._operation_event = threading.Event()
        self._pending_operation: Optional[CameraOperation] = None
        self._active_operation: Optional[CameraOperation] = None
        self._operations = {}
        self._capture_times = deque(maxlen=120)
        self._measured_fps = 0.0

    def _load_capabilities(self) -> None:
        source = self.source
        if isinstance(source, str) and source.isdigit():
            source = int(source)
        sensor_id = source if isinstance(source, int) and source >= 0 else 0
        self._capabilities = discover_nvidia_csi_capabilities(sensor_id)
        print(
            "Camera capabilities loaded once before capture: "
            f"{self._capabilities.provenance}, {len(self._capabilities.modes)} modes"
        )

    def _select_settings(self, requested_fps: int) -> CameraSelection:
        if self._capabilities is None:
            self._load_capabilities()
        fps, mode = self._capabilities.select(requested_fps)
        return CameraSelection(
            requested_fps=int(requested_fps),
            fps=fps,
            width=mode.width,
            height=mode.height,
            mode_max_fps=int(math.floor(mode.max_fps + 0.001)),
            mode_min_fps=int(math.ceil(mode.min_fps - 0.001)),
            mode_id=mode.id,
            sensor_mode_index=mode.sensor_mode_index,
            provenance=mode.provenance,
            pixel_format=mode.pixel_format,
        )

    def _mode_for(
        self,
        width: int,
        height: int,
        fps: Optional[int] = None,
        mode_id: Optional[str] = None,
    ):
        if self._capabilities is None:
            self._load_capabilities()
        return self._capabilities.find_mode(
            width,
            height,
            fps=fps,
            mode_id=mode_id,
        )

    def _remember_selection_mode(self, selection: CameraSelection) -> None:
        self._current_mode_id = selection.mode_id

    def _mode_max_fps(self, width: int, height: int) -> Optional[int]:
        mode = self._mode_for(width, height)
        return (
            int(math.floor(mode.max_fps + 0.001)) if mode is not None else None
        )

    def _current_selection(self) -> CameraSelection:
        with self._state_lock:
            mode = self._mode_for(
                self.width,
                self.height,
                self.fps,
                self._current_mode_id,
            )
            return CameraSelection(
                requested_fps=self.fps,
                fps=self.fps,
                width=self.width,
                height=self.height,
                mode_max_fps=(
                    int(math.floor(mode.max_fps + 0.001))
                    if mode is not None
                    else self.fps
                ),
                mode_min_fps=(
                    int(math.ceil(mode.min_fps - 0.001))
                    if mode is not None
                    else self.fps
                ),
                mode_id=mode.id if mode is not None else "unknown",
                sensor_mode_index=(
                    mode.sensor_mode_index if mode is not None else None
                ),
                provenance=(mode.provenance if mode is not None else "unknown"),
                pixel_format=(mode.pixel_format if mode is not None else "NV12"),
            )

    def load_config(self):
        try:
            if not os.path.exists(self.config_path):
                print(f"Warning: Configuration file not found at {self.config_path}. Using defaults.")
                self._load_capabilities()
                selected = self._select_settings(self.fps)
                self._remember_selection_mode(selected)
                self.width, self.height, self.fps = (
                    selected.width,
                    selected.height,
                    selected.fps,
                )
                return
            with open(self.config_path, "r", encoding="utf-8") as config_file:
                data = yaml.safe_load(config_file) or {}
            camera_config = data.get("camera", {})
            self.source = camera_config.get("source", 0)
            # Capability discovery is deliberately completed before start()
            # can create nvarguscamerasrc's sole CaptureSession.
            self._load_capabilities()
            width = int(camera_config.get("width", self.width))
            height = int(camera_config.get("height", self.height))
            fps = int(camera_config.get("fps", self.fps))
            self._requested_fps = fps
            mode = self._mode_for(width, height, fps)
            if mode is not None and mode.supports_integer_fps(fps):
                self.width, self.height, self.fps = width, height, fps
                self._current_mode_id = mode.id
            else:
                selected = self._select_settings(fps)
                self._remember_selection_mode(selected)
                self.width, self.height, self.fps = selected.width, selected.height, selected.fps
                print("Camera config was outside advertised limits; safe bounded settings will be used.")
        except Exception as error:
            print(f"Error loading camera config: {error}. Using defaults.")
            if self._capabilities is None:
                self._load_capabilities()
            selected = self._select_settings(self.fps)
            self._remember_selection_mode(selected)
            self.width, self.height, self.fps = (
                selected.width,
                selected.height,
                selected.fps,
            )

    def _save_config_atomic(self, selection: CameraSelection) -> None:
        data = {}
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as config_file:
                data = yaml.safe_load(config_file) or {}
        camera_config = data.setdefault("camera", {})
        camera_config.update(
            {
                "source": self.source,
                "width": int(selection.width),
                "height": int(selection.height),
                "fps": int(selection.fps),
            }
        )

        config_dir = os.path.dirname(os.path.abspath(self.config_path))
        os.makedirs(config_dir, exist_ok=True)
        original_mode = 0o664
        if os.path.exists(self.config_path):
            original_mode = stat.S_IMODE(os.stat(self.config_path).st_mode)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=config_dir,
                prefix=".camera-",
                suffix=".yaml.tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = temporary_file.name
                yaml.safe_dump(data, temporary_file, sort_keys=False, allow_unicode=True)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.chmod(temporary_path, original_mode)
            os.replace(temporary_path, self.config_path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def start(self):
        with self._lifecycle_lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = None
            self.running = True
            self._operation_event.clear()
            thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread = thread
            thread.start()
        print("Camera capture thread started.")

    def stop(self):
        with self._lifecycle_lock:
            self.running = False
            self._operation_event.set()
            self._fail_pending_operation("相機服務正在停止")
            thread = self.thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=6.0)
        with self._lifecycle_lock:
            if not thread or not thread.is_alive():
                if self.thread is thread:
                    self.thread = None
            else:
                print("Camera capture thread did not stop within 6 seconds.")
        with self.frame_condition:
            self.frame_condition.notify_all()
        print("Camera capture thread stopped.")

    def _fail_pending_operation(self, message: str) -> None:
        operation = None
        with self._operation_lock:
            if self._pending_operation is not None:
                operation = self._pending_operation
                self._pending_operation = None
                operation.status = "failed"
                operation.error = message
                operation.done.set()
        if operation is not None and self._operation_gate.locked():
            self._operation_gate.release()

    def _release_camera_on_capture_thread(self) -> None:
        with self._state_lock:
            cap = self.cap
            self.cap = None
            self._connected = False
        if cap is not None:
            try:
                cap.release()
            except Exception as error:
                print(f"Exception releasing camera: {error}")

    def _activate_capture(
        self,
        cap: cv2.VideoCapture,
        selection: CameraSelection,
    ) -> None:
        with self._state_lock:
            self.cap = cap
            self.width = selection.width
            self.height = selection.height
            self.fps = selection.fps
            self._remember_selection_mode(selection)
            self._connected = True
            self._capture_times.clear()
            self._measured_fps = 0.0

    def _build_jetson_pipeline(self, source: int, selection: CameraSelection) -> str:
        sensor_mode = (
            f" sensor-mode={selection.sensor_mode_index}"
            if selection.sensor_mode_index is not None
            else ""
        )
        return (
            f"nvarguscamerasrc sensor-id={source}{sensor_mode} ! "
            f"video/x-raw(memory:NVMM), width=(int){selection.width}, "
            f"height=(int){selection.height}, format=(string)NV12, "
            f"framerate=(fraction){selection.fps}/1 ! "
            "nvvidconv flip-method=0 ! "
            f"video/x-raw, width=(int){selection.width}, height=(int){selection.height}, "
            "format=(string)BGRx ! videoconvert ! "
            "video/x-raw, format=(string)BGR ! appsink drop=true"
        )

    @staticmethod
    def _valid_frame(frame: Optional[np.ndarray], selection: CameraSelection) -> bool:
        return bool(
            frame is not None
            and frame.size
            and frame.shape[:2] == (selection.height, selection.width)
        )

    def _open_camera_for(
        self, selection: CameraSelection
    ) -> Tuple[Optional[cv2.VideoCapture], Optional[np.ndarray]]:
        source = self.source
        if isinstance(source, str) and source.isdigit():
            source = int(source)
        try:
            is_jetson_csi = os.path.exists("/etc/nv_tegra_release") and isinstance(source, int)
            if is_jetson_csi:
                pipeline = self._build_jetson_pipeline(source, selection)
                print(f"Attempting to open CSI camera via GStreamer: {pipeline}")
                cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
                if cap is not None and cap.isOpened():
                    success, frame = cap.read()
                    if success and self._valid_frame(frame, selection):
                        print(
                            "CSI camera initialized and read a frame successfully "
                            f"({selection.width}x{selection.height} @ {selection.fps} FPS)"
                        )
                        return cap, frame
                if cap is not None:
                    cap.release()
                # Never fall back to an unrelated /dev/video0 for a CSI preset.
                return None, None

            print(f"Attempting to open camera using default API (Source: {source})")
            cap = cv2.VideoCapture(source)
            if cap is not None and cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, selection.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, selection.height)
                cap.set(cv2.CAP_PROP_FPS, selection.fps)
                success, frame = cap.read()
                if success and self._valid_frame(frame, selection):
                    return cap, frame
            if cap is not None:
                cap.release()
        except Exception as error:
            print(f"Exception initializing physical camera: {error}")
        return None, None

    def _open_camera_with_retries(
        self,
        selection: CameraSelection,
        delays=(0.3, 0.7, 1.5),
    ) -> Tuple[Optional[cv2.VideoCapture], Optional[np.ndarray]]:
        for delay in delays:
            if not self.running:
                return None, None
            self._operation_event.wait(timeout=delay)
            if not self.running:
                return None, None
            cap, frame = self._open_camera_for(selection)
            if cap is not None and frame is not None:
                return cap, frame
        return None, None

    def _publish_frame(self, frame: np.ndarray, physical_frame: bool) -> None:
        encoded, jpeg = cv2.imencode(".jpg", frame)
        if not encoded:
            raise RuntimeError("JPEG frame encoding failed")
        now = time.monotonic()
        with self.frame_condition:
            self.latest_frame = jpeg.tobytes()
            self.frame_sequence += 1
            if physical_frame:
                self._capture_times.append(now)
                if len(self._capture_times) >= 5:
                    elapsed = self._capture_times[-1] - self._capture_times[0]
                    if elapsed > 0:
                        self._measured_fps = (len(self._capture_times) - 1) / elapsed
            self.frame_condition.notify_all()

    def _offline_frame(self, selection: CameraSelection) -> np.ndarray:
        frame = np.zeros((selection.height, selection.width, 3), dtype=np.uint8)
        cv2.putText(
            frame,
            "NO CAMERA DETECTED (CAM0)",
            (max(10, selection.width // 2 - 210), selection.height // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )
        cv2.putText(
            frame,
            "Please check physical connection to CAM0 port",
            (max(10, selection.width // 2 - 240), selection.height // 2 + 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (150, 150, 150),
            1,
        )
        return frame

    def _take_pending_operation(self) -> Optional[CameraOperation]:
        with self._operation_lock:
            operation = self._pending_operation
            self._pending_operation = None
            if operation is not None:
                self._active_operation = operation
                operation.status = "running"
                self._operation_event.clear()
            return operation

    def _complete_operation(
        self,
        operation: CameraOperation,
        result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._operation_lock:
            operation.result = result
            operation.error = error
            operation.status = "succeeded" if error is None else "failed"
            if self._active_operation is operation:
                self._active_operation = None
            operation.done.set()
        if self._operation_gate.locked():
            self._operation_gate.release()

    @staticmethod
    def _selection_result(selection: CameraSelection) -> dict:
        return {
            "requested_fps": selection.requested_fps,
            "fps": selection.fps,
            "width": selection.width,
            "height": selection.height,
            "mode_min_fps": selection.mode_min_fps,
            "mode_max_fps": selection.mode_max_fps,
            "mode_id": selection.mode_id,
            "sensor_mode_index": selection.sensor_mode_index,
            "pixel_format": selection.pixel_format,
            "provenance": selection.provenance,
            "clamped": selection.clamped,
            "connected": True,
        }

    def _apply_operation(self, operation: CameraOperation) -> None:
        selection = operation.selection
        old_selection = self._current_selection()
        error_message = None
        result = None
        with self._state_lock:
            self._reconfiguring = True
        try:
            self._release_camera_on_capture_thread()
            cap, frame = self._open_camera_with_retries(selection)
            if cap is None or frame is None:
                raise RuntimeError(
                    f"無法開啟 {selection.width}x{selection.height} @ {selection.fps} FPS"
                )
            self._activate_capture(cap, selection)
            self._publish_frame(frame, physical_frame=True)
            # Persist only after the requested pipeline produced a real frame.
            self._save_config_atomic(selection)
            with self._state_lock:
                self._requested_fps = selection.requested_fps
            result = self._selection_result(selection)
            print(
                f"Camera settings applied: {selection.width}x{selection.height} "
                f"@ {selection.fps} FPS"
            )
        except Exception as error:
            self._release_camera_on_capture_thread()
            if self.running:
                rollback_cap, rollback_frame = self._open_camera_with_retries(old_selection)
                if rollback_cap is not None and rollback_frame is not None:
                    self._activate_capture(rollback_cap, old_selection)
                    try:
                        self._publish_frame(rollback_frame, physical_frame=True)
                        error_message = f"{error}；已恢復原設定"
                    except Exception as rollback_error:
                        self._release_camera_on_capture_thread()
                        error_message = f"{error}；回復影格失敗：{rollback_error}"
                else:
                    error_message = f"{error}；原設定也無法重新開啟"
            else:
                error_message = f"{error}；服務正在停止"
        finally:
            with self._state_lock:
                self._reconfiguring = False
            self._complete_operation(operation, result=result, error=error_message)

    def submit_fps(self, requested_fps: int) -> dict:
        selection = self._select_settings(requested_fps)
        with self._lifecycle_lock:
            if not self.running or not self.thread or not self.thread.is_alive():
                raise RuntimeError("攝影機擷取服務尚未執行")
            if not self._operation_gate.acquire(blocking=False):
                raise CameraBusyError("已有相機設定正在套用")
            with self._state_lock:
                same_active_setting = (
                    self._connected
                    and (self.width, self.height, self.fps)
                    == (selection.width, selection.height, selection.fps)
                )
            operation = CameraOperation(selection=selection)
            with self._operation_lock:
                self._operations[operation.operation_id] = operation
                completed_ids = [
                    operation_id
                    for operation_id, old_operation in self._operations.items()
                    if old_operation.done.is_set()
                ]
                for operation_id in completed_ids[:-20]:
                    self._operations.pop(operation_id, None)
                if same_active_setting:
                    with self._state_lock:
                        self._requested_fps = selection.requested_fps
                    result = self._selection_result(selection)
                    operation.status = "succeeded"
                    operation.result = result
                    operation.done.set()
                    self._operation_gate.release()
                    return operation.to_dict()
                self._pending_operation = operation
                self._operation_event.set()
            return operation.to_dict()

    def get_operation(self, operation_id: str) -> Optional[dict]:
        with self._operation_lock:
            operation = self._operations.get(operation_id)
            return operation.to_dict() if operation is not None else None

    def _capture_loop(self):
        next_open_time = 0.0
        try:
            while self.running:
                operation = self._take_pending_operation()
                if operation is not None:
                    self._apply_operation(operation)
                    continue

                start_time = time.monotonic()
                with self._state_lock:
                    cap = self.cap
                    connected = self._connected
                frame = None

                if not connected or cap is None:
                    if start_time >= next_open_time:
                        selection = self._current_selection()
                        new_cap, frame = self._open_camera_for(selection)
                        if new_cap is not None and frame is not None:
                            self._activate_capture(new_cap, selection)
                            next_open_time = 0.0
                        else:
                            next_open_time = start_time + 2.0
                            # Publish an offline frame only once per retry period.
                            try:
                                self._publish_frame(
                                    self._offline_frame(selection), physical_frame=False
                                )
                            except Exception as error:
                                print(f"Offline frame generation failed: {error}")
                else:
                    try:
                        success, candidate = cap.read()
                        if success and self._valid_frame(candidate, self._current_selection()):
                            frame = candidate
                        else:
                            print("Failed to read frame. Releasing camera for retry.")
                            self._release_camera_on_capture_thread()
                            next_open_time = start_time + 2.0
                    except Exception as error:
                        print(f"Exception reading frame: {error}. Releasing camera.")
                        self._release_camera_on_capture_thread()
                        next_open_time = start_time + 2.0

                if frame is not None:
                    try:
                        self._publish_frame(frame, physical_frame=True)
                    except Exception as error:
                        print(f"Frame encoding failed: {error}. Releasing camera.")
                        self._release_camera_on_capture_thread()
                        next_open_time = time.monotonic() + 2.0

                elapsed = time.monotonic() - start_time
                with self._state_lock:
                    fps = self.fps
                if next_open_time > time.monotonic():
                    wait_time = min(2.0, next_open_time - time.monotonic())
                else:
                    wait_time = max(0.0, (1.0 / max(fps, 1)) - elapsed)
                self._operation_event.wait(timeout=wait_time)
        except BaseException as error:
            print(f"Fatal camera capture error: {error}")
        finally:
            self._release_camera_on_capture_thread()
            with self._lifecycle_lock:
                self.running = False
                self._fail_pending_operation("相機擷取執行緒已停止")
            with self._operation_lock:
                active = self._active_operation
            if active is not None and not active.done.is_set():
                self._complete_operation(active, error="相機擷取執行緒已停止")
            with self.frame_condition:
                self.frame_condition.notify_all()

    def get_frame(self) -> bytes:
        with self._state_lock:
            return self.latest_frame

    def wait_for_frame(
        self, last_sequence: int, timeout: float = 1.0
    ) -> Tuple[Optional[bytes], int]:
        with self.frame_condition:
            self.frame_condition.wait_for(
                lambda: (
                    self.latest_frame is not None and self.frame_sequence != last_sequence
                )
                or not self.running,
                timeout=timeout,
            )
            return self.latest_frame, self.frame_sequence

    def get_status(self) -> dict:
        with self._state_lock:
            mode = self._mode_for(
                self.width,
                self.height,
                self.fps,
                self._current_mode_id,
            )
            measured_fps = round(self._measured_fps, 2)
            measurement_status = (
                "offline"
                if not self._connected
                else "measured"
                if len(self._capture_times) >= 5
                else "warming_up"
            )
            return {
                "source": self.source,
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
                "requested_fps": self._requested_fps,
                "negotiated_fps": self.fps,
                "negotiated_width": self.width,
                "negotiated_height": self.height,
                "min_fps": self._capabilities.min_fps,
                "max_fps": self._capabilities.max_fps,
                "mode_min_fps": (
                    int(math.ceil(mode.min_fps - 0.001))
                    if mode is not None
                    else None
                ),
                "mode_max_fps": (
                    int(math.floor(mode.max_fps + 0.001))
                    if mode is not None
                    else None
                ),
                "mode_id": mode.id if mode is not None else None,
                "sensor_mode_index": (
                    mode.sensor_mode_index if mode is not None else None
                ),
                "pixel_format": mode.pixel_format if mode is not None else "NV12",
                "capability_provenance": self._capabilities.provenance,
                "measured_fps": measured_fps,
                "frame_sequence": self.frame_sequence,
                "reconfiguring": self._reconfiguring,
                "is_mock": False,
                "connected": self._connected,
                "requested": {
                    "fps": self._requested_fps,
                    "selection_rule": "highest_pixel_mode_supporting_requested_fps",
                },
                "negotiated": {
                    "mode_id": mode.id if mode is not None else None,
                    "sensor_mode_index": (
                        mode.sensor_mode_index if mode is not None else None
                    ),
                    "width": self.width,
                    "height": self.height,
                    "fps": self.fps,
                    "pixel_format": mode.pixel_format if mode is not None else "NV12",
                    "status": "negotiated" if self._connected else "offline",
                },
                "measured": {
                    "fps": measured_fps,
                    "sample_frames": len(self._capture_times),
                    "status": measurement_status,
                },
            }

    def get_capabilities(self) -> dict:
        # Discovery is cached for the reader lifecycle. This endpoint never
        # starts another Argus provider or CaptureSession.
        return self._capabilities.to_dict(self.get_status())
