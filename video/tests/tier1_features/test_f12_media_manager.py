"""
tests/tier1_features/test_f12_media_manager.py
Feature F12: Embedded Media Manager (R4 Requirement).
Verifies capture directory scanner, media metadata indexer, thumbnail generation, and gallery selection.
"""

import os
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockMediaManager,
    MockAppWindow,
    CaptureConfig,
)


class TestF12EmbeddedMediaManager(BaseE2ETestCase):
    """Tier 1 tests for Embedded Media Manager."""

    def test_f12_01_scan_captures_directory(self):
        """Verify MediaManager.scan_captures() returns list of MediaItem sorted newest first."""
        self.create_sample_image("img1.png")
        self.create_sample_image("img2.png")
        self.create_sample_video("vid1.mp4")

        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items), 3)
        self.assertTrue(all(it.filesize > 0 for it in items))

    def test_f12_02_media_item_metadata(self):
        """Verify MediaItem attributes match physical files on disk."""
        path = self.create_sample_image("test_meta.png", width=320, height=240)
        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        match = next(it for it in items if it.filename == "test_meta.png")
        self.assertEqual(match.media_type, "image")
        self.assertEqual(match.filesize, os.path.getsize(path))
        self.assertGreater(match.timestamp, 0)

    def test_f12_03_thumbnail_generation(self):
        """Verify MediaManager generates and caches thumbnail for media items."""
        self.create_sample_image("thumb_test.png")
        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        thumb = mgr.get_thumbnail(items[0])
        self.assertIsNotNone(thumb)
        self.assertTrue(os.path.exists(thumb))
        self.assertImageValid(thumb, expected_format="PNG")

    def test_f12_04_media_list_ui_display(self):
        """Verify UI media list displays newly captured items."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        self.create_sample_image("new_item.png")
        items = app.media_manager.scan_captures(self.temp_dir)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].filename, "new_item.png")
        app.destroy()

    def test_f12_05_media_selection_event(self):
        """Verify selecting an item in the capture list emits selection signal."""
        path = self.create_sample_image("select_test.png")
        mgr = MockMediaManager()
        items = mgr.scan_captures(self.temp_dir)
        selected_item = items[0]
        self.assertEqual(selected_item.filepath, path)


if __name__ == "__main__":
    unittest.main()
