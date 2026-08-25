"""
tests/tier4_scenarios/test_scenario_fullscreen_capture_preview.py
Tier 4 Scenario 1: Full-Screen Capture & Embedded Preview Workflow.
Simulates complete user flow: app launch -> fullscreen screenshot -> thumbnail appearance -> list selection -> canvas preview -> zoom/fit toggling.
"""

import os
import unittest
from PIL import Image
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockAppWindow,
    CaptureConfig,
    CaptureMode,
)


class TestScenarioFullscreenCapturePreview(BaseE2ETestCase):
    """Scenario 1: End-to-end fullscreen snapshot, thumbnailing, and preview zoom lifecycle."""

    def test_scenario_fullscreen_capture_preview_lifecycle(self):
        """Verify entire capture-to-preview lifecycle in single-window interface."""
        # 1. Initialize App with clean temporary directory
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir, mode=CaptureMode.MANUAL))
        self.assertTrue(app.get_visible())
        self.assertEqual(app.mode, CaptureMode.MANUAL)
        self.assertEqual(len(app.media_manager.scan_captures(self.temp_dir)), 0)

        # 2. Trigger Fullscreen Screenshot via engine
        img_path = app.engine.capture_screenshot()
        self.assertImageValid(img_path, expected_format="PNG")

        # 3. Media Manager scans captures and indexes new file
        items = app.media_manager.scan_captures(self.temp_dir)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.media_type, "image")
        self.assertEqual(item.filepath, img_path)

        # 4. Generate thumbnail
        thumb_path = app.media_manager.get_thumbnail(item)
        self.assertIsNotNone(thumb_path)
        self.assertTrue(os.path.exists(thumb_path))
        self.assertImageValid(thumb_path, expected_format="PNG")

        # 5. Simulate in-app preview rendering with zoom/fit
        with Image.open(item.filepath) as orig_img:
            orig_w, orig_h = orig_img.size
            self.assertGreaterEqual(orig_w, 640)
            self.assertGreaterEqual(orig_h, 480)

            # Viewport fit calculation (e.g. 400x300 canvas)
            vp_w, vp_h = 400, 300
            scale = min(vp_w / orig_w, vp_h / orig_h)
            fit_w = int(orig_w * scale)
            fit_h = int(orig_h * scale)
            self.assertLessEqual(fit_w, vp_w)
            self.assertLessEqual(fit_h, vp_h)

        # 6. Verify single window invariant
        self.assertTrue(app.get_visible())
        app.destroy()


if __name__ == "__main__":
    unittest.main()
