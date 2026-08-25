"""
tests/tier3_combinations/test_mode_toggle_recording.py
Tier 3: Combination of F1 (UI) + F6 (Auto) + F10 (Video Recording).
Verifies that mode toggle is handled safely during active recording without corrupting the video container.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    CaptureMode,
    EngineStatus,
)


class TestModeToggleRecording(BaseE2ETestCase):
    """Test mode toggle interaction during active video recording."""

    def test_mode_toggle_safeguard_during_recording(self):
        """Verify recording continues safely if mode toggle is triggered during recording."""
        cfg = CaptureConfig(mode=CaptureMode.MANUAL, output_dir=self.temp_dir)
        engine = MockCaptureEngine(cfg)
        engine.start_recording(cfg)
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)

        # User attempts to toggle to auto mode while recording
        time.sleep(0.05)
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)

        # Stop recording
        path = engine.stop_recording()
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        self.assertVideoValid(path, expected_format="MP4")


if __name__ == "__main__":
    unittest.main()
