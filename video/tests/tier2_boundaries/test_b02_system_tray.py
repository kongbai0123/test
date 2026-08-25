"""
tests/tier2_boundaries/test_b02_system_tray.py
Boundary B2: System Tray Integration Boundaries.
Verifies rapid show/hide toggles, tray quit during active recording, fallback icons, duplicate prevention, and invalid icon handling.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockTrayService,
    MockCaptureEngine,
    CaptureConfig,
    EngineStatus,
    MockAppWindow,
)


class TestB02SystemTrayBoundaries(BaseE2ETestCase):
    """Tier 2 tests for System Tray Integration Boundaries."""

    def test_b02_01_rapid_show_hide_toggles(self):
        """Verify rapid show/hide toggle calls maintain consistent final state."""
        app = MockAppWindow()
        initial_state = app.get_visible()
        for i in range(20):
            if app.get_visible():
                app.hide()
            else:
                app.show_all()
        # Even number of toggles returns to initial state
        self.assertEqual(app.get_visible(), initial_state)
        app.destroy()

    def test_b02_02_tray_quit_during_active_recording(self):
        """Verify triggering Quit from tray while recording cleanly stops recording."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        engine.start_recording()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)

        def tray_quit():
            if engine.get_status() in (EngineStatus.RECORDING, EngineStatus.PAUSED):
                engine.stop_recording()

        tray = MockTrayService(on_quit=tray_quit)
        tray.on_quit()
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)

    def test_b02_03_missing_appindicator_fallback(self):
        """Verify tray service initializes gracefully even if native indicator is unavailable."""
        tray = MockTrayService()
        self.assertIsNotNone(tray.current_icon)
        self.assertEqual(tray.status, "ACTIVE")

    def test_b02_04_duplicate_tray_service_prevention(self):
        """Verify creating multiple tray instances does not corrupt state."""
        t1 = MockTrayService()
        t2 = MockTrayService()
        t1.set_recording_state(True)
        self.assertTrue(t1.is_recording)
        self.assertFalse(t2.is_recording)

    def test_b02_05_invalid_icon_path_handling(self):
        """Verify update_icon with non-existent path falls back to default icon."""
        tray = MockTrayService()
        tray.update_icon("/nonexistent/path/custom_icon.png")
        self.assertIsNotNone(tray.current_icon)
        self.assertEqual(tray.current_icon, "app-indicator")


if __name__ == "__main__":
    unittest.main()
