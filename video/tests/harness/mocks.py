"""
tests/harness/mocks.py
Synthetic media sources, mock events, and contract test doubles for isolated testing.
"""

import os
import time
import enum
import typing
import threading
import datetime
from typing import Optional, List, Dict, Any, Tuple, Callable, NamedTuple
import numpy as np
import cv2
from PIL import Image, ImageDraw


# --- Interface Contracts from PROJECT.md ---

class CaptureMode(enum.Enum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"


class OutputFormat(enum.Enum):
    PNG = "png"
    JPG = "jpg"
    MP4 = "mp4"
    WEBM = "webm"


class Region(NamedTuple):
    x: int
    y: int
    width: int
    height: int


class EngineStatus(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"
    AUTO_ACTIVE = "auto_active"
    ERROR = "error"


class CaptureConfig:
    def __init__(
        self,
        mode: CaptureMode = CaptureMode.MANUAL,
        interval: float = 5.0,
        region: Optional[Region] = None,
        audio_enabled: bool = False,
        audio_source: str = "default",
        image_format: OutputFormat = OutputFormat.PNG,
        video_format: OutputFormat = OutputFormat.MP4,
        output_dir: str = "/tmp",
        use_hardware_accel: bool = True,
        fps: int = 30,
        bitrate_kbps: int = 4000,
    ):
        self.mode = mode if isinstance(mode, CaptureMode) else CaptureMode(mode)
        # Validate interval
        self.interval = float(interval)
        self.region = region
        self.audio_enabled = bool(audio_enabled)
        self.audio_source = str(audio_source)
        self.image_format = image_format if isinstance(image_format, OutputFormat) else OutputFormat(image_format)
        self.video_format = video_format if isinstance(video_format, OutputFormat) else OutputFormat(video_format)
        self.output_dir = output_dir
        self.use_hardware_accel = use_hardware_accel
        self.fps = fps
        self.bitrate_kbps = bitrate_kbps


class MediaItem(NamedTuple):
    filepath: str
    filename: str
    media_type: str  # 'image' or 'video'
    filesize: int
    timestamp: float
    thumbnail_path: Optional[str] = None


class MockScreenGrabber:
    """Generates synthetic RGB/BGR frame buffers for screen capture testing."""

    @staticmethod
    def generate_frame(width: int = 640, height: int = 480, frame_idx: int = 0) -> np.ndarray:
        """Creates a distinct color pattern with timestamp/frame counter overlay."""
        img = np.zeros((height, width, 3), dtype=np.uint8)
        # Gradient background
        xs = np.linspace(0, 255, width, dtype=np.uint8)
        img[:, :, 0] = xs
        img[:, :, 1] = int((frame_idx * 17) % 255)
        img[:, :, 2] = 160
        # Overlay distinct text
        cv2.putText(
            img,
            f"FRAME {frame_idx:04d}",
            (max(5, width // 10), max(20, height // 2)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6 if width < 400 else 1.0,
            (255, 255, 255),
            2,
        )
        return img

    @classmethod
    def save_synthetic_image(
        cls, filepath: str, width: int = 640, height: int = 480, fmt: str = "PNG"
    ) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        arr = cls.generate_frame(width, height, frame_idx=1)
        img = Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))
        fmt_name = "JPEG" if fmt.upper() in ("JPG", "JPEG") else "PNG"
        img.save(filepath, format=fmt_name)
        return filepath

    @classmethod
    def save_synthetic_video(
        cls,
        filepath: str,
        width: int = 320,
        height: int = 240,
        frames: int = 30,
        fps: float = 30.0,
        with_audio: bool = False,
    ) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        is_webm = filepath.lower().endswith(".webm")
        if is_webm:
            fourcc = cv2.VideoWriter_fourcc(*"VP80")
        else:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        # Ensure even dimensions for video codecs
        w = width if width % 2 == 0 else width + 1
        h = height if height % 2 == 0 else height + 1

        writer = cv2.VideoWriter(filepath, fourcc, fps, (w, h))
        if not writer.isOpened():
            if is_webm:
                fourcc = cv2.VideoWriter_fourcc(*"vp80")
            else:
                fourcc = cv2.VideoWriter_fourcc(*"avc1")
            writer = cv2.VideoWriter(filepath, fourcc, fps, (w, h))

        for i in range(max(1, frames)):
            frame = cls.generate_frame(w, h, frame_idx=i)
            writer.write(frame)
        writer.release()

        # If MP4 and faststart simulation requested, ensure moov is positioned
        if filepath.lower().endswith(".mp4") and os.path.exists(filepath):
            pass

        return filepath


class MockCaptureEngine:
    """Contract-compliant test double for CaptureEngine."""

    def __init__(self, default_config: Optional[CaptureConfig] = None):
        self.default_config = default_config or CaptureConfig()
        self.status = EngineStatus.IDLE
        self.active_config: Optional[CaptureConfig] = None
        self._auto_thread: Optional[threading.Thread] = None
        self._auto_stop_event = threading.Event()
        self._record_start_time: float = 0.0
        self._record_paused_accum: float = 0.0
        self._record_pause_start: float = 0.0
        self._current_recording_path: Optional[str] = None
        self._record_frames = 0
        self._lock = threading.Lock()

    def get_status(self) -> EngineStatus:
        with self._lock:
            return self.status

    def capture_screenshot(self, config: Optional[CaptureConfig] = None) -> str:
        cfg = config or self.active_config or self.default_config
        out_dir = cfg.output_dir
        if not os.path.exists(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as e:
                with self._lock:
                    self.status = EngineStatus.ERROR
                raise

        if not os.access(out_dir, os.W_OK):
            with self._lock:
                self.status = EngineStatus.ERROR
            raise PermissionError(f"Directory not writable: {out_dir}")

        ext = cfg.image_format.value if hasattr(cfg.image_format, "value") else str(cfg.image_format)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"capture_{ts}.{ext}"
        filepath = os.path.join(out_dir, filename)

        w, h = (1920, 1080)
        if cfg.region is not None:
            w = max(1, cfg.region.width)
            h = max(1, cfg.region.height)

        MockScreenGrabber.save_synthetic_image(filepath, width=w, height=h, fmt=ext)
        return filepath

    def start_recording(self, config: Optional[CaptureConfig] = None) -> None:
        with self._lock:
            if self.status == EngineStatus.RECORDING:
                return
            cfg = config or self.default_config
            self.active_config = cfg
            out_dir = cfg.output_dir
            if not os.path.exists(out_dir):
                os.makedirs(out_dir, exist_ok=True)
            if not os.access(out_dir, os.W_OK):
                self.status = EngineStatus.ERROR
                raise PermissionError(f"Directory not writable: {out_dir}")

            ext = cfg.video_format.value if hasattr(cfg.video_format, "value") else str(cfg.video_format)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"record_{ts}.{ext}"
            self._current_recording_path = os.path.join(out_dir, filename)
            self._record_start_time = time.monotonic()
            self._record_paused_accum = 0.0
            self.status = EngineStatus.RECORDING

    def pause_recording(self) -> None:
        with self._lock:
            if self.status == EngineStatus.RECORDING:
                self.status = EngineStatus.PAUSED
                self._record_pause_start = time.monotonic()

    def resume_recording(self) -> None:
        with self._lock:
            if self.status == EngineStatus.PAUSED:
                paused_duration = time.monotonic() - self._record_pause_start
                self._record_paused_accum += paused_duration
                self.status = EngineStatus.RECORDING

    def stop_recording(self) -> str:
        with self._lock:
            if self.status not in (EngineStatus.RECORDING, EngineStatus.PAUSED):
                raise RuntimeError("Cannot stop recording: engine is not actively recording")

            if self.status == EngineStatus.PAUSED:
                paused_duration = time.monotonic() - self._record_pause_start
                self._record_paused_accum += paused_duration

            total_elapsed = max(0.1, (time.monotonic() - self._record_start_time) - self._record_paused_accum)
            fps = self.active_config.fps if self.active_config else 30
            frames = int(max(1, total_elapsed * fps))
            filepath = self._current_recording_path

            w, h = (1280, 720)
            if self.active_config and self.active_config.region:
                w = self.active_config.region.width
                h = self.active_config.region.height

            # Adjust odd dimensions for H264
            w = w if w % 2 == 0 else w + 1
            h = h if h % 2 == 0 else h + 1

            MockScreenGrabber.save_synthetic_video(
                filepath,
                width=w,
                height=h,
                frames=frames,
                fps=float(fps),
                with_audio=self.active_config.audio_enabled if self.active_config else False,
            )

            self.status = EngineStatus.IDLE
            self._current_recording_path = None
            return filepath

    def start_auto_mode(self, interval: float, callback: Callable[[str], None]) -> None:
        with self._lock:
            if self.status == EngineStatus.AUTO_ACTIVE:
                self.stop_auto_mode()
            self.status = EngineStatus.AUTO_ACTIVE
            self._auto_stop_event.clear()

        def _loop():
            nonlocal interval
            target = time.monotonic()
            while not self._auto_stop_event.is_set():
                now = time.monotonic()
                if now >= target:
                    try:
                        path = self.capture_screenshot()
                        if callback:
                            callback(path)
                    except Exception:
                        pass
                    # Drift-free increment
                    target += max(0.05, interval)
                sleep_time = max(0.005, min(0.05, target - time.monotonic()))
                self._auto_stop_event.wait(timeout=sleep_time)

        self._auto_thread = threading.Thread(target=_loop, daemon=True)
        self._auto_thread.start()

    def stop_auto_mode(self) -> None:
        with self._lock:
            if self.status == EngineStatus.AUTO_ACTIVE:
                self._auto_stop_event.set()
                self.status = EngineStatus.IDLE
        if self._auto_thread and self._auto_thread.is_alive():
            self._auto_thread.join(timeout=1.0)
            self._auto_thread = None


class MockHotkeyManager:
    """Contract-compliant test double for HotkeyManager."""

    def __init__(self):
        self.bindings: Dict[str, Callable[[], None]] = {}
        self.is_running = False
        self._thread: Optional[threading.Thread] = None

    def register_hotkey(self, key_combo: str, callback: Callable[[], None]) -> bool:
        if not key_combo or not isinstance(key_combo, str) or key_combo.strip() == "":
            return False
        if "invalid" in key_combo.lower():
            return False
        self.bindings[key_combo.lower()] = callback
        return True

    def unregister_hotkey(self, key_combo: str) -> bool:
        k = key_combo.lower()
        if k in self.bindings:
            del self.bindings[k]
            return True
        return False

    def trigger_hotkey(self, key_combo: str) -> bool:
        k = key_combo.lower()
        if k in self.bindings:
            self.bindings[k]()
            return True
        return False

    def start(self) -> None:
        self.is_running = True

    def stop(self) -> None:
        self.is_running = False
        self.bindings.clear()


class MockTrayService:
    """Contract-compliant test double for TrayService."""

    def __init__(
        self,
        on_show_hide: Optional[Callable] = None,
        on_mode_toggle: Optional[Callable] = None,
        on_capture: Optional[Callable] = None,
        on_record: Optional[Callable] = None,
        on_quit: Optional[Callable] = None,
    ):
        self.on_show_hide = on_show_hide
        self.on_mode_toggle = on_mode_toggle
        self.on_capture = on_capture
        self.on_record = on_record
        self.on_quit = on_quit
        self.is_recording = False
        self.current_icon = "app-indicator"
        self.status = "ACTIVE"
        self.category = "APPLICATION_STATUS"

    def set_recording_state(self, is_recording: bool) -> None:
        self.is_recording = is_recording
        self.current_icon = "media-record" if is_recording else "app-indicator"

    def update_icon(self, icon_path_or_name: str) -> None:
        if not icon_path_or_name or not isinstance(icon_path_or_name, str):
            self.current_icon = "app-indicator"
            return
        if not os.path.exists(icon_path_or_name) and "/" in icon_path_or_name:
            self.current_icon = "app-indicator"
            return
        self.current_icon = icon_path_or_name


class MockFloatingBar:
    """Contract-compliant test double for FloatingBar overlay."""

    def __init__(self, root=None):
        self.visible = False
        self.is_paused = False
        self.timer_text = "00:00"
        self.on_pause: Optional[Callable] = None
        self.on_stop: Optional[Callable] = None
        self.x = 100
        self.y = 100
        self.width = 240
        self.height = 60

    def show_bar(self, on_pause: Optional[Callable] = None, on_stop: Optional[Callable] = None) -> None:
        self.visible = True
        self.on_pause = on_pause
        self.on_stop = on_stop

    def update_timer(self, elapsed_seconds: float) -> None:
        mins = int(elapsed_seconds) // 60
        secs = int(elapsed_seconds) % 60
        self.timer_text = f"{mins:02d}:{secs:02d}"

    def set_paused(self, is_paused: bool) -> None:
        self.is_paused = is_paused

    def hide_bar(self) -> None:
        self.visible = False

    def get_visible(self) -> bool:
        return self.visible


class MockRegionPicker:
    """Contract-compliant test double for RegionPicker."""

    def __init__(self):
        self.selected_region: Optional[Region] = None

    def select_region(self, x1: int, y1: int, x2: int, y2: int) -> Optional[Region]:
        x = min(x1, x2)
        y = min(y1, y2)
        w = abs(x2 - x1)
        h = abs(y2 - y1)
        if w <= 0 or h <= 0:
            return None
        self.selected_region = Region(x, y, w, h)
        return self.selected_region


class MockMediaManager:
    """Contract-compliant test double for MediaManager."""

    def __init__(self):
        self._thumbnails: Dict[str, str] = {}

    def scan_captures(self, output_dir: str) -> List[MediaItem]:
        if not os.path.exists(output_dir):
            return []
        items = []
        for fname in os.listdir(output_dir):
            if ".thumb." in fname or fname.startswith("."):
                continue
            fpath = os.path.join(output_dir, fname)
            if not os.path.isfile(fpath):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext in (".png", ".jpg", ".jpeg"):
                mtype = "image"
            elif ext in (".mp4", ".webm", ".avi", ".mkv"):
                mtype = "video"
            else:
                continue
            st = os.stat(fpath)
            items.append(
                MediaItem(
                    filepath=fpath,
                    filename=fname,
                    media_type=mtype,
                    filesize=st.st_size,
                    timestamp=st.st_mtime,
                    thumbnail_path=self._thumbnails.get(fpath),
                )
            )
        # Sort newest first
        items.sort(key=lambda it: it.timestamp, reverse=True)
        return items

    def get_thumbnail(self, item: MediaItem) -> Optional[str]:
        if item.filepath in self._thumbnails:
            return self._thumbnails[item.filepath]
        if not os.path.exists(item.filepath) or os.path.getsize(item.filepath) == 0:
            return None
        thumb_path = item.filepath + ".thumb.png"
        MockScreenGrabber.save_synthetic_image(thumb_path, 64, 64, "PNG")
        self._thumbnails[item.filepath] = thumb_path
        return thumb_path

    def delete_item(self, item: MediaItem) -> bool:
        if os.path.exists(item.filepath):
            os.remove(item.filepath)
        if item.filepath in self._thumbnails:
            thumb = self._thumbnails.pop(item.filepath)
            if os.path.exists(thumb):
                os.remove(thumb)
        return True


class MockVideoPlayer:
    """Contract-compliant test double for VideoPlayer."""

    def __init__(self):
        self.current_filepath: Optional[str] = None
        self.duration: float = 0.0
        self.position: float = 0.0
        self.playing: bool = False

    def load_media(self, filepath: str) -> bool:
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            self.current_filepath = None
            self.duration = 0.0
            return False
        self.current_filepath = filepath
        cap = cv2.VideoCapture(filepath)
        if cap.isOpened():
            ret, _ = cap.read()
            if not ret:
                cap.release()
                self.current_filepath = None
                self.duration = 0.0
                return False
            fc = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            self.duration = fc / fps if fps > 0 else 0.0
            cap.release()
        else:
            self.current_filepath = None
            self.duration = 0.0
            return False
        self.position = 0.0
        self.playing = False
        return True

    def play(self) -> None:
        if self.current_filepath:
            self.playing = True

    def pause(self) -> None:
        self.playing = False

    def is_playing(self) -> bool:
        return self.playing

    def get_duration(self) -> float:
        return self.duration

    def get_position(self) -> float:
        return self.position

    def seek(self, position: float) -> None:
        if self.duration <= 0:
            self.position = 0.0
        else:
            self.position = max(0.0, min(self.duration, float(position)))


class MockAppWindow:
    """Headless window container modeling the single-window interface."""

    def __init__(self, config: Optional[CaptureConfig] = None):
        self.config = config or CaptureConfig()
        self.engine = MockCaptureEngine(self.config)
        self.hotkeys = MockHotkeyManager()
        self.tray = MockTrayService()
        self.floating_bar = MockFloatingBar()
        self.media_manager = MockMediaManager()
        self.video_player = MockVideoPlayer()
        self.visible = True
        self.title = "Screen Capture & Recording"
        self.width = 1024
        self.height = 768
        self.position = (100, 100)
        self.mode = self.config.mode
        self.interval = self.config.interval
        self.status_badge = "IDLE"
        self.children = [
            "HeaderWidget",
            "ControlsWidget",
            "MediaPanelWidget",
        ]

    def resize(self, width: int, height: int) -> None:
        self.width = max(100, width)
        self.height = max(100, height)

    def get_position(self) -> Tuple[int, int]:
        return self.position

    def move(self, x: int, y: int) -> None:
        self.position = (x, y)

    def get_visible(self) -> bool:
        return self.visible

    def show_all(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def maximize(self) -> None:
        pass

    def unmaximize(self) -> None:
        pass

    def iconify(self) -> None:
        self.visible = False

    def deiconify(self) -> None:
        self.visible = True

    def destroy(self) -> None:
        self.visible = False
        self.engine.stop_auto_mode()
        self.hotkeys.stop()
