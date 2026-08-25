"""
src/config.py
Configuration models, enums, Region geometry, validation, and serialization.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, NamedTuple, Optional, Tuple, Union


# Sony IMX219 CSI modes reported by this Jetson's device tree. The UI accepts
# an FPS target and selects the highest-pixel sensor mode that can sustain it.
CAMERA_MIN_FPS: int = 2
CAMERA_MAX_FPS: int = 60
IMX219_SENSOR_MODES: Tuple[Tuple[int, int, int], ...] = (
    (3280, 2464, 21),
    (3280, 1848, 28),
    (1920, 1080, 30),
    (1640, 1232, 30),
    (1280, 720, 60),
)


@dataclass(frozen=True)
class CameraFpsSelection:
    """A bounded FPS request and its automatically selected sensor mode."""

    requested_fps: int
    fps: int
    width: int
    height: int
    mode_max_fps: int

    @property
    def was_clamped(self) -> bool:
        return self.requested_fps != self.fps


def select_imx219_settings(requested_fps: int) -> CameraFpsSelection:
    """Clamp FPS to 2..60 and retain the maximum supported pixel count."""
    requested = int(requested_fps)
    fps = max(CAMERA_MIN_FPS, min(CAMERA_MAX_FPS, requested))
    # Modes are ordered by descending pixel count. At 30 FPS, for example,
    # 1920x1080 wins over 1640x1232 because it has slightly more pixels.
    for width, height, max_fps in IMX219_SENSOR_MODES:
        if fps <= max_fps:
            return CameraFpsSelection(requested, fps, width, height, max_fps)
    width, height, max_fps = IMX219_SENSOR_MODES[-1]
    return CameraFpsSelection(requested, fps, width, height, max_fps)


class CaptureMode(Enum):
    """Screen capture execution mode."""
    MANUAL = "manual"
    AUTOMATIC = "automatic"

    @classmethod
    def from_string(cls, val: str) -> CaptureMode:
        clean = val.strip().lower()
        for member in cls:
            if member.value == clean:
                return member
        raise ValueError(f"Unsupported CaptureMode: '{val}'. Valid options: {[m.value for m in cls]}")


class OutputFormat(Enum):
    """Supported output image and video container formats."""
    PNG = "png"
    JPG = "jpg"
    MP4 = "mp4"
    WEBM = "webm"

    @property
    def is_image(self) -> bool:
        return self in (OutputFormat.PNG, OutputFormat.JPG)

    @property
    def is_video(self) -> bool:
        return self in (OutputFormat.MP4, OutputFormat.WEBM)

    @property
    def file_extension(self) -> str:
        return f".{self.value}"

    @property
    def mime_type(self) -> str:
        _map = {
            OutputFormat.PNG: "image/png",
            OutputFormat.JPG: "image/jpeg",
            OutputFormat.MP4: "video/mp4",
            OutputFormat.WEBM: "video/webm",
        }
        return _map[self]

    @classmethod
    def from_string(cls, val: str) -> OutputFormat:
        clean = val.strip().lower().lstrip(".")
        for member in cls:
            if member.value == clean or (clean == "jpeg" and member == OutputFormat.JPG):
                return member
        raise ValueError(f"Unsupported OutputFormat: '{val}'. Valid options: {[m.value for m in cls]}")


class EngineStatus(Enum):
    """State of the Core Capture Engine."""
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"
    AUTO_ACTIVE = "auto_active"


class Region(NamedTuple):
    """Screen coordinate bounding box (x, y, width, height)."""
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    def to_box(self) -> Tuple[int, int, int, int]:
        """Returns PIL/Gdk bounding box (left, top, right, bottom)."""
        return (self.x, self.y, self.right, self.bottom)

    def to_gstreamer_crop(self) -> Tuple[int, int, int, int]:
        """Returns ximagesrc bounds (startx, starty, endx, endy)."""
        return (self.x, self.y, max(self.x, self.right - 1), max(self.y, self.bottom - 1))

    @classmethod
    def from_points(cls, x1: int, y1: int, x2: int, y2: int) -> Region:
        """Constructs Region from two opposite corners, normalizing inverted drags."""
        min_x = min(int(x1), int(x2))
        min_y = min(int(y1), int(y2))
        w = max(1, abs(int(x2) - int(x1)))
        h = max(1, abs(int(y2) - int(y1)))
        return cls(x=max(0, min_x), y=max(0, min_y), width=w, height=h)


# Constants
MIN_INTERVAL: float = 0.5       # Minimum capture interval in seconds
MAX_INTERVAL: float = 3600.0    # Maximum capture interval in seconds (1 hour)
DEFAULT_CAPTURES_DIR: str = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures")
)


@dataclass
class CaptureConfig:
    """Central configuration for screenshots and video recordings."""
    mode: CaptureMode = CaptureMode.MANUAL
    interval: float = 3.0
    capture_source: str = "camera"
    region: Optional[Region] = None
    audio_enabled: bool = False
    audio_source: str = "default"
    image_format: OutputFormat = OutputFormat.PNG
    video_format: OutputFormat = OutputFormat.MP4
    output_dir: str = field(default_factory=lambda: DEFAULT_CAPTURES_DIR)
    fps: int = 30
    camera_width: int = 0
    camera_height: int = 0
    camera_pixel_format: str = ""
    jpg_quality: int = 90
    nvenc_enabled: bool = True

    def validate(self) -> None:
        """
        Exhaustive validation of all configuration parameters.
        Raises ValueError or TypeError on invalid configurations.
        """
        # 1. Mode validation
        if not isinstance(self.mode, CaptureMode):
            if isinstance(self.mode, str):
                self.mode = CaptureMode.from_string(self.mode)
            else:
                raise TypeError(f"Invalid mode type: {type(self.mode).__name__}")

        # 2. Interval validation (0.5s - 3600.0s)
        try:
            val = float(self.interval)
            if not (MIN_INTERVAL <= val <= MAX_INTERVAL):
                raise ValueError(f"Capture interval must be between {MIN_INTERVAL}s and {MAX_INTERVAL}s, got {val}s.")
            self.interval = val
        except (TypeError, ValueError) as e:
            if "between" in str(e):
                raise
            raise ValueError(f"Invalid interval value '{self.interval}': must be a numeric value.") from e

        # 3. Region validation
        if self.region is not None:
            if not isinstance(self.region, Region):
                if isinstance(self.region, (tuple, list)) and len(self.region) == 4:
                    self.region = Region(*[int(v) for v in self.region])
                else:
                    raise TypeError(f"Region must be an instance of Region or 4-tuple, got {type(self.region).__name__}")
            if self.region.x < 0 or self.region.y < 0:
                raise ValueError(f"Region coordinates cannot be negative: x={self.region.x}, y={self.region.y}")
            if self.region.width < 1 or self.region.height < 1:
                raise ValueError(f"Region width and height must be >= 1: width={self.region.width}, height={self.region.height}")

        # 4. Formats validation
        if not isinstance(self.image_format, OutputFormat):
            if isinstance(self.image_format, str):
                self.image_format = OutputFormat.from_string(self.image_format)
            else:
                raise TypeError(f"Invalid image_format type: {type(self.image_format).__name__}")
        if not self.image_format.is_image:
            raise ValueError(f"image_format must be PNG or JPG, got {self.image_format.value}")

        if not isinstance(self.video_format, OutputFormat):
            if isinstance(self.video_format, str):
                self.video_format = OutputFormat.from_string(self.video_format)
            else:
                raise TypeError(f"Invalid video_format type: {type(self.video_format).__name__}")
        if not self.video_format.is_video:
            raise ValueError(f"video_format must be MP4 or WEBM, got {self.video_format.value}")

        # 5. Output Directory validation and auto-creation
        if not self.output_dir or not isinstance(self.output_dir, str):
            raise ValueError("output_dir must be a non-empty string path.")
        self.output_dir = os.path.abspath(self.output_dir)
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError as e:
            raise ValueError(f"Failed to create or access output directory '{self.output_dir}': {e}") from e

        # 6. Audio parameters
        if not isinstance(self.audio_enabled, bool):
            self.audio_enabled = bool(self.audio_enabled)
        if not isinstance(self.audio_source, str) or not self.audio_source.strip():
            self.audio_source = "default"

        # 7. Additional parameters
        try:
            fps_val = int(self.fps)
            if not (1 <= fps_val <= 120):
                raise ValueError(f"FPS must be between 1 and 120, got {fps_val}")
            self.fps = fps_val
        except (TypeError, ValueError) as e:
            if "between" in str(e):
                raise
            raise ValueError(f"Invalid FPS value '{self.fps}'") from e

        for field_name in ("camera_width", "camera_height"):
            try:
                dimension = int(getattr(self, field_name))
            except (TypeError, ValueError) as e:
                raise ValueError(f"Invalid {field_name} value") from e
            if not (0 <= dimension <= 16384):
                raise ValueError(f"{field_name} must be between 0 and 16384")
            setattr(self, field_name, dimension)
        self.camera_pixel_format = str(self.camera_pixel_format or "").strip().upper()

        try:
            qual_val = int(self.jpg_quality)
            if not (1 <= qual_val <= 100):
                raise ValueError(f"JPG quality must be between 1 and 100, got {qual_val}")
            self.jpg_quality = qual_val
        except (TypeError, ValueError) as e:
            if "between" in str(e):
                raise
            raise ValueError(f"Invalid JPG quality value '{self.jpg_quality}'") from e

        if not isinstance(self.nvenc_enabled, bool):
            self.nvenc_enabled = bool(self.nvenc_enabled)

    def __post_init__(self) -> None:
        self.validate()

    def to_dict(self) -> Dict[str, Any]:
        """Serializes configuration to a JSON-compatible dictionary."""
        return {
            "mode": self.mode.value,
            "interval": self.interval,
            "capture_source": self.capture_source,
            "region": self.region.to_tuple() if self.region else None,
            "audio_enabled": self.audio_enabled,
            "audio_source": self.audio_source,
            "image_format": self.image_format.value,
            "video_format": self.video_format.value,
            "output_dir": self.output_dir,
            "fps": self.fps,
            "camera_width": self.camera_width,
            "camera_height": self.camera_height,
            "camera_pixel_format": self.camera_pixel_format,
            "jpg_quality": self.jpg_quality,
            "nvenc_enabled": self.nvenc_enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CaptureConfig:
        """Constructs and validates a CaptureConfig from a dictionary."""
        region = None
        if data.get("region") is not None:
            r_data = data["region"]
            if isinstance(r_data, (tuple, list)) and len(r_data) == 4:
                region = Region(int(r_data[0]), int(r_data[1]), int(r_data[2]), int(r_data[3]))
            elif isinstance(r_data, dict):
                region = Region(int(r_data["x"]), int(r_data["y"]), int(r_data["width"]), int(r_data["height"]))

        return cls(
            mode=CaptureMode.from_string(data["mode"]) if "mode" in data else CaptureMode.MANUAL,
            interval=float(data.get("interval", 5.0)),
            capture_source=str(data.get("capture_source", "camera")),
            region=region,
            audio_enabled=bool(data.get("audio_enabled", False)),
            audio_source=str(data.get("audio_source", "default")),
            image_format=OutputFormat.from_string(data["image_format"]) if "image_format" in data else OutputFormat.PNG,
            video_format=OutputFormat.from_string(data["video_format"]) if "video_format" in data else OutputFormat.MP4,
            output_dir=str(data.get("output_dir", DEFAULT_CAPTURES_DIR)),
            fps=int(data.get("fps", 30)),
            camera_width=int(data.get("camera_width", 0)),
            camera_height=int(data.get("camera_height", 0)),
            camera_pixel_format=str(data.get("camera_pixel_format", "")),
            jpg_quality=int(data.get("jpg_quality", 90)),
            nvenc_enabled=bool(data.get("nvenc_enabled", True)),
        )
