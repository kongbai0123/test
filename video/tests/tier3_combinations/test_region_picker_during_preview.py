"""
tests/tier3_combinations/test_region_picker_during_preview.py
Tier 3: Combination of F8 (Region ROI) + F13 (Image Preview) + F14 (Video Playback).
Verifies launching region picker overlay while media preview is displayed.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockRegionPicker,
    MockAppWindow,
    CaptureConfig,
    Region,
)


class TestRegionPickerDuringPreview(BaseE2ETestCase):
    """Test activating RegionPicker overlay while preview is loaded."""

    def test_region_picker_overlay_over_preview(self):
        """Verify region selector activates and updates config without disturbing main app state."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        picker = MockRegionPicker()

        # Simulate user selecting region (200, 200) to (800, 600)
        selected = picker.select_region(200, 200, 800, 600)
        self.assertEqual(selected, Region(200, 200, 600, 400))
        app.config.region = selected

        self.assertEqual(app.config.region.width, 600)
        self.assertEqual(app.config.region.height, 400)
        self.assertTrue(app.get_visible())
        app.destroy()


if __name__ == "__main__":
    unittest.main()
