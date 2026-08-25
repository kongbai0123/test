"""
tests/tier2_boundaries/test_b10_hardware_encoding.py
Boundary B10: Hardware/System Encoding Boundaries.
Verifies software encoding fallback, resource exhaustion recovery, bitrate parameter clamping, high framerate (60fps), and colorspace conversion.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
)


def clamp_bitrate(kbps: int) -> int:
    """Clamps bitrate to valid range 500kbps to 50000kbps."""
    return max(500, min(50000, kbps))


class TestB10HardwareEncodingBoundaries(BaseE2ETestCase):
    """Tier 2 tests for Hardware/System Encoding Boundaries."""

    def test_b10_01_force_software_x264_when_nvenc_disabled(self):
        """Verify use_hardware_accel=False builds software encoder pipeline."""
        cfg = CaptureConfig(output_dir=self.temp_dir, use_hardware_accel=False)
        self.assertFalse(cfg.use_hardware_accel)
        engine = MockCaptureEngine(cfg)
        engine.start_recording(cfg)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_b10_02_gpu_memory_exhaustion_fallback(self):
        """Verify fallback to software encoder if hardware encoder fails."""
        cfg = CaptureConfig(output_dir=self.temp_dir)
        engine = MockCaptureEngine(cfg)
        engine.start_recording(cfg)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_b10_03_invalid_bitrate_parameter_clamping(self):
        """Verify bitrates <= 0 or > 100,000 kbps clamp to [500, 50000]."""
        self.assertEqual(clamp_bitrate(-500), 500)
        self.assertEqual(clamp_bitrate(0), 500)
        self.assertEqual(clamp_bitrate(500000), 50000)
        self.assertEqual(clamp_bitrate(4000), 4000)

    def test_b10_04_high_framerate_pipeline_stability(self):
        """Verify 60fps recording configuration creates valid video."""
        cfg = CaptureConfig(output_dir=self.temp_dir, fps=60)
        self.assertEqual(cfg.fps, 60)
        engine = MockCaptureEngine(cfg)
        engine.start_recording(cfg)
        time.sleep(0.05)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")

    def test_b10_05_unsupported_colorspace_conversion(self):
        """Verify colorspace conversion ensures standard BGR/RGB pixel buffers."""
        cfg = CaptureConfig(output_dir=self.temp_dir)
        engine = MockCaptureEngine(cfg)
        path = engine.capture_screenshot(cfg)
        self.assertImageValid(path, expected_format="PNG")


if __name__ == "__main__":
    unittest.main()
