"""
tests/tier4_scenarios/test_scenario_tray_minimize_hotkey_burst.py
Tier 4 Scenario 4: Tray Minimize & Background Hotkey Burst Workflow.
Simulates minimizing app to tray, taking rapid hotkey screenshots and recording, and restoring from tray.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockAppWindow,
    CaptureConfig,
)


class TestScenarioTrayMinimizeHotkeyBurst(BaseE2ETestCase):
    """Scenario 4: Background workstation capture session via tray and hotkeys."""

    def test_tray_minimize_hotkey_burst_and_restore(self):
        """Verify hotkey captures in background while minimized, followed by clean window restore."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        screenshots = []

        app.hotkeys.register_hotkey("<Ctrl><Alt>a", lambda: screenshots.append(app.engine.capture_screenshot()))
        app.hotkeys.register_hotkey("<Ctrl><Alt>r", lambda: app.engine.start_recording() if app.engine.get_status().value == "idle" else app.engine.stop_recording())
        app.hotkeys.start()

        # 1. Minimize main window to tray
        app.hide()
        self.assertFalse(app.get_visible())

        # 2. Fire 3 hotkey screenshot bursts
        for _ in range(3):
            app.hotkeys.trigger_hotkey("<Ctrl><Alt>a")
        self.assertEqual(len(screenshots), 3)

        # 3. Start recording via hotkey
        app.hotkeys.trigger_hotkey("<Ctrl><Alt>r")
        app.floating_bar.show_bar()
        self.assertTrue(app.floating_bar.get_visible())
        time.sleep(0.05)

        # 4. Stop recording via hotkey
        app.hotkeys.trigger_hotkey("<Ctrl><Alt>r")
        app.floating_bar.hide_bar()
        self.assertFalse(app.floating_bar.get_visible())

        # 5. Restore application window from tray
        app.show_all()
        self.assertTrue(app.get_visible())

        # 6. Verify MediaManager lists all 4 captures (3 images + 1 video)
        items = app.media_manager.scan_captures(self.temp_dir)
        self.assertEqual(len(items), 4)

        app.hotkeys.stop()
        app.destroy()


if __name__ == "__main__":
    unittest.main()
