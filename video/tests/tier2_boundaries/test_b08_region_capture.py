"""
tests/tier2_boundaries/test_b08_region_capture.py
Boundary B8: Region & Fullscreen Capture Boundaries.
Verifies 1x1 pixel ROI, odd dimension video alignment, negative coordinates, screen overflow clamping, and inverted region normalization.
"""

import unittest
from PIL import Image
import cv2
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    Region,
    MockRegionPicker,
)


def clamp_region(r: Region, screen_w: int = 1920, screen_h: int = 1080) -> Region:
    """Helper normalizing region within screen bounds."""
    x = max(0, min(screen_w - 1, r.x))
    y = max(0, min(screen_h - 1, r.y))
    w = max(1, min(screen_w - x, r.width))
    h = max(1, min(screen_h - y, r.height))
    return Region(x, y, w, h)


class TestB08RegionCaptureBoundaries(BaseE2ETestCase):
    """Tier 2 tests for Region & Fullscreen Capture Boundaries."""

    def test_b08_01_single_pixel_roi_region_1x1(self):
        """Verify 1x1 pixel ROI region captures valid 1x1 image."""
        roi = Region(10, 10, 1, 1)
        cfg = CaptureConfig(output_dir=self.temp_dir, region=roi)
        engine = MockCaptureEngine(cfg)
        path = engine.capture_screenshot(cfg)
        self.assertImageValid(path, expected_format="PNG", check_non_blank=False)
        with Image.open(path) as img:
            self.assertEqual(img.size, (1, 1))

    def test_b08_02_odd_dimensions_video_roi_alignment(self):
        """Verify odd dimensions (101x99) are adjusted to even dimensions (102x100) for video codecs."""
        roi = Region(0, 0, 101, 99)
        cfg = CaptureConfig(output_dir=self.temp_dir, region=roi)
        engine = MockCaptureEngine(cfg)
        engine.start_recording(cfg)
        path = engine.stop_recording()
        self.assertVideoValid(path, expected_format="MP4")
        cap = cv2.VideoCapture(path)
        ret, frame = cap.read()
        cap.release()
        self.assertTrue(ret)
        # Even dimensions
        self.assertEqual(frame.shape[1] % 2, 0)
        self.assertEqual(frame.shape[0] % 2, 0)

    def test_b08_03_negative_coordinates_clamping(self):
        """Verify negative coordinates are clamped to (0, 0)."""
        raw_r = Region(-50, -20, 300, 200)
        clamped = clamp_region(raw_r, 1920, 1080)
        self.assertGreaterEqual(clamped.x, 0)
        self.assertGreaterEqual(clamped.y, 0)

    def test_b08_04_overflow_screen_bounds_clamping(self):
        """Verify region exceeding screen width/height is clamped to screen edge."""
        raw_r = Region(1800, 1000, 500, 500)
        clamped = clamp_region(raw_r, 1920, 1080)
        self.assertLessEqual(clamped.x + clamped.width, 1920)
        self.assertLessEqual(clamped.y + clamped.height, 1080)

    def test_b08_05_zero_and_inverted_region_rejection(self):
        """Verify inverted drag is normalized and zero-area drag is rejected."""
        picker = MockRegionPicker()
        inverted = picker.select_region(300, 300, 100, 100)
        self.assertEqual(inverted, Region(100, 100, 200, 200))

        zero_area = picker.select_region(100, 100, 100, 100)
        self.assertIsNone(zero_area)


if __name__ == "__main__":
    unittest.main()
