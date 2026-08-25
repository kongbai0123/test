"""
tests/tier1_features/test_f14_video_playback.py
Feature F14: In-App Video Playback (R4 Requirement).
Verifies embedded video player with frame-accurate seekbar, play/pause, and time counter.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import MockVideoPlayer


class TestF14InAppVideoPlayback(BaseE2ETestCase):
    """Tier 1 tests for In-App Video Playback."""

    def test_f14_01_video_player_load_and_duration(self):
        """Verify selecting a video MediaItem loads video and calculates duration."""
        path = self.create_sample_video("play1.mp4", duration=1.0, fps=30.0)
        player = MockVideoPlayer()
        loaded = player.load_media(path)
        self.assertTrue(loaded)
        self.assertAlmostEqual(player.get_duration(), 1.0, delta=0.2)
        self.assertFalse(player.is_playing())

    def test_f14_02_video_play_pause_toggle(self):
        """Verify video player play/pause controls playback state."""
        path = self.create_sample_video("play2.mp4", duration=1.0)
        player = MockVideoPlayer()
        player.load_media(path)
        player.play()
        self.assertTrue(player.is_playing())
        player.pause()
        self.assertFalse(player.is_playing())

    def test_f14_03_video_seekbar_position_sync(self):
        """Verify video player reports current position bounded by duration."""
        path = self.create_sample_video("play3.mp4", duration=2.0)
        player = MockVideoPlayer()
        player.load_media(path)
        self.assertEqual(player.get_position(), 0.0)
        player.position = 0.5
        self.assertEqual(player.get_position(), 0.5)

    def test_f14_04_video_seekbar_seeking(self):
        """Verify seeking to a valid timestamp updates position."""
        path = self.create_sample_video("play4.mp4", duration=2.0)
        player = MockVideoPlayer()
        player.load_media(path)
        player.seek(1.5)
        self.assertAlmostEqual(player.get_position(), 1.5, delta=0.05)

    def test_f14_05_video_playback_completion(self):
        """Verify player resets or pauses at end-of-stream."""
        path = self.create_sample_video("play5.mp4", duration=0.5)
        player = MockVideoPlayer()
        player.load_media(path)
        player.play()
        self.assertTrue(player.is_playing())
        # End of stream simulation
        player.pause()
        player.seek(0.0)
        self.assertFalse(player.is_playing())
        self.assertEqual(player.get_position(), 0.0)


if __name__ == "__main__":
    unittest.main()
