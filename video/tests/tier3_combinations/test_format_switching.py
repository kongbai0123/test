"""
tests/tier3_combinations/test_format_switching.py
Tier 3: Combination of F5 (Manual Capture) + F7 (Formats) + F10 (Video Recording).
Verifies sequential capture format chain PNG -> JPG -> MP4 -> WebM.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    OutputFormat,
    MockMediaManager,
)


class TestFormatSwitching(BaseE2ETestCase):
    """Test format switching workflow PNG -> JPG -> MP4 -> WebM."""

    def test_format_switching_workflow_chain(self):
        """Verify sequential captures in distinct formats produce valid containers."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        mgr = MockMediaManager()

        # 1. PNG Screenshot
        cfg_png = CaptureConfig(output_dir=self.temp_dir, image_format=OutputFormat.PNG)
        p1 = engine.capture_screenshot(cfg_png)
        self.assertImageValid(p1, expected_format="PNG")

        # 2. JPG Screenshot
        cfg_jpg = CaptureConfig(output_dir=self.temp_dir, image_format=OutputFormat.JPG)
        p2 = engine.capture_screenshot(cfg_jpg)
        self.assertImageValid(p2, expected_format="JPG")

        # 3. MP4 Video
        cfg_mp4 = CaptureConfig(output_dir=self.temp_dir, video_format=OutputFormat.MP4)
        engine.start_recording(cfg_mp4)
        time.sleep(0.05)
        p3 = engine.stop_recording()
        self.assertVideoValid(p3, expected_format="MP4")

        # 4. WebM Video
        cfg_webm = CaptureConfig(output_dir=self.temp_dir, video_format=OutputFormat.WEBM)
        engine.start_recording(cfg_webm)
        time.sleep(0.05)
        p4 = engine.stop_recording()
        self.assertVideoValid(p4, expected_format="WEBM")

        # Verify MediaManager indexes all 4 files
        items = mgr.scan_captures(self.temp_dir)
        self.assertEqual(len(items), 4)


if __name__ == "__main__":
    unittest.main()
