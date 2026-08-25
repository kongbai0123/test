"""
tests/tier2_boundaries/test_b12_media_manager.py
Boundary B12: Embedded Media Manager Boundaries.
Verifies empty directory scanning, large directory scalability, corrupt file handling, special characters/spaces in filenames, and external deletion.
"""

import os
import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import MockMediaManager, MockScreenGrabber


class TestB12MediaManagerBoundaries(BaseE2ETestCase):
    """Tier 2 tests for Embedded Media Manager Boundaries."""

    def test_b12_01_empty_directory_scan(self):
        """Verify scanning an empty directory returns an empty list safely."""
        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        self.assertEqual(items, [])

    def test_b12_02_large_directory_scalability(self):
        """Verify scanning directory with 50 mock captures executes rapidly."""
        for i in range(50):
            fname = f"mock_{i:03d}.png"
            fpath = os.path.join(self.temp_dir, fname)
            with open(fpath, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        mgr = MockMediaManager()
        start = time.monotonic()
        items = mgr.scan_captures(self.temp_dir)
        elapsed = time.monotonic() - start
        self.assertEqual(len(items), 50)
        self.assertLess(elapsed, 1.0)

    def test_b12_03_corrupt_truncated_media_files(self):
        """Verify 0-byte or corrupted files are handled safely without crash."""
        corrupt_png = os.path.join(self.temp_dir, "corrupt.png")
        with open(corrupt_png, "wb") as f:
            f.write(b"")
        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items), 1)
        thumb = mgr.get_thumbnail(items[0])
        self.assertIsNone(thumb)

    def test_b12_04_filenames_with_special_characters_and_spaces(self):
        """Verify files with spaces, unicode, quotes are scanned and indexed properly."""
        fname = "Screen #1 — 日本語 [2026] (test) & more.png"
        path = os.path.join(self.temp_dir, fname)
        MockScreenGrabber.save_synthetic_image(path, 320, 240, "PNG")
        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].filename, fname)
        thumb = mgr.get_thumbnail(items[0])
        self.assertIsNotNone(thumb)

    def test_b12_05_file_deleted_externally(self):
        """Verify scanner updates cleanly when a file is deleted from disk."""
        p1 = self.create_sample_image("img1.png")
        p2 = self.create_sample_image("img2.png")
        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items), 2)
        os.remove(p1)
        items_after = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items_after), 1)
        self.assertEqual(items_after[0].filepath, p2)


if __name__ == "__main__":
    unittest.main()
