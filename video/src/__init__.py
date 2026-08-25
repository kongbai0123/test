"""
Screen Capture & Recording GUI Application.
"""

from src.config import (
    CaptureConfig,
    CaptureMode,
    DEFAULT_CAPTURES_DIR,
    EngineStatus,
    MAX_INTERVAL,
    MIN_INTERVAL,
    OutputFormat,
    Region,
)
from src.engine import (
    AudioDevice,
    AudioDiscovery,
    AudioMixer,
    AutoScheduler,
    CaptureEngine,
    CameraStream,
    enumerate_v4l2_capabilities,
    MonotonicScheduler,
    ScreenGrabber,
    ScreenshotEngine,
    select_mode_for_fps,
    VideoRecorder,
)

__version__ = "1.0.0"

__all__ = [
    "CaptureConfig",
    "CaptureMode",
    "OutputFormat",
    "EngineStatus",
    "Region",
    "MIN_INTERVAL",
    "MAX_INTERVAL",
    "DEFAULT_CAPTURES_DIR",
    "CaptureEngine",
    "CameraStream",
    "enumerate_v4l2_capabilities",
    "select_mode_for_fps",
    "ScreenshotEngine",
    "ScreenGrabber",
    "VideoRecorder",
    "AudioDiscovery",
    "AudioDevice",
    "AudioMixer",
    "MonotonicScheduler",
    "AutoScheduler",
]
