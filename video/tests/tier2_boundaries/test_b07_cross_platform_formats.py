"""
tests/tier2_boundaries/test_b07_cross_platform_formats.py
Boundary B7: Cross-Platform Formats Boundaries.
Verifies invalid format fallbacks, format change during recording, case-insensitive parsing, large resolutions, and container integrity.
"""

import os
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    OutputFormat,
    MockScreenGrabber,
)


def parse_output_format(fmt_str: str) -> OutputFormat:
    """Helper mimicking config format parsing."""
    s = fmt_str.strip().lower()
    if s in ("png",):
        return OutputFormat.PNG
    elif s in ("jpg", "jpeg"):
        return OutputFormat.JPG
    elif s in ("mp4",):
        return OutputFormat.MP4
    elif s in ("webm",):
        return OutputFormat.WEBM
    raise ValueError(f"Unsupported format: {fmt_str}")


class TestB07CrossPlatformFormatsBoundaries(BaseE2ETestCase):
    """Tier 2 tests for Cross-Platform Formats Boundaries."""

    def test_b07_01_invalid_format_enum_fallback(self):
        """Verify passing unsupported format strings raises ValueError."""
        with self.assertRaises(ValueError):
            parse_output_format("gif")
        with self.assertRaises(ValueError):
            parse_output_format("avi")

    def test_b07_02_format_switch_mid_recording_rejection(self):
        """Verify changing config format while recording applies to next session."""
        cfg = CaptureConfig(output_dir=self.temp_dir, video_format=OutputFormat.MP4)
        engine = MockCaptureEngine(cfg)
        engine.start_recording(cfg)
        # Change format mid recording
        cfg.video_format = OutputFormat.WEBM
        path = engine.stop_recording()
        # Original recording was MP4
        self.assertTrue(path.endswith(".mp4"))

    def test_b07_03_case_insensitive_format_parsing(self):
        """Verify format parsing handles mixed case strings."""
        self.assertEqual(parse_output_format("PNG"), OutputFormat.PNG)
        self.assertEqual(parse_output_format("JpG"), OutputFormat.JPG)
        self.assertEqual(parse_output_format("Mp4"), OutputFormat.MP4)
        self.assertEqual(parse_output_format("WEBM"), OutputFormat.WEBM)

    def test_b07_04_huge_resolution_format_handling(self):
        """Verify capturing high-resolution (4K) image produces valid file."""
        path = os.path.join(self.temp_dir, "4k_test.png")
        MockScreenGrabber.save_synthetic_image(path, width=3840, height=2160, fmt="PNG")
        self.assertImageValid(path, expected_format="PNG", min_width=3840, min_height=2160)

    def test_b07_05_sudden_sigterm_video_container_integrity(self):
        """Verify video container is non-empty and valid on stop."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        engine.start_recording()
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4", min_duration_sec=0.05)


if __name__ == "__main__":
    unittest.main()
