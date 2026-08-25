"""
tests/tier3_combinations/test_tray_quick_capture_floating_bar.py
Tier 3: Combination of F2 (Tray) + F4 (Floating Bar) + F5 (Manual) + F10 (Video Recording).
Verifies triggering quick screenshot from tray menu while recording with floating bar active.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    MockFloatingBar,
    MockTrayService,
    CaptureConfig,
    EngineStatus,
)


class TestTrayQuickCaptureFloatingBar(BaseE2ETestCase):
    """Test quick screenshot via tray while recording with floating bar visible."""

    def test_quick_capture_during_active_recording_and_floating_bar(self):
        """Verify screenshot can be taken via tray without interrupting video recording."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        bar = MockFloatingBar()
        screenshots = []

        tray = MockTrayService(on_capture=lambda: screenshots.append(engine.capture_screenshot()))

        # Start recording
        engine.start_recording()
        bar.show_bar()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)

        # Trigger tray quick screenshot
        tray.on_capture()
        self.assertEqual(len(screenshots), 1)
        self.assertImageValid(screenshots[0], expected_format="PNG")
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)

        # Stop recording
        time.sleep(0.05)
        path = engine.stop_recording()
        bar.hide_bar()
        self.assertVideoValid(path, expected_format="MP4")


if __name__ == "__main__":
    unittest.main()
