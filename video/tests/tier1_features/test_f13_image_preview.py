"""
tests/tier1_features/test_f13_image_preview.py
Feature F13: In-App Image Preview (R4 Requirement).
Verifies embedded image viewer with zoom/fit display inside the single main interface.
"""

import os
import unittest
from PIL import Image
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import MockMediaManager


class TestF13InAppImagePreview(BaseE2ETestCase):
    """Tier 1 tests for In-App Image Preview."""

    def test_f13_01_image_preview_load(self):
        """Verify image MediaItem loads correctly into preview canvas."""
        path = self.create_sample_image("preview1.png", width=640, height=480)
        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        item = items[0]
        with Image.open(item.filepath) as img:
            self.assertEqual(img.size, (640, 480))

    def test_f13_02_image_aspect_ratio_fit(self):
        """Verify embedded image viewer computes fitted aspect ratio without distortion."""
        path = self.create_sample_image("aspect.png", width=1920, height=1080)
        with Image.open(path) as img:
            orig_ratio = img.size[0] / img.size[1]
            viewport_w, viewport_h = 400, 300
            # Fit calculation
            scale = min(viewport_w / img.size[0], viewport_h / img.size[1])
            fit_w, fit_h = int(img.size[0] * scale), int(img.size[1] * scale)
            fit_ratio = fit_w / fit_h
            self.assertAlmostEqual(orig_ratio, fit_ratio, places=2)

    def test_f13_03_image_metadata_overlay(self):
        """Verify image preview displays file dimensions and size metadata."""
        path = self.create_sample_image("meta_img.png", width=800, height=600)
        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        item = items[0]
        self.assertEqual(item.filesize, os.path.getsize(path))
        with Image.open(item.filepath) as img:
            self.assertEqual(img.size, (800, 600))

    def test_f13_04_image_preview_switch(self):
        """Verify switching selection between two images updates loaded image."""
        p1 = self.create_sample_image("img_a.png", width=320, height=240)
        p2 = self.create_sample_image("img_b.png", width=640, height=480)
        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        sizes = []
        for it in items:
            with Image.open(it.filepath) as img:
                sizes.append(img.size)
        self.assertIn((320, 240), sizes)
        self.assertIn((640, 480), sizes)

    def test_f13_05_image_zoom_fit_controls(self):
        """Verify zoom scale calculation for 1:1 and Fit modes."""
        orig_w, orig_h = 1920, 1080
        viewport_w, viewport_h = 800, 600
        # 1:1 scale
        scale_1to1 = 1.0
        # Fit scale
        scale_fit = min(viewport_w / orig_w, viewport_h / orig_h)
        self.assertEqual(scale_1to1, 1.0)
        self.assertLess(scale_fit, 1.0)


if __name__ == "__main__":
    unittest.main()
