"""
src/engine/recorder.py
Video recording engine supporting MP4 (with faststart) and WebM containers,
NVENC hardware acceleration with x264/VP8/VP9 CPU fallback, audio muxing,
even-dimension ROI cropping, and thread-safe Pause/Resume/Stop lifecycle.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import threading
import time
from typing import Optional, Tuple

import gi
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

Gst.init(None)

from src.config import CaptureConfig, EngineStatus, OutputFormat, Region
from src.engine.audio import AudioMixer
from src.engine.camera import NVIDIA_CAMERA_STREAM_URL
from src.engine.screenshot import normalize_roi, ScreenshotEngine

logger = logging.getLogger("CaptureEngine.Recorder")


def normalize_video_roi(region: Optional[Region], screen_w: int, screen_h: int) -> Tuple[int, int, int, int]:
    """
    Normalizes ROI coordinates for video encoders, enforcing even width & height
    (w % 2 == 0, h % 2 == 0) and preventing boundary overflows.

    Args:
        region: Optional Region namedtuple (x, y, width, height) or None for full screen.
        screen_w: Screen width in pixels.
        screen_h: Screen height in pixels.

    Returns:
        (x, y, width, height) with even width and height, fully clamped.
    """
    if screen_w <= 0:
        screen_w = 1920
    if screen_h <= 0:
        screen_h = 1080

    x, y, w, h = normalize_roi(region, screen_w, screen_h)

    # 1. Enforce even dimensions (minimum 2x2)
    w = max(2, w - (w % 2))
    h = max(2, h - (h % 2))

    # 2. Prevent right/bottom boundary overflow
    if x + w > screen_w:
        shift = (x + w) - screen_w
        x = max(0, x - shift)
        if x + w > screen_w:
            avail_w = screen_w - x
            w = max(2, avail_w - (avail_w % 2))

    if y + h > screen_h:
        shift = (y + h) - screen_h
        y = max(0, y - shift)
        if y + h > screen_h:
            avail_h = screen_h - y
            h = max(2, avail_h - (avail_h % 2))

    return x, y, w, h


class VideoRecorder:
    """
    Thread-safe GStreamer-based screen video recorder with hardware acceleration,
    audio muxing, and a robust Pause / Resume / Stop state machine.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._status: EngineStatus = EngineStatus.IDLE
        self._pipeline: Optional[Gst.Pipeline] = None
        self._output_file: Optional[str] = None
        self._active_config: Optional[CaptureConfig] = None
        self._screenshot_engine = ScreenshotEngine()

        # Monotonic time tracking
        self._start_time: float = 0.0
        self._pause_time: float = 0.0
        self._accumulated_duration: float = 0.0

        # Error tracking
        self._last_error: Optional[str] = None

    @property
    def status(self) -> EngineStatus:
        """Returns the current EngineStatus (IDLE, RECORDING, PAUSED)."""
        with self._lock:
            return self._status

    def is_recording(self) -> bool:
        """Returns True if recording is actively running."""
        with self._lock:
            return self._status == EngineStatus.RECORDING

    def is_paused(self) -> bool:
        """Returns True if recording is paused."""
        with self._lock:
            return self._status == EngineStatus.PAUSED

    def get_elapsed_seconds(self) -> float:
        """
        Returns total active recording duration in seconds (excluding paused intervals).
        Monotonically increasing during active recording.
        """
        with self._lock:
            if self._status == EngineStatus.RECORDING:
                return self._accumulated_duration + max(0.0, time.monotonic() - self._start_time)
            elif self._status == EngineStatus.PAUSED:
                return self._accumulated_duration
            return 0.0

    def _build_pipeline_string(
        self,
        output_path: str,
        x: int,
        y: int,
        w: int,
        h: int,
        fps: int,
        format_type: OutputFormat,
        audio_enabled: bool,
        audio_source: str,
        nvenc_enabled: bool = True,
        capture_source: str = "camera",
        camera_width: int = 0,
        camera_height: int = 0,
        camera_pixel_format: str = "",
    ) -> str:
        """Constructs the complete GStreamer pipeline string."""
        endx = x + w - 1
        endy = y + h - 1

        # Video source selection: Nvidia Jetson CSI (nvarguscamerasrc) vs V4L2 (nvv4l2camerasrc / v4l2src) vs camera test feed
        if capture_source == "nvidia_stream":
            vsrc = (
                f'souphttpsrc location="{NVIDIA_CAMERA_STREAM_URL}" '
                'is-live=true timeout=5 ! multipartdemux single-stream=true ! '
                'image/jpeg ! jpegdec ! videorate'
            )
        elif capture_source.startswith("v4l2:"):
            device_path = capture_source[len("v4l2:"):]
            if re.fullmatch(r"/dev/video\d+", device_path) is None:
                raise ValueError(f"Invalid V4L2 camera path: {device_path!r}")
            width = int(camera_width or 0)
            height = int(camera_height or 0)
            pixel_format = str(camera_pixel_format or "").strip().upper()
            size_caps = (
                f",width={width},height={height}"
                if width > 0 and height > 0
                else ""
            )
            # V4L2 settings belong to each open file handle. Recording opens a
            # new handle after preview stops, so repeat the smart-selected mode
            # here instead of relying on the previous OpenCV negotiation.
            if pixel_format in ("MJPG", "JPEG"):
                vsrc = (
                    f'v4l2src device="{device_path}" ! '
                    f'image/jpeg{size_caps},framerate={fps}/1 ! jpegdec ! videorate'
                )
            else:
                raw_formats = {
                    "YUYV": "YUY2",
                    "YUY2": "YUY2",
                    "UYVY": "UYVY",
                    "NV12": "NV12",
                    "RGB3": "RGB",
                    "BGR3": "BGR",
                    "GREY": "GRAY8",
                }
                gst_format = raw_formats.get(pixel_format)
                if gst_format:
                    vsrc = (
                        f'v4l2src device="{device_path}" ! '
                        f'video/x-raw,format={gst_format}{size_caps},framerate={fps}/1 '
                        f'! videorate'
                    )
                else:
                    # Unknown/compressed formats remain broadly compatible;
                    # videorate still guarantees the requested encoded output.
                    vsrc = f'v4l2src device="{device_path}" ! decodebin ! videorate'
        elif capture_source == "camera":
            if Gst.ElementFactory.find("nvarguscamerasrc") is not None:
                vsrc = "nvarguscamerasrc sensor-id=0 ! video/x-raw(memory:NVMM), width=1280, height=720, framerate=30/1 ! nvvidconv"
            elif Gst.ElementFactory.find("nvv4l2camerasrc") is not None and os.path.exists("/dev/video0"):
                vsrc = "nvv4l2camerasrc device=/dev/video0 ! nvvidconv"
            elif Gst.ElementFactory.find("v4l2src") is not None and os.path.exists("/dev/video0"):
                vsrc = "v4l2src device=/dev/video0"
            else:
                vsrc = f"videotestsrc is-live=true ! video/x-raw,width=1280,height=720,framerate={fps}/1 ! clockoverlay text=\"📷 CAMERA VIDEO STREAM [LIVE] \" time-format=\"%Y-%m-%d %H:%M:%S\" font-desc=\"Sans Bold 14\""
        elif capture_source == "camera_test":
            vsrc = f"videotestsrc is-live=true ! video/x-raw,width=1280,height=720,framerate={fps}/1 ! clockoverlay text=\"📷 CAMERA VIDEO STREAM [LIVE] \" time-format=\"%Y-%m-%d %H:%M:%S\" font-desc=\"Sans Bold 14\""
        else:
            vsrc = f"ximagesrc startx={x} starty={y} endx={endx} endy={endy} use-damage=0"

        # Probe NVENC capabilities
        has_nvenc = False
        if nvenc_enabled:
            has_nvenc = (
                Gst.ElementFactory.find("nvh264enc") is not None
                or Gst.ElementFactory.find("nvv4l2h264enc") is not None
            )

        if format_type == OutputFormat.MP4:
            if has_nvenc:
                if Gst.ElementFactory.find("nvh264enc") is not None:
                    venc = "nvh264enc bitrate=4000 ! video/x-h264,profile=baseline"
                else:
                    venc = "nvv4l2h264enc bitrate=4000000 ! video/x-h264,profile=baseline"
            else:
                venc = "x264enc speed-preset=ultrafast tune=zerolatency bitrate=4000 ! video/x-h264,profile=baseline"

            if not audio_enabled:
                return (
                    f"{vsrc} ! video/x-raw,framerate={fps}/1 ! videoconvert ! "
                    f"{venc} ! mp4mux faststart=true ! filesink location=\"{output_path}\""
                )
            else:
                audio_branch = AudioMixer.build_audio_branch(
                    device_id=audio_source,
                    format_type="mp4",
                )
                return (
                    f"mp4mux name=mux faststart=true ! filesink location=\"{output_path}\" "
                    f"{vsrc} ! video/x-raw,framerate={fps}/1 ! videoconvert ! "
                    f"{venc} ! queue max-size-buffers=100 max-size-time=2000000000 ! mux.video_0 "
                    f"{audio_branch}"
                )
        else:  # WebM
            if Gst.ElementFactory.find("vp8enc") is not None:
                venc = "vp8enc deadline=1 cpu-used=8"
            elif Gst.ElementFactory.find("vp9enc") is not None:
                venc = "vp9enc deadline=1 cpu-used=8"
            else:
                venc = "vp8enc"

            if not audio_enabled:
                return (
                    f"{vsrc} ! video/x-raw,framerate={fps}/1 ! videoconvert ! "
                    f"{venc} ! webmmux ! filesink location=\"{output_path}\""
                )
            else:
                audio_branch = AudioMixer.build_audio_branch(
                    device_id=audio_source,
                    format_type="webm",
                )
                return (
                    f"webmmux name=mux ! filesink location=\"{output_path}\" "
                    f"{vsrc} ! video/x-raw,framerate={fps}/1 ! videoconvert ! "
                    f"{venc} ! queue max-size-buffers=100 max-size-time=2000000000 ! mux.video_0 "
                    f"{audio_branch}"
                )

    def start(self, filepath: str, config: Optional[CaptureConfig] = None) -> None:
        """
        Starts video recording to the given filepath.

        Args:
            filepath: Destination video file path.
            config: Optional CaptureConfig overriding default configuration.
        """
        with self._lock:
            if self._status != EngineStatus.IDLE:
                raise RuntimeError(f"Cannot start recording: engine is in state '{self._status.value}' (must be IDLE)")

            active_config = config or CaptureConfig()
            active_config.validate()

            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            self._output_file = os.path.abspath(filepath)
            self._active_config = active_config

            screen_w, screen_h = self._screenshot_engine.get_screen_size()
            x, y, w, h = normalize_video_roi(active_config.region, screen_w, screen_h)

            pipe_str = self._build_pipeline_string(
                output_path=self._output_file,
                x=x,
                y=y,
                w=w,
                h=h,
                fps=active_config.fps,
                format_type=active_config.video_format,
                audio_enabled=active_config.audio_enabled,
                audio_source=active_config.audio_source,
                nvenc_enabled=active_config.nvenc_enabled,
                capture_source=active_config.capture_source,
                camera_width=active_config.camera_width,
                camera_height=active_config.camera_height,
                camera_pixel_format=active_config.camera_pixel_format,
            )
            logger.info(f"Launching GStreamer recording pipeline: {pipe_str}")

            try:
                self._pipeline = Gst.parse_launch(pipe_str)
            except Exception as e:
                # If v4l2src failed, retry with camera test source (NEVER screen)
                logger.warning(f"Pipeline launch failed ({e}). Retrying with camera test stream...")
                pipe_str = self._build_pipeline_string(
                    output_path=self._output_file,
                    x=x,
                    y=y,
                    w=w,
                    h=h,
                    fps=active_config.fps,
                    format_type=active_config.video_format,
                    audio_enabled=False,
                    audio_source="none",
                    nvenc_enabled=active_config.nvenc_enabled,
                    capture_source="camera_test",
                    camera_width=active_config.camera_width,
                    camera_height=active_config.camera_height,
                    camera_pixel_format=active_config.camera_pixel_format,
                )
                self._pipeline = Gst.parse_launch(pipe_str)

            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                # Retry with camera test stream (NEVER screen)
                logger.warning("Camera pipeline PLAYING failed. Switching to camera test stream...")
                self._pipeline.set_state(Gst.State.NULL)
                pipe_str = self._build_pipeline_string(
                    output_path=self._output_file,
                    x=x,
                    y=y,
                    w=w,
                    h=h,
                    fps=active_config.fps,
                    format_type=active_config.video_format,
                    audio_enabled=False,
                    audio_source="none",
                    nvenc_enabled=active_config.nvenc_enabled,
                    capture_source="camera_test",
                    camera_width=active_config.camera_width,
                    camera_height=active_config.camera_height,
                    camera_pixel_format=active_config.camera_pixel_format,
                )
                self._pipeline = Gst.parse_launch(pipe_str)
                ret = self._pipeline.set_state(Gst.State.PLAYING)

                if ret == Gst.StateChangeReturn.FAILURE:
                    self._pipeline.set_state(Gst.State.NULL)
                    self._pipeline = None
                    raise RuntimeError("GStreamer camera pipeline failed to transition to PLAYING state")

            self._accumulated_duration = 0.0
            self._start_time = time.monotonic()
            self._status = EngineStatus.RECORDING
            logger.info(f"Video recording started: {self._output_file}")

    def start_recording(self, config: Optional[CaptureConfig] = None) -> None:
        """Starts recording with automatic timestamped filename generation in output_dir."""
        with self._lock:
            if self._status != EngineStatus.IDLE:
                raise RuntimeError(f"Cannot start recording: engine is in state '{self._status.value}'")

            active_config = config or CaptureConfig()
            active_config.validate()

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = active_config.video_format.value
            filename = f"Recording_{timestamp}.{ext}"
            filepath = os.path.join(active_config.output_dir, filename)

            # Deduplicate filename if already exists
            counter = 1
            while os.path.exists(filepath):
                filepath = os.path.join(active_config.output_dir, f"Recording_{timestamp}_{counter:02d}.{ext}")
                counter += 1

            self.start(filepath=filepath, config=active_config)

    def pause(self) -> None:
        """Pauses the active recording without dropping timestamp synchronization."""
        with self._lock:
            if self._status != EngineStatus.RECORDING:
                raise RuntimeError(f"Cannot pause recording: engine is in state '{self._status.value}' (must be RECORDING)")

            if self._pipeline:
                self._pipeline.set_state(Gst.State.PAUSED)

            self._accumulated_duration += max(0.0, time.monotonic() - self._start_time)
            self._pause_time = time.monotonic()
            self._status = EngineStatus.PAUSED
            logger.info("Video recording paused")

    def pause_recording(self) -> None:
        """Alias for pause()."""
        self.pause()

    def resume(self) -> None:
        """Resumes a paused recording."""
        with self._lock:
            if self._status != EngineStatus.PAUSED:
                raise RuntimeError(f"Cannot resume recording: engine is in state '{self._status.value}' (must be PAUSED)")

            if self._pipeline:
                self._pipeline.set_state(Gst.State.PLAYING)

            self._start_time = time.monotonic()
            self._status = EngineStatus.RECORDING
            logger.info("Video recording resumed")

    def resume_recording(self) -> None:
        """Alias for resume()."""
        self.resume()

    def stop(self) -> str:
        """
        Stops recording cleanly, sends EOS to finalize container headers, and returns filepath.
        """
        with self._lock:
            if self._status not in (EngineStatus.RECORDING, EngineStatus.PAUSED):
                raise RuntimeError(f"Cannot stop recording: engine is in state '{self._status.value}' (must be RECORDING or PAUSED)")

            output_file = self._output_file or ""

            if self._pipeline:
                try:
                    # If paused, transition back to PLAYING so pipeline can process the EOS event
                    if self._status == EngineStatus.PAUSED:
                        self._pipeline.set_state(Gst.State.PLAYING)

                    # Send EOS event to finalize muxer container
                    self._pipeline.send_event(Gst.Event.new_eos())
                    bus = self._pipeline.get_bus()
                    if bus:
                        bus.timed_pop_filtered(1500 * Gst.MSECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
                except Exception as e:
                    logger.warning(f"Error during EOS flush: {e}")
                finally:
                    try:
                        self._pipeline.set_state(Gst.State.NULL)
                    except Exception:
                        pass
                    self._pipeline = None

            self._status = EngineStatus.IDLE
            self._output_file = None
            logger.info(f"Video recording stopped and finalized: {output_file}")
            return output_file

    def stop_recording(self) -> str:
        """Alias for stop()."""
        return self.stop()
