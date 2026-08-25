"""
tests/tier3_combinations/test_audio_source_switching.py
Tier 3: Combination of F9 (Audio Recording) + F10 (Video Recording).
Verifies switching audio sources across consecutive video recording sessions.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
)


class TestAudioSourceSwitching(BaseE2ETestCase):
    """Test switching audio sources across consecutive recording takes."""

    def test_audio_source_switching_across_takes(self):
        """Verify recording with pulse, alsa, and disabled audio successively produces valid videos."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))

        # Take 1: PulseAudio
        cfg1 = CaptureConfig(output_dir=self.temp_dir, audio_enabled=True, audio_source="pulse")
        engine.start_recording(cfg1)
        time.sleep(0.05)
        path1 = engine.stop_recording()
        self.assertVideoValid(path1, expected_format="MP4")

        # Take 2: ALSA
        cfg2 = CaptureConfig(output_dir=self.temp_dir, audio_enabled=True, audio_source="alsa")
        engine.start_recording(cfg2)
        time.sleep(0.05)
        path2 = engine.stop_recording()
        self.assertVideoValid(path2, expected_format="MP4")

        # Take 3: Audio Disabled
        cfg3 = CaptureConfig(output_dir=self.temp_dir, audio_enabled=False)
        engine.start_recording(cfg3)
        time.sleep(0.05)
        path3 = engine.stop_recording()
        self.assertVideoValid(path3, expected_format="MP4", check_audio=False)


if __name__ == "__main__":
    unittest.main()
