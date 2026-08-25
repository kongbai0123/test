"""
tests/tier3_combinations/test_pause_resume_roi_audio.py
Tier 3: Combination of F4 (Floating Bar) + F8 (ROI Region) + F9 (Audio) + F10 (Video) + F11 (Pause/Resume).
Verifies multi-segment ROI video recording with audio and floating bar control.
"""

import time
import unittest
import cv2
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    MockFloatingBar,
    CaptureConfig,
    Region,
    EngineStatus,
)


class TestPauseResumeRoiAudio(BaseE2ETestCase):
    """Test comprehensive combination of Floating Bar, ROI Region, Audio, and Pause/Resume."""

    def test_roi_audio_recording_with_pause_resume(self):
        """Verify video recorded with ROI and audio across pause/resume boundary is valid."""
        roi = Region(50, 50, 640, 480)
        config = CaptureConfig(
            output_dir=self.temp_dir,
            region=roi,
            audio_enabled=True,
            audio_source="default",
        )
        engine = MockCaptureEngine(config)
        bar = MockFloatingBar()

        # 1. Start recording
        engine.start_recording(config)
        bar.show_bar()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        time.sleep(0.05)

        # 2. Pause recording
        engine.pause_recording()
        bar.set_paused(True)
        self.assertEqual(engine.get_status(), EngineStatus.PAUSED)
        time.sleep(0.05)

        # 3. Resume recording
        engine.resume_recording()
        bar.set_paused(False)
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        time.sleep(0.05)

        # 4. Stop recording
        path = engine.stop_recording()
        bar.hide_bar()
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)

        # 5. Assert video validity and ROI dimensions
        self.assertVideoValid(path, expected_format="MP4")
        cap = cv2.VideoCapture(path)
        ret, frame = cap.read()
        cap.release()
        self.assertTrue(ret)
        self.assertEqual((frame.shape[1], frame.shape[0]), (640, 480))


if __name__ == "__main__":
    unittest.main()
