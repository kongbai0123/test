"""
tests/tier3_combinations/test_hotkey_during_pause.py
Tier 3: Combination of F3 (Global Hotkeys) + F4 (Floating Bar) + F11 (Pause/Resume).
Verifies triggering manual screenshot hotkey while video recording is in PAUSED state.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    MockHotkeyManager,
    CaptureConfig,
    EngineStatus,
    MockFloatingBar,
)


class TestHotkeyDuringPause(BaseE2ETestCase):
    """Test hotkey screenshot trigger during paused video recording."""

    def test_hotkey_screenshot_while_recording_paused(self):
        """Verify taking a screenshot during pause leaves recording in PAUSED state and resumes cleanly."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        bar = MockFloatingBar()
        hotkeys = MockHotkeyManager()
        shots = []

        hotkeys.register_hotkey("<Ctrl><Alt>a", lambda: shots.append(engine.capture_screenshot()))

        # Start recording and pause
        engine.start_recording()
        bar.show_bar()
        time.sleep(0.05)
        engine.pause_recording()
        bar.set_paused(True)
        self.assertEqual(engine.get_status(), EngineStatus.PAUSED)
        self.assertTrue(bar.is_paused)

        # Trigger hotkey screenshot during pause
        hotkeys.trigger_hotkey("<Ctrl><Alt>a")
        self.assertEqual(len(shots), 1)
        self.assertImageValid(shots[0], expected_format="PNG")
        self.assertEqual(engine.get_status(), EngineStatus.PAUSED)

        # Resume recording and stop
        engine.resume_recording()
        bar.set_paused(False)
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        time.sleep(0.05)
        vid_path = engine.stop_recording()
        bar.hide_bar()
        hotkeys.stop()

        self.assertVideoValid(vid_path, expected_format="MP4")


if __name__ == "__main__":
    unittest.main()
