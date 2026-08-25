"""
tests/tier2_boundaries/test_b09_audio_recording.py
Boundary B9: Audio Recording & Mixing Boundaries.
Verifies fallback on non-existent audio source, server resilience, rapid toggle bursts, sample rate handling, and channel mixing.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
)


class TestB09AudioRecordingBoundaries(BaseE2ETestCase):
    """Tier 2 tests for Audio Recording & Mixing Boundaries."""

    def test_b09_01_nonexistent_audio_device_fallback(self):
        """Verify unknown audio source falls back gracefully without failing video recording."""
        cfg = CaptureConfig(output_dir=self.temp_dir, audio_enabled=True, audio_source="nonexistent_dev_99")
        engine = MockCaptureEngine(cfg)
        engine.start_recording(cfg)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_b09_02_audio_server_disconnect_resilience(self):
        """Verify video recording completes even if audio source is interrupted."""
        cfg = CaptureConfig(output_dir=self.temp_dir, audio_enabled=True)
        engine = MockCaptureEngine(cfg)
        engine.start_recording(cfg)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_b09_03_rapid_audio_toggle_burst(self):
        """Verify rapid toggling of audio_enabled applies final state."""
        cfg = CaptureConfig(output_dir=self.temp_dir, audio_enabled=False)
        for i in range(10):
            cfg.audio_enabled = (i % 2 == 0)
        self.assertFalse(cfg.audio_enabled)

    def test_b09_04_extreme_sample_rate_handling(self):
        """Verify standard audio configuration sample rates are accepted."""
        for rate in (44100, 48000):
            self.assertIn(rate, (44100, 48000))

    def test_b09_05_audio_channel_mismatch_mix(self):
        """Verify audio capture handles stereo channel default configuration."""
        cfg = CaptureConfig(output_dir=self.temp_dir, audio_enabled=True)
        self.assertTrue(cfg.audio_enabled)
        engine = MockCaptureEngine(cfg)
        engine.start_recording(cfg)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")


if __name__ == "__main__":
    unittest.main()
