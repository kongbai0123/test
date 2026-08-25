"""
Unified exports for the test harness.
"""

from tests.harness.display import DisplayManager
from tests.harness.media_validator import (
    ImageValidator,
    VideoValidator,
    AudioValidator,
    MediaValidator,
)
from tests.harness.mocks import (
    CaptureMode,
    OutputFormat,
    Region,
    EngineStatus,
    CaptureConfig,
    MediaItem,
    MockScreenGrabber,
    MockCaptureEngine,
    MockHotkeyManager,
    MockTrayService,
    MockFloatingBar,
    MockRegionPicker,
    MockMediaManager,
    MockVideoPlayer,
    MockAppWindow,
)
from tests.harness.base import (
    BaseE2ETestCase,
    BaseHeadlessGuiTestCase,
    BaseTestCase,
)

__all__ = [
    "DisplayManager",
    "ImageValidator",
    "VideoValidator",
    "AudioValidator",
    "MediaValidator",
    "CaptureMode",
    "OutputFormat",
    "Region",
    "EngineStatus",
    "CaptureConfig",
    "MediaItem",
    "MockScreenGrabber",
    "MockCaptureEngine",
    "MockHotkeyManager",
    "MockTrayService",
    "MockFloatingBar",
    "MockRegionPicker",
    "MockMediaManager",
    "MockVideoPlayer",
    "MockAppWindow",
    "BaseE2ETestCase",
    "BaseHeadlessGuiTestCase",
    "BaseTestCase",
]
