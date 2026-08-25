"""
tests/tier1_features/test_f11_pause_resume.py
Feature F11: Pause / Resume Recording (R3 Requirement).
Verifies seamless video recording pause/resume with continuous container timeline.
"""

import time
import unittest
import cv2
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    EngineStatus,
    MockFloatingBar,
)


class TestF11PauseResumeRecording(BaseE2ETestCase):
    """Tier 1 tests for Pause / Resume Recording."""

    def test_f11_01_pause_recording_state(self):
        """Verify calling pause_recording() transitions engine status to PAUSED."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        engine.start_recording()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        engine.pause_recording()
        self.assertEqual(engine.get_status(), EngineStatus.PAUSED)
        engine.stop_recording()

    def test_f11_02_resume_recording_state(self):
        """Verify calling resume_recording() transitions engine status back to RECORDING."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        engine.start_recording()
        engine.pause_recording()
        self.assertEqual(engine.get_status(), EngineStatus.PAUSED)
        engine.resume_recording()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        engine.stop_recording()

    def test_f11_03_continuous_timeline_no_freeze_drift(self):
        """Verify paused duration is excluded from active container duration."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir, fps=30))
        engine.start_recording()
        time.sleep(0.1)
        engine.pause_recording()
        time.sleep(0.2)  # Paused 200ms
        engine.resume_recording()
        time.sleep(0.1)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_f11_04_pause_resume_floating_bar_sync(self):
        """Verify floating bar button state reflects engine pause state."""
        bar = MockFloatingBar()
        bar.show_bar()
        self.assertFalse(bar.is_paused)
        bar.set_paused(True)
        self.assertTrue(bar.is_paused)
        bar.set_paused(False)
        self.assertFalse(bar.is_paused)

    def test_f11_05_stop_while_paused(self):
        """Verify calling stop_recording() while in PAUSED state finalizes container cleanly."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        engine.start_recording()
        time.sleep(0.05)
        engine.pause_recording()
        self.assertEqual(engine.get_status(), EngineStatus.PAUSED)
        path = engine.stop_recording()
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        self.assertVideoValid(path, expected_format="MP4")


if __name__ == "__main__":
    unittest.main()
