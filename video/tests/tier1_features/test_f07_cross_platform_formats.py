"""
tests/tier1_features/test_f07_cross_platform_formats.py
Feature F7: Cross-Platform Formats (R2 Requirement).
Verifies screenshots in PNG/JPG and videos in MP4 (faststart) / WebM.
"""

import os
import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    OutputFormat,
)


class TestF07CrossPlatformFormats(BaseE2ETestCase):
    """Tier 1 tests for Cross-Platform File Formats."""

    def test_f07_01_png_screenshot_generation(self):
        """Verify screenshot saved with PNG format has valid magic bytes and is readable."""
        config = CaptureConfig(output_dir=self.temp_dir, image_format=OutputFormat.PNG)
        engine = MockCaptureEngine(config)
        path = engine.capture_screenshot(config)
        self.assertTrue(path.endswith(".png"))
        self.assertImageValid(path, expected_format="PNG")

    def test_f07_02_jpg_screenshot_generation(self):
        """Verify screenshot saved with JPG format has valid magic bytes and is readable."""
        config = CaptureConfig(output_dir=self.temp_dir, image_format=OutputFormat.JPG)
        engine = MockCaptureEngine(config)
        path = engine.capture_screenshot(config)
        self.assertTrue(path.endswith(".jpg"))
        self.assertImageValid(path, expected_format="JPG")

    def test_f07_03_mp4_video_generation_and_faststart(self):
        """Verify video saved with MP4 format creates valid decodable MP4 container."""
        config = CaptureConfig(output_dir=self.temp_dir, video_format=OutputFormat.MP4)
        engine = MockCaptureEngine(config)
        engine.start_recording(config)
        time.sleep(0.1)
        path = engine.stop_recording()
        self.assertTrue(path.endswith(".mp4"))
        self.assertVideoValid(path, expected_format="MP4", min_duration_sec=0.05)

    def test_f07_04_webm_video_generation(self):
        """Verify video saved with WEBM format creates valid WebM container."""
        config = CaptureConfig(output_dir=self.temp_dir, video_format=OutputFormat.WEBM)
        engine = MockCaptureEngine(config)
        engine.start_recording(config)
        time.sleep(0.1)
        path = engine.stop_recording()
        self.assertTrue(path.endswith(".webm"))
        self.assertVideoValid(path, expected_format="WEBM", min_duration_sec=0.05)

    def test_f07_05_format_switching_config(self):
        """Verify switching format in config dynamically switches output extension."""
        config = CaptureConfig(output_dir=self.temp_dir, image_format=OutputFormat.PNG)
        engine = MockCaptureEngine(config)
        p1 = engine.capture_screenshot(config)
        self.assertTrue(p1.endswith(".png"))
        self.assertImageValid(p1, expected_format="PNG")

        config.image_format = OutputFormat.JPG
        p2 = engine.capture_screenshot(config)
        self.assertTrue(p2.endswith(".jpg"))
        self.assertImageValid(p2, expected_format="JPG")


if __name__ == "__main__":
    unittest.main()
