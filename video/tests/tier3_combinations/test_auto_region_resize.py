"""
tests/tier3_combinations/test_auto_region_resize.py
Tier 3: Combination of F6 (Auto Mode) + F8 (Region ROI).
Verifies updating ROI region dimensions while auto-capture scheduler is actively running.
"""

import unittest
from PIL import Image
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    Region,
)


class TestAutoRegionResize(BaseE2ETestCase):
    """Test dynamic ROI region adjustment while auto-capture is active."""

    def test_dynamic_roi_resize_during_auto_mode(self):
        """Verify scheduler respects updated region dimensions across captures."""
        cfg = CaptureConfig(output_dir=self.temp_dir, region=Region(0, 0, 640, 480))
        engine = MockCaptureEngine(cfg)
        captures = []

        engine.start_auto_mode(interval=0.1, callback=lambda p: captures.append(p))
        self.wait_for_condition(lambda: len(captures) >= 1, timeout=2.0)

        # Update region to 320x240
        cfg.region = Region(0, 0, 320, 240)
        self.wait_for_condition(lambda: len(captures) >= 2, timeout=2.0)
        engine.stop_auto_mode()

        self.assertGreaterEqual(len(captures), 2)
        # Check first capture
        with Image.open(captures[0]) as img:
            self.assertEqual(img.size, (640, 480))
        # Check subsequent capture
        with Image.open(captures[-1]) as img:
            self.assertEqual(img.size, (320, 240))


if __name__ == "__main__":
    unittest.main()
