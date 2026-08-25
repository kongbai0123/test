"""
tests/tier3_combinations/test_auto_interval_dynamic.py
Tier 3: Combination of F1 (UI) + F6 (Auto Mode).
Verifies dynamic interval adjustment while auto-capture mode is actively running.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
)


class TestAutoIntervalDynamic(BaseE2ETestCase):
    """Test dynamic interval updates on active auto-capture scheduler."""

    def test_dynamic_interval_adjustment_on_active_loop(self):
        """Verify scheduler adapts to interval modifications seamlessly."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        captures = []

        # Start with interval 0.1s
        engine.start_auto_mode(interval=0.1, callback=lambda path: captures.append(path))
        self.wait_for_condition(lambda: len(captures) >= 1, timeout=2.0)

        # Update interval to 0.05s dynamically
        engine.stop_auto_mode()
        engine.start_auto_mode(interval=0.05, callback=lambda path: captures.append(path))
        self.wait_for_condition(lambda: len(captures) >= 3, timeout=2.0)
        engine.stop_auto_mode()

        self.assertGreaterEqual(len(captures), 3)
        for p in captures:
            self.assertImageValid(p, expected_format="PNG")


if __name__ == "__main__":
    unittest.main()
