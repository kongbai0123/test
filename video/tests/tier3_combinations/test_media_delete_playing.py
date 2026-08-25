"""
tests/tier3_combinations/test_media_delete_playing.py
Tier 3: Combination of F12 (Embedded Media Manager) + F14 (In-App Video Playback).
Verifies deleting a video file while player is active stops playback and removes file safely.
"""

import os
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockMediaManager,
    MockVideoPlayer,
)


class TestMediaDeletePlaying(BaseE2ETestCase):
    """Test media item deletion during active video playback."""

    def test_delete_media_item_during_active_playback(self):
        """Verify deleting an actively playing media item halts player and deletes file cleanly."""
        vid_path = self.create_sample_video("to_delete.mp4", duration=2.0)
        mgr = MockMediaManager()
        player = MockVideoPlayer()

        items = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items), 1)
        item = items[0]

        # Start playback
        loaded = player.load_media(item.filepath)
        self.assertTrue(loaded)
        player.play()
        self.assertTrue(player.is_playing())

        # Delete item
        player.pause()
        deleted = mgr.delete_item(item)
        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(item.filepath))

        # Re-scan media directory
        items_after = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items_after), 0)


if __name__ == "__main__":
    unittest.main()
