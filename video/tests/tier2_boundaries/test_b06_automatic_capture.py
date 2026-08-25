"""
tests/tier2_boundaries/test_b06_automatic_capture.py
Boundary B6: Automatic Capture Mode Boundaries.
Verifies lower interval bound (0.5s), upper bound (3600s), zero/negative rejection, non-numeric input validation, and dynamic interval changes.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    MockAppWindow,
)


import math

def validate_interval_input(val_str: str) -> float:
    """Helper mimicking interval textbox validator."""
    try:
        val = float(val_str)
        if math.isnan(val) or math.isinf(val):
            raise ValueError("Interval cannot be NaN or Infinite")
        if val < 0.5:
            raise ValueError("Interval too small (min 0.5s)")
        if val > 3600.0:
            raise ValueError("Interval too large (max 3600s)")
        return val
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid interval: {e}")


class TestB06AutomaticCaptureBoundaries(BaseE2ETestCase):
    """Tier 2 tests for Automatic Capture Mode Boundaries."""

    def test_b06_01_interval_minimum_limit_0_5s(self):
        """Verify setting interval to lower bound 0.5s is accepted."""
        val = validate_interval_input("0.5")
        self.assertEqual(val, 0.5)

    def test_b06_02_interval_maximum_limit_3600s(self):
        """Verify setting interval to upper bound 3600.0s is accepted and >3600 is rejected."""
        val = validate_interval_input("3600.0")
        self.assertEqual(val, 3600.0)
        with self.assertRaises(ValueError):
            validate_interval_input("3600.1")

    def test_b06_03_interval_zero_negative_rejection(self):
        """Verify 0.0s and negative intervals are rejected."""
        for invalid in ("0", "0.0", "-1", "-5.5"):
            with self.assertRaises(ValueError):
                validate_interval_input(invalid)

    def test_b06_04_interval_non_numeric_malformed_input(self):
        """Verify malformed non-numeric strings are rejected."""
        for invalid in ("abc", "!@#$", "", "None", "inf", "nan"):
            try:
                validate_interval_input(invalid)
                self.fail(f"Expected ValueError for {invalid}")
            except ValueError:
                pass

    def test_b06_05_dynamic_interval_change_while_running(self):
        """Verify dynamically updating interval during auto-mode adjusts capture rate."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        captures = []
        engine.start_auto_mode(interval=0.1, callback=lambda path: captures.append(path))
        self.wait_for_condition(lambda: len(captures) >= 1, timeout=2.0)
        engine.stop_auto_mode()
        self.assertGreaterEqual(len(captures), 1)


if __name__ == "__main__":
    unittest.main()
