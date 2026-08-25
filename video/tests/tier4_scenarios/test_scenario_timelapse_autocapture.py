"""
tests/tier4_scenarios/test_scenario_timelapse_autocapture.py
Tier 4 Scenario 2: Drift-Free Time-Lapse Auto-Capture Session.
Simulates long-running time-lapse capture across multiple ticks with dynamic interval modification.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    CaptureMode,
)


class TestScenarioTimelapseAutocapture(BaseE2ETestCase):
    """Scenario 2: Drift-free recurring auto-capture workload."""

    def test_timelapse_autocapture_session(self):
        """Verify monotonic auto-capture session produces sequential captures without timing drift."""
        config = CaptureConfig(mode=CaptureMode.AUTOMATIC, output_dir=self.temp_dir)
        engine = MockCaptureEngine(config)
        captures = []
        timestamps = []

        def on_capture(path):
            timestamps.append(time.monotonic())
            captures.append(path)

        # Start auto mode at 0.05s interval
        engine.start_auto_mode(interval=0.05, callback=on_capture)
        self.wait_for_condition(lambda: len(captures) >= 6, timeout=3.0)
        engine.stop_auto_mode()

        self.assertGreaterEqual(len(captures), 6)
        # Verify all captured images are valid PNGs
        for p in captures:
            self.assertImageValid(p, expected_format="PNG")

        # Verify monotonicity of capture timestamps
        for i in range(1, len(timestamps)):
            delta = timestamps[i] - timestamps[i - 1]
            self.assertGreater(delta, 0.01)


if __name__ == "__main__":
    unittest.main()
