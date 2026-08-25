"""
tests/tier3_combinations/test_hotkey_during_auto.py
Tier 3: Combination of F3 (Global Hotkeys) + F5 (Manual Capture) + F6 (Automatic Mode).
Verifies triggering manual hotkey screenshot while auto-capture loop is actively ticking.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    MockHotkeyManager,
    CaptureConfig,
    CaptureMode,
)


class TestHotkeyDuringAuto(BaseE2ETestCase):
    """Test hotkey screenshot trigger during active auto-capture mode."""

    def test_hotkey_screenshot_concurrent_with_auto_mode(self):
        """Verify manual screenshot via hotkey executes without disrupting scheduled auto-capture loop."""
        config = CaptureConfig(mode=CaptureMode.AUTOMATIC, output_dir=self.temp_dir)
        engine = MockCaptureEngine(config)
        auto_captures = []
        manual_captures = []

        hotkeys = MockHotkeyManager()
        hotkeys.register_hotkey("<Ctrl><Alt>a", lambda: manual_captures.append(engine.capture_screenshot()))

        engine.start_auto_mode(interval=0.1, callback=lambda path: auto_captures.append(path))

        # Wait for 1st auto capture, then trigger manual hotkey
        self.wait_for_condition(lambda: len(auto_captures) >= 1, timeout=2.0)
        hotkeys.trigger_hotkey("<Ctrl><Alt>a")

        # Wait for next auto capture
        self.wait_for_condition(lambda: len(auto_captures) >= 2, timeout=2.0)
        engine.stop_auto_mode()
        hotkeys.stop()

        self.assertEqual(len(manual_captures), 1)
        self.assertGreaterEqual(len(auto_captures), 2)
        self.assertImageValid(manual_captures[0], expected_format="PNG")
        for p in auto_captures:
            self.assertImageValid(p, expected_format="PNG")


if __name__ == "__main__":
    unittest.main()
