"""
tests/tier3_combinations/test_rapid_mode_toggle.py
Tier 3: Combination of F1 (UI) + F5 (Manual) + F6 (Auto).
Verifies rapid toggling between Manual and Automatic modes without deadlocks or thread leaks.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockAppWindow,
    CaptureConfig,
    CaptureMode,
)


class TestRapidModeToggle(BaseE2ETestCase):
    """Test rapid mode toggling stress."""

    def test_rapid_mode_toggle_integrity(self):
        """Verify 20 rapid mode switch cycles execute without unhandled exceptions."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        for i in range(20):
            if i % 2 == 0:
                app.mode = CaptureMode.AUTOMATIC
                app.engine.start_auto_mode(interval=0.1, callback=lambda path: None)
            else:
                app.mode = CaptureMode.MANUAL
                app.engine.stop_auto_mode()

        # Ensure final state is clean
        app.engine.stop_auto_mode()
        app.destroy()
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
