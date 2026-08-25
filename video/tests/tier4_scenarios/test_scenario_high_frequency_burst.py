"""
tests/tier4_scenarios/test_scenario_high_frequency_burst.py
Tier 4 Scenario 7: High-Frequency Screenshot Burst Workload.
Simulates dispatching 25 manual screenshot calls in rapid succession to test serialization and unique timestamping.
"""

import os
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    MockMediaManager,
)


class TestScenarioHighFrequencyBurst(BaseE2ETestCase):
    """Scenario 7: High-frequency screenshot burst stress test."""

    def test_high_frequency_screenshot_burst_workload(self):
        """Verify 25 rapid-fire screenshots produce 25 unique, valid files without collisions."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        mgr = MockMediaManager()
        created_paths = []

        for _ in range(25):
            p = engine.capture_screenshot()
            created_paths.append(p)

        self.assertEqual(len(created_paths), 25)
        # Verify unique files
        unique_paths = set(created_paths)
        self.assertEqual(len(unique_paths), 25)

        # Verify all files exist and are valid PNGs
        for p in unique_paths:
            self.assertTrue(os.path.exists(p))
            self.assertImageValid(p, expected_format="PNG")

        # Verify MediaManager indexes all 25 items
        items = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items), 25)


if __name__ == "__main__":
    unittest.main()
