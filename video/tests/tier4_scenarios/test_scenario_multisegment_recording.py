"""
tests/tier4_scenarios/test_scenario_multisegment_recording.py
Tier 4 Scenario 3: Multi-Segment Video Recording Series (Pause/Resume Lifecycle).
Simulates recording presentation with multiple pauses, container finalization, and video player verification.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    MockFloatingBar,
    MockVideoPlayer,
    CaptureConfig,
    EngineStatus,
)


class TestScenarioMultisegmentRecording(BaseE2ETestCase):
    """Scenario 3: Multi-segment video recording with pause/resume and player loading."""

    def test_multisegment_recording_and_playback_workflow(self):
        """Verify video recorded across 3 segments produces playable continuous MP4."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir, fps=30))
        bar = MockFloatingBar()
        player = MockVideoPlayer()

        # Segment 1
        engine.start_recording()
        bar.show_bar()
        time.sleep(0.05)
        bar.update_timer(1.0)

        # Pause 1
        engine.pause_recording()
        bar.set_paused(True)
        self.assertEqual(engine.get_status(), EngineStatus.PAUSED)
        time.sleep(0.05)

        # Segment 2
        engine.resume_recording()
        bar.set_paused(False)
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        time.sleep(0.05)

        # Pause 2
        engine.pause_recording()
        bar.set_paused(True)
        time.sleep(0.05)

        # Segment 3
        engine.resume_recording()
        bar.set_paused(False)
        time.sleep(0.05)

        # Finalize recording
        vid_path = engine.stop_recording()
        bar.hide_bar()
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        self.assertVideoValid(vid_path, expected_format="MP4")

        # Load into In-App Video Player
        loaded = player.load_media(vid_path)
        self.assertTrue(loaded)
        self.assertGreater(player.get_duration(), 0.0)
        player.play()
        self.assertTrue(player.is_playing())
        player.seek(player.get_duration() / 2)
        self.assertGreater(player.get_position(), 0.0)
        player.pause()
        self.assertFalse(player.is_playing())


if __name__ == "__main__":
    unittest.main()
