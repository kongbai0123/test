"""
tests/tier3_combinations/test_tray_minimize_recording.py
Tier 3: Combination of F2 (System Tray) + F4 (Floating Bar) + F10 (Video Recording).
Verifies minimizing app to tray while recording keeps floating bar active and stop works cleanly.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockAppWindow,
    CaptureConfig,
    EngineStatus,
)


class TestTrayMinimizeRecording(BaseE2ETestCase):
    """Test minimizing main window to tray while video recording and floating bar are active."""

    def test_minimize_to_tray_with_active_floating_bar(self):
        """Verify main window minimizes to tray while floating bar remains visible to control recording."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        app.engine.start_recording()
        app.floating_bar.show_bar()
        self.assertEqual(app.engine.get_status(), EngineStatus.RECORDING)
        self.assertTrue(app.floating_bar.get_visible())

        # Minimize main app window to tray
        app.hide()
        self.assertFalse(app.get_visible())
        self.assertTrue(app.floating_bar.get_visible())

        # Stop recording via floating bar action
        time.sleep(0.05)
        path = app.engine.stop_recording()
        app.floating_bar.hide_bar()
        self.assertFalse(app.floating_bar.get_visible())
        self.assertEqual(app.engine.get_status(), EngineStatus.IDLE)
        self.assertVideoValid(path, expected_format="MP4")

        # Restore main window from tray
        app.show_all()
        self.assertTrue(app.get_visible())
        app.destroy()


if __name__ == "__main__":
    unittest.main()
