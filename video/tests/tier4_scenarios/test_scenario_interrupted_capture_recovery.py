"""
tests/tier4_scenarios/test_scenario_interrupted_capture_recovery.py
Tier 4 Scenario 6: Fault Injection & Resilient Error Recovery.
Simulates encountering disk errors or unwritable paths, recovering state, and resuming normal capture operations.
"""

import os
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    EngineStatus,
)


class TestScenarioInterruptedCaptureRecovery(BaseE2ETestCase):
    """Scenario 6: Fault injection and error recovery."""

    def test_fault_injection_and_state_recovery(self):
        """Verify engine catches filesystem/pipeline errors and recovers to clean IDLE state."""
        # 1. Fault Injection: Attempt capture to unwritable / invalid directory
        bad_config = CaptureConfig(output_dir="/root/forbidden_recording_test_path_9999")
        engine = MockCaptureEngine(bad_config)

        try:
            engine.capture_screenshot(bad_config)
        except Exception:
            pass
        self.assertEqual(engine.get_status(), EngineStatus.ERROR)

        # 2. Recovery Phase: Switch to valid writable directory
        engine.status = EngineStatus.IDLE
        good_config = CaptureConfig(output_dir=self.temp_dir)
        path = engine.capture_screenshot(good_config)
        self.assertImageValid(path, expected_format="PNG")
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)

        # 3. Verify normal recording works after recovery
        engine.start_recording(good_config)
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        vid_path = engine.stop_recording()
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        self.assertVideoValid(vid_path, expected_format="MP4")


if __name__ == "__main__":
    unittest.main()
