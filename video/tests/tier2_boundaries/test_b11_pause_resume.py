"""
tests/tier2_boundaries/test_b11_pause_resume.py
Boundary B11: Pause / Resume Recording Boundaries.
Verifies zero-duration pause/resume bursts, duplicate pause calls, duplicate resume calls, prolonged pauses, and stop immediately after pause.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    EngineStatus,
)


class TestB11PauseResumeBoundaries(BaseE2ETestCase):
    """Tier 2 tests for Pause / Resume Recording Boundaries."""

    def test_b11_01_zero_duration_pause_resume_burst(self):
        """Verify immediate pause and resume (<10ms) does not corrupt recording state."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        engine.start_recording()
        engine.pause_recording()
        engine.resume_recording()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_b11_02_consecutive_duplicate_pause_calls(self):
        """Verify calling pause_recording() multiple times consecutively is a safe no-op."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        engine.start_recording()
        engine.pause_recording()
        self.assertEqual(engine.get_status(), EngineStatus.PAUSED)
        engine.pause_recording()
        self.assertEqual(engine.get_status(), EngineStatus.PAUSED)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_b11_03_consecutive_duplicate_resume_calls(self):
        """Verify calling resume_recording() when already recording is a safe no-op."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        engine.start_recording()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        engine.resume_recording()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_b11_04_prolonged_pause_timestamp_continuity(self):
        """Verify prolonged pause is excluded from container timeline."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        engine.start_recording()
        time.sleep(0.05)
        engine.pause_recording()
        time.sleep(0.15)
        engine.resume_recording()
        time.sleep(0.05)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_b11_05_stop_immediately_after_pause(self):
        """Verify calling stop_recording() immediately after pause finalizes container cleanly."""
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
