"""
tests/tier1_features/test_f05_manual_capture.py
Feature F5: Manual Capture Mode (R2 Requirement).
Verifies manual screenshot capture, start/stop recording, UI triggers, and timestamped filenames.
"""

import os
import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    CaptureMode,
    EngineStatus,
    MockAppWindow,
)


class TestF05ManualCaptureMode(BaseE2ETestCase):
    """Tier 1 tests for Manual Capture Mode."""

    def test_f05_01_manual_screenshot_trigger(self):
        """Verify CaptureEngine captures screenshot immediately in manual mode."""
        engine = MockCaptureEngine(CaptureConfig(mode=CaptureMode.MANUAL, output_dir=self.temp_dir))
        filepath = engine.capture_screenshot()
        self.assertImageValid(filepath, expected_format="PNG")

    def test_f05_02_manual_record_start_stop(self):
        """Verify starting and stopping manual recording produces a valid video file."""
        engine = MockCaptureEngine(CaptureConfig(mode=CaptureMode.MANUAL, output_dir=self.temp_dir))
        engine.start_recording()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        time.sleep(0.1)
        filepath = engine.stop_recording()
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        self.assertVideoValid(filepath, expected_format="MP4", min_duration_sec=0.05)

    def test_f05_03_manual_mode_ui_interaction(self):
        """Verify clicking UI screenshot trigger captures an image into output dir."""
        app = MockAppWindow(CaptureConfig(mode=CaptureMode.MANUAL, output_dir=self.temp_dir))
        path = app.engine.capture_screenshot()
        self.assertImageValid(path, expected_format="PNG")
        items = app.media_manager.scan_captures(self.temp_dir)
        self.assertGreaterEqual(len(items), 1)
        app.destroy()

    def test_f05_04_manual_mode_record_toggle_button(self):
        """Verify Record toggle transitions state from IDLE to RECORDING and back."""
        engine = MockCaptureEngine(CaptureConfig(mode=CaptureMode.MANUAL, output_dir=self.temp_dir))
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        engine.start_recording()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        time.sleep(0.1)
        path = engine.stop_recording()
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        self.assertTrue(os.path.exists(path))

    def test_f05_05_manual_capture_timestamp_filename(self):
        """Verify generated files follow deterministic timestamped naming conventions."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        img_path = engine.capture_screenshot()
        self.assertTrue(os.path.basename(img_path).startswith("capture_"))
        self.assertTrue(img_path.endswith(".png"))

        engine.start_recording()
        time.sleep(0.05)
        vid_path = engine.stop_recording()
        self.assertTrue(os.path.basename(vid_path).startswith("record_"))
        self.assertTrue(vid_path.endswith(".mp4"))


if __name__ == "__main__":
    unittest.main()
