"""
tests/tier3_combinations/test_hotkey_during_media_search.py
Tier 3: Combination of F3 (Global Hotkeys) + F10 (Video Recording) + F12 (Media Manager).
Verifies that global hotkeys trigger reliably while searching media and the media list updates.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    MockHotkeyManager,
    MockMediaManager,
    CaptureConfig,
    EngineStatus,
)


class TestHotkeyDuringMediaSearch(BaseE2ETestCase):
    """Test hotkey recording dispatch and immediate media manager refresh."""

    def test_hotkey_trigger_updates_media_manager_index(self):
        """Verify global hotkey recording starts/stops and refreshes media gallery."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        hotkeys = MockHotkeyManager()
        mgr = MockMediaManager()

        def toggle_rec():
            if engine.get_status() == EngineStatus.RECORDING:
                engine.stop_recording()
            else:
                engine.start_recording()

        hotkeys.register_hotkey("<Ctrl><Alt>r", toggle_rec)

        # Initial media scan
        items_initial = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items_initial), 0)

        # Start recording via hotkey
        hotkeys.trigger_hotkey("<Ctrl><Alt>r")
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        time.sleep(0.05)

        # Stop recording via hotkey
        hotkeys.trigger_hotkey("<Ctrl><Alt>r")
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        hotkeys.stop()

        # Media list should now contain 1 video
        items_after = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items_after), 1)
        self.assertEqual(items_after[0].media_type, "video")


if __name__ == "__main__":
    unittest.main()
