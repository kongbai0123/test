"""
tests/tier4_scenarios/test_scenario_mixed_media_library.py
Tier 4 Scenario 5: Mixed Media Library & Gallery Operations.
Simulates extensive library with 20 mixed files (PNG/JPG/MP4/WebM), sorting, filtering, and previewing.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockMediaManager,
    MockVideoPlayer,
)


class TestScenarioMixedMediaLibrary(BaseE2ETestCase):
    """Scenario 5: Mixed media gallery lifecycle with sorting, filtering, and deleting."""

    def test_mixed_media_library_lifecycle(self):
        """Verify media manager handles 20 mixed format captures cleanly."""
        # Create 5 PNG, 5 JPG, 5 MP4, 5 WebM
        for i in range(5):
            self.create_sample_image(f"snap_{i:02d}.png", fmt="PNG")
            self.create_sample_image(f"photo_{i:02d}.jpg", fmt="JPG")
            self.create_sample_video(f"clip_{i:02d}.mp4", fmt="MP4")
            self.create_sample_video(f"anim_{i:02d}.webm", fmt="WEBM")

        mgr = MockMediaManager()
        player = MockVideoPlayer()

        # 1. Scan directory
        items = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items), 20)

        # 2. Filter by media type
        images = [it for it in items if it.media_type == "image"]
        videos = [it for it in items if it.media_type == "video"]
        self.assertEqual(len(images), 10)
        self.assertEqual(len(videos), 10)

        # 3. Filter by extension
        webm_files = [it for it in items if it.filename.endswith(".webm")]
        self.assertEqual(len(webm_files), 5)

        # 4. Preview / Thumbnail generation for first 3 items
        for it in items[:3]:
            if it.media_type == "image":
                thumb = mgr.get_thumbnail(it)
                self.assertIsNotNone(thumb)
            else:
                loaded = player.load_media(it.filepath)
                self.assertTrue(loaded)

        # 5. Delete 2 items
        mgr.delete_item(items[0])
        mgr.delete_item(items[1])
        items_remaining = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items_remaining), 18)


if __name__ == "__main__":
    unittest.main()
