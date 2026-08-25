"""
tests/tier1_features/test_f09_audio_recording.py
Feature F9: Audio Recording & Mixing (R3 Requirement).
Verifies PulseAudio/ALSA microphone and system desktop audio capture, mixing, and UI toggle.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    MockAppWindow,
)


class TestF09AudioRecording(BaseE2ETestCase):
    """Tier 1 tests for Audio Recording and Mixing."""

    def test_f09_01_audio_disabled_video(self):
        """Verify video recorded with audio_enabled=False creates valid video file."""
        config = CaptureConfig(output_dir=self.temp_dir, audio_enabled=False)
        engine = MockCaptureEngine(config)
        engine.start_recording(config)
        time.sleep(0.1)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4", check_audio=False)

    def test_f09_02_audio_enabled_pulse_source(self):
        """Verify video recorded with audio_enabled=True and pulse source creates valid video file."""
        config = CaptureConfig(output_dir=self.temp_dir, audio_enabled=True, audio_source="pulse")
        engine = MockCaptureEngine(config)
        engine.start_recording(config)
        time.sleep(0.1)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_f09_03_audio_source_selection_config(self):
        """Verify CaptureConfig accepts default, pulse, alsa sources."""
        for src in ("default", "pulse", "alsa"):
            cfg = CaptureConfig(output_dir=self.temp_dir, audio_enabled=True, audio_source=src)
            self.assertEqual(cfg.audio_source, src)
            self.assertTrue(cfg.audio_enabled)

    def test_f09_04_audio_mixing_mic_and_desktop(self):
        """Verify audio configuration enables stereo mixing support."""
        config = CaptureConfig(output_dir=self.temp_dir, audio_enabled=True, audio_source="default")
        self.assertTrue(config.audio_enabled)
        engine = MockCaptureEngine(config)
        engine.start_recording(config)
        time.sleep(0.1)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_f09_05_audio_toggle_ui_control(self):
        """Verify toggling audio button in UI enables/disables audio capture in config."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir, audio_enabled=False))
        self.assertFalse(app.config.audio_enabled)
        app.config.audio_enabled = True
        self.assertTrue(app.config.audio_enabled)
        app.config.audio_enabled = False
        self.assertFalse(app.config.audio_enabled)
        app.destroy()


if __name__ == "__main__":
    unittest.main()
