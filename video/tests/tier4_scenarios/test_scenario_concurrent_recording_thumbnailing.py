"""
tests/tier4_scenarios/test_scenario_concurrent_recording_thumbnailing.py
Tier 4 Scenario 8: Heavy Concurrency Workload (Video Recording + Asynchronous Thumbnail Generation).
Simulates active video recording concurrent with media gallery thumbnail scanning and generation.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    MockMediaManager,
    CaptureConfig,
    EngineStatus,
)


class TestScenarioConcurrentRecordingThumbnailing(BaseE2ETestCase):
    """Scenario 8: Heavy concurrent recording and media gallery operations."""

    def test_concurrent_recording_and_thumbnail_extraction(self):
        """Verify video recording runs smoothly concurrent with batch thumbnail extraction."""
        # 1. Pre-populate 5 image captures in directory
        for i in range(5):
            self.create_sample_image(f"existing_{i:02d}.png")

        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        mgr = MockMediaManager()

        # 2. Start active video recording
        engine.start_recording()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)

        # 3. Simultaneously trigger thumbnail extraction on existing files
        items = mgr.scan_captures(self.temp_dir)
        self.assertGreaterEqual(len(items), 5)
        for it in items:
            thumb = mgr.get_thumbnail(it)
            self.assertIsNotNone(thumb)

        time.sleep(0.05)

        # 4. Stop video recording
        vid_path = engine.stop_recording()
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        self.assertVideoValid(vid_path, expected_format="MP4")

        # 5. Final media scan includes video and images
        all_items = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(all_items), 6)


if __name__ == "__main__":
    unittest.main()
