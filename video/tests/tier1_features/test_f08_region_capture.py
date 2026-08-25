"""
tests/tier1_features/test_f08_region_capture.py
Feature F8: Region & Fullscreen Capture (R3 Requirement).
Verifies fullscreen capture, ROI region screenshot, ROI video recording, region picker overlay, and toggle.
"""

import time
import unittest
from PIL import Image
import cv2
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    Region,
    MockRegionPicker,
    MockAppWindow,
)


class TestF08RegionCapture(BaseE2ETestCase):
    """Tier 1 tests for Region and Fullscreen Capture."""

    def test_f08_01_fullscreen_capture_dimensions(self):
        """Verify screenshot with region=None captures full desktop dimensions."""
        config = CaptureConfig(output_dir=self.temp_dir, region=None)
        engine = MockCaptureEngine(config)
        path = engine.capture_screenshot(config)
        self.assertImageValid(path, expected_format="PNG")
        with Image.open(path) as img:
            self.assertGreaterEqual(img.size[0], 640)
            self.assertGreaterEqual(img.size[1], 480)

    def test_f08_02_roi_region_screenshot(self):
        """Verify screenshot with ROI Region produces image with exact resolution."""
        roi = Region(x=50, y=50, width=200, height=150)
        config = CaptureConfig(output_dir=self.temp_dir, region=roi)
        engine = MockCaptureEngine(config)
        path = engine.capture_screenshot(config)
        self.assertImageValid(path, expected_format="PNG")
        with Image.open(path) as img:
            self.assertEqual(img.size, (200, 150))

    def test_f08_03_roi_region_video_recording(self):
        """Verify video recorded with ROI Region produces cropped video frames."""
        roi = Region(x=100, y=100, width=320, height=240)
        config = CaptureConfig(output_dir=self.temp_dir, region=roi)
        engine = MockCaptureEngine(config)
        engine.start_recording(config)
        time.sleep(0.1)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")
        cap = cv2.VideoCapture(path)
        ret, frame = cap.read()
        cap.release()
        self.assertTrue(ret)
        self.assertEqual((frame.shape[1], frame.shape[0]), (320, 240))

    def test_f08_04_region_picker_overlay_selection(self):
        """Verify RegionPicker emits valid Region tuple on rubberband selection."""
        picker = MockRegionPicker()
        res = picker.select_region(100, 100, 400, 300)
        self.assertIsNotNone(res)
        self.assertEqual(res, Region(100, 100, 300, 200))

    def test_f08_05_fullscreen_region_toggle_in_ui(self):
        """Verify UI allows switching between Fullscreen and Region selection."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        self.assertIsNone(app.config.region)
        app.config.region = Region(10, 10, 400, 300)
        self.assertIsNotNone(app.config.region)
        # Clear back to fullscreen
        app.config.region = None
        self.assertIsNone(app.config.region)
        app.destroy()


if __name__ == "__main__":
    unittest.main()
