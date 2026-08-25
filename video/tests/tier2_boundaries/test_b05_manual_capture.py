"""
tests/tier2_boundaries/test_b05_manual_capture.py
Boundary B5: Manual Capture Mode Boundaries.
Verifies screenshot during active recording, rapid screenshot bursts, unwritable directory handling, stop when idle, and zero-duration recording.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    EngineStatus,
)


class TestB05ManualCaptureBoundaries(BaseE2ETestCase):
    """Tier 2 tests for Manual Capture Mode Boundaries."""

    def test_b05_01_screenshot_during_active_recording(self):
        """Verify taking a screenshot during active video recording works concurrently."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        engine.start_recording()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)

        # Concurrent screenshot
        img_path = engine.capture_screenshot()
        self.assertImageValid(img_path, expected_format="PNG")
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)

        time.sleep(0.05)
        vid_path = engine.stop_recording()
        self.assertVideoValid(vid_path, expected_format="MP4")

    def test_b05_02_rapid_double_click_screenshot(self):
        """Verify rapid consecutive screenshot calls produce distinct files."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        p1 = engine.capture_screenshot()
        p2 = engine.capture_screenshot()
        self.assertNotEqual(p1, p2)
        self.assertImageValid(p1, expected_format="PNG")
        self.assertImageValid(p2, expected_format="PNG")

    def test_b05_03_unwritable_output_directory(self):
        """Verify attempting capture to an invalid/unwritable directory raises an error."""
        engine = MockCaptureEngine(CaptureConfig(output_dir="/nonexistent_root_dir_test_error"))
        with self.assertRaises(Exception):
            engine.capture_screenshot()

    def test_b05_04_stop_recording_when_idle(self):
        """Verify calling stop_recording() when IDLE raises RuntimeError cleanly."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        with self.assertRaises(RuntimeError):
            engine.stop_recording()

    def test_b05_05_zero_duration_recording_handling(self):
        """Verify recording stopped immediately after start produces valid minimal file."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        engine.start_recording()
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4", min_duration_sec=0.05)


if __name__ == "__main__":
    unittest.main()
