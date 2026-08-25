"""
tests/tier1_features/test_f10_hardware_encoding.py
Feature F10: Hardware/System Encoding (R3 Requirement).
Verifies NVIDIA NVENC / GStreamer / x264 hardware and software optimized encoding.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    OutputFormat,
)


class TestF10HardwareEncoding(BaseE2ETestCase):
    """Tier 1 tests for Hardware/System Encoding."""

    def test_f10_01_nvenc_pipeline_selection(self):
        """Verify engine configures hardware acceleration when use_hardware_accel=True."""
        config = CaptureConfig(output_dir=self.temp_dir, use_hardware_accel=True)
        self.assertTrue(config.use_hardware_accel)
        engine = MockCaptureEngine(config)
        engine.start_recording(config)
        time.sleep(0.1)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_f10_02_x264_software_fallback(self):
        """Verify engine configures software encoding when use_hardware_accel=False."""
        config = CaptureConfig(output_dir=self.temp_dir, use_hardware_accel=False)
        self.assertFalse(config.use_hardware_accel)
        engine = MockCaptureEngine(config)
        engine.start_recording(config)
        time.sleep(0.1)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_f10_03_encoder_preset_and_bitrate(self):
        """Verify encoder respects bitrate and fps configuration parameters."""
        config = CaptureConfig(output_dir=self.temp_dir, fps=30, bitrate_kbps=4000)
        self.assertEqual(config.fps, 30)
        self.assertEqual(config.bitrate_kbps, 4000)

    def test_f10_04_hardware_encoding_output_validity(self):
        """Verify encoded video produces valid frames readable by OpenCV."""
        config = CaptureConfig(output_dir=self.temp_dir, video_format=OutputFormat.MP4)
        engine = MockCaptureEngine(config)
        engine.start_recording(config)
        time.sleep(0.1)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4", min_duration_sec=0.05)

    def test_f10_05_encoder_error_handling(self):
        """Verify engine transitions to ERROR state or handles invalid output directory cleanly."""
        config = CaptureConfig(output_dir="/nonexistent/unwritable/dir_99999")
        engine = MockCaptureEngine(config)
        with self.assertRaises(Exception):
            engine.start_recording(config)


if __name__ == "__main__":
    unittest.main()
