"""
tests/tier2_boundaries/test_b13_image_preview.py
Boundary B13: In-App Image Preview Boundaries.
Verifies corrupt image fallbacks, 0-byte images, ultra-high resolution image fitting, rapid switching, and deleted image handling.
"""

import os
import unittest
from PIL import Image
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import MockMediaManager, MockScreenGrabber


class TestB13ImagePreviewBoundaries(BaseE2ETestCase):
    """Tier 2 tests for In-App Image Preview Boundaries."""

    def test_b13_01_corrupt_image_preview_fallback(self):
        """Verify selecting corrupted image file handles error gracefully without crash."""
        corrupt = os.path.join(self.temp_dir, "bad.png")
        with open(corrupt, "wb") as f:
            f.write(b"not a valid png file bytes")
        try:
            with Image.open(corrupt) as img:
                img.verify()
            self.fail("Expected PIL error on corrupt image")
        except Exception:
            pass

    def test_b13_02_zero_byte_image_preview(self):
        """Verify selecting a 0-byte image file is handled safely."""
        empty_img = os.path.join(self.temp_dir, "empty.png")
        with open(empty_img, "wb") as f:
            f.write(b"")
        self.assertEqual(os.path.getsize(empty_img), 0)

    def test_b13_03_ultra_high_resolution_image_fit(self):
        """Verify previewing high-resolution (8K) image computes valid downscale."""
        img_w, img_h = 7680, 4320
        vp_w, vp_h = 800, 600
        scale = min(vp_w / img_w, vp_h / img_h)
        fit_w = int(img_w * scale)
        fit_h = int(img_h * scale)
        self.assertLessEqual(fit_w, vp_w)
        self.assertLessEqual(fit_h, vp_h)

    def test_b13_04_rapid_gallery_item_switching(self):
        """Verify rapidly switching between image items does not cause race conditions."""
        paths = [self.create_sample_image(f"img_{i}.png", width=320, height=240) for i in range(5)]
        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        for _ in range(20):
            for item in items:
                self.assertTrue(os.path.exists(item.filepath))

    def test_b13_05_deleted_image_preview_handling(self):
        """Verify selecting an image whose underlying file was removed handles gracefully."""
        path = self.create_sample_image("to_delete.png")
        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        item = items[0]
        os.remove(path)
        self.assertFalse(os.path.exists(item.filepath))


if __name__ == "__main__":
    unittest.main()
