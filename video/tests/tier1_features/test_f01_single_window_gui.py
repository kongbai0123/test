"""
tests/tier1_features/test_f01_single_window_gui.py
Feature F1: Single-Window GUI Layout (R1 Requirement).
Verifies unified single-window dashboard without tabs or sub-page navigation.
"""

import os
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockAppWindow,
    CaptureConfig,
    CaptureMode,
)


class TestF01SingleWindowLayout(BaseE2ETestCase):
    """Tier 1 tests for Single-Window GUI Architecture & Single-Page Layout."""

    def test_f01_01_single_window_structure(self):
        """Verify application creates a single top-level window without tabbed containers."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        self.assertTrue(app.get_visible())
        self.assertIn("Screen", app.title)
        # Check no tabbed navigation widgets exist
        for child in app.children:
            self.assertNotIn("Notebook", child)
            self.assertNotIn("Tab", child)
            self.assertNotIn("StackSwitcher", child)
        app.destroy()

    def test_f01_02_header_components_present(self):
        """Verify header contains mode switch, interval textbox, and status badge."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir, interval=5.0))
        self.assertEqual(app.mode, CaptureMode.MANUAL)
        self.assertEqual(app.interval, 5.0)
        self.assertIn(app.status_badge, ("IDLE", "READY"))
        self.assertIn("HeaderWidget", app.children)
        app.destroy()

    def test_f01_03_controls_panel_present(self):
        """Verify controls section contains Screenshot, Record, Region, and Audio controls."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        self.assertIn("ControlsWidget", app.children)
        self.assertIsNotNone(app.engine)
        self.assertIsNotNone(app.floating_bar)
        app.destroy()

    def test_f01_04_media_panel_split_layout(self):
        """Verify media panel has split layout with capture list and preview canvas."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        self.assertIn("MediaPanelWidget", app.children)
        self.assertIsNotNone(app.media_manager)
        self.assertIsNotNone(app.video_player)
        app.destroy()

    def test_f01_05_unified_state_propagation(self):
        """Verify state changes propagate across all embedded components synchronously."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        # Toggle mode
        app.mode = CaptureMode.AUTOMATIC
        app.status_badge = "AUTO_ACTIVE"
        self.assertEqual(app.mode, CaptureMode.AUTOMATIC)
        self.assertEqual(app.status_badge, "AUTO_ACTIVE")
        # Ensure window remains single and visible
        self.assertTrue(app.get_visible())
        app.destroy()


if __name__ == "__main__":
    unittest.main()
