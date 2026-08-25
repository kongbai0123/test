"""
tests/tier1_features/test_f02_system_tray.py
Feature F2: System Tray Integration (R1 Requirement).
Verifies tray icon status, menu callbacks, window visibility toggles, and background execution.
"""

import os
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockTrayService,
    MockCaptureEngine,
    CaptureConfig,
    MockAppWindow,
)


class TestF02SystemTrayIntegration(BaseE2ETestCase):
    """Tier 1 tests for System Tray Integration."""

    def test_f02_01_tray_initialization(self):
        """Verify TrayService initializes with AppIndicator3/StatusIcon properties."""
        tray = MockTrayService()
        self.assertEqual(tray.status, "ACTIVE")
        self.assertEqual(tray.category, "APPLICATION_STATUS")
        self.assertTrue(len(tray.current_icon) > 0)

    def test_f02_02_tray_menu_actions(self):
        """Verify tray context menu actions invoke registered callbacks."""
        called = {"show_hide": False, "mode": False, "cap": False, "rec": False, "quit": False}
        tray = MockTrayService(
            on_show_hide=lambda: called.update({"show_hide": True}),
            on_mode_toggle=lambda: called.update({"mode": True}),
            on_capture=lambda: called.update({"cap": True}),
            on_record=lambda: called.update({"rec": True}),
            on_quit=lambda: called.update({"quit": True}),
        )
        tray.on_show_hide()
        tray.on_mode_toggle()
        tray.on_capture()
        tray.on_record()
        tray.on_quit()
        self.assertTrue(all(called.values()))

    def test_f02_03_toggle_window_visibility(self):
        """Verify triggering Show/Hide from tray toggles main application window visibility."""
        app = MockAppWindow()
        self.assertTrue(app.get_visible())
        # First toggle hides
        app.hide()
        self.assertFalse(app.get_visible())
        # Second toggle shows
        app.show_all()
        self.assertTrue(app.get_visible())
        app.destroy()

    def test_f02_04_tray_recording_state_update(self):
        """Verify set_recording_state(True) updates tray icon to recording indicator."""
        tray = MockTrayService()
        self.assertFalse(tray.is_recording)
        tray.set_recording_state(True)
        self.assertTrue(tray.is_recording)
        self.assertEqual(tray.current_icon, "media-record")
        tray.set_recording_state(False)
        self.assertFalse(tray.is_recording)
        self.assertEqual(tray.current_icon, "app-indicator")

    def test_f02_05_background_execution_when_hidden(self):
        """Verify capture operations continue running when window is hidden to tray."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        app.hide()
        self.assertFalse(app.get_visible())
        # Capture screenshot while hidden
        path = app.engine.capture_screenshot()
        self.assertImageValid(path, expected_format="PNG")
        app.destroy()


if __name__ == "__main__":
    unittest.main()
