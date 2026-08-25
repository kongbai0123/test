"""
tests/tier2_boundaries/test_b14_video_playback.py
Boundary B14: In-App Video Playback Boundaries.
Verifies corrupted video handling, out-of-bounds seeking, rapid seek scrubbing stress, zero-duration video, and file deletion during playback.
"""

import os
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import MockVideoPlayer


class TestB14VideoPlaybackBoundaries(BaseE2ETestCase):
    """Tier 2 tests for In-App Video Playback Boundaries."""

    def test_b14_01_corrupted_truncated_video_playback(self):
        """Verify attempting to load a truncated or corrupted video is handled safely."""
        bad_vid = os.path.join(self.temp_dir, "bad.mp4")
        with open(bad_vid, "wb") as f:
            f.write(b"corrupted video header")
        player = MockVideoPlayer()
        loaded = player.load_media(bad_vid)
        self.assertFalse(loaded)
        self.assertEqual(player.get_duration(), 0.0)

    def test_b14_02_seek_beyond_duration_bounds(self):
        """Verify seeking past duration or negative time is clamped to [0.0, duration]."""
        path = self.create_sample_video("seek_test.mp4", duration=2.0)
        player = MockVideoPlayer()
        player.load_media(path)
        dur = player.get_duration()
        player.seek(-5.0)
        self.assertEqual(player.get_position(), 0.0)
        player.seek(100.0)
        self.assertEqual(player.get_position(), dur)

    def test_b14_03_rapid_seekbar_scrubbing_stress(self):
        """Verify firing rapid seek calls does not crash player."""
        path = self.create_sample_video("scrub_test.mp4", duration=5.0)
        player = MockVideoPlayer()
        player.load_media(path)
        for t in [0.5, 1.2, 3.8, 0.1, 4.5, 2.0, 4.9]:
            player.seek(t)
            self.assertGreaterEqual(player.get_position(), 0.0)
            self.assertLessEqual(player.get_position(), player.get_duration())

    def test_b14_04_zero_duration_video_playback(self):
        """Verify loading 0-duration or empty video handles duration calculation safely."""
        empty_vid = os.path.join(self.temp_dir, "empty.mp4")
        with open(empty_vid, "wb") as f:
            f.write(b"")
        player = MockVideoPlayer()
        loaded = player.load_media(empty_vid)
        self.assertFalse(loaded)
        self.assertEqual(player.get_duration(), 0.0)

    def test_b14_05_video_file_deleted_during_playback(self):
        """Verify deleting video file while player is active handles cleanly."""
        path = self.create_sample_video("active_play.mp4", duration=1.0)
        player = MockVideoPlayer()
        player.load_media(path)
        player.play()
        self.assertTrue(player.is_playing())
        os.remove(path)
        player.pause()
        self.assertFalse(player.is_playing())


if __name__ == "__main__":
    unittest.main()
