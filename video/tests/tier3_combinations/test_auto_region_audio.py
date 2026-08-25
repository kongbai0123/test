"""
tests/tier3_combinations/test_auto_region_audio.py
Tier 3: Combination of F6 (Automatic Mode) + F8 (Region ROI) + F9 (Audio Recording).
Verifies cropped auto-capture loop execution with audio enabled.
"""

import unittest
from PIL import Image
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    CaptureMode,
    Region,
)


class TestAutoRegionAudio(BaseE2ETestCase):
    """Test interaction between Auto Mode, Region ROI, and Audio configuration."""

    def test_auto_region_audio_capture_loop(self):
        """Verify recurring auto-capture produces images conforming to specified ROI dimensions."""
        roi = Region(100, 100, 400, 300)
        config = CaptureConfig(
            mode=CaptureMode.AUTOMATIC,
            interval=0.1,
            region=roi,
            audio_enabled=True,
            audio_source="default",
            output_dir=self.temp_dir,
        )
        engine = MockCaptureEngine(config)
        captures = []
        engine.start_auto_mode(interval=0.1, callback=lambda path: captures.append(path))

        self.wait_for_condition(lambda: len(captures) >= 3, timeout=3.0)
        engine.stop_auto_mode()

        self.assertGreaterEqual(len(captures), 3)
        for path in captures:
            self.assertImageValid(path, expected_format="PNG")
            with Image.open(path) as img:
                self.assertEqual(img.size, (400, 300))


if __name__ == "__main__":
    unittest.main()
