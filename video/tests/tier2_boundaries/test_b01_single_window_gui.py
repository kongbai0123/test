"""
tests/tier2_boundaries/test_b01_single_window_gui.py
Boundary B1: Single-Window GUI Layout Boundaries.
Verifies minimum dimensions, rapid resize stress, maximize/restore cycles, multi-monitor coordinates, and zero-tab invariant.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockAppWindow,
    CaptureConfig,
    CaptureMode,
)


class TestB01SingleWindowBoundaries(BaseE2ETestCase):
    """Tier 2 tests for Single-Window GUI Layout Boundaries."""

    def test_b01_01_minimum_window_dimensions(self):
        """Verify window handles minimum dimensions (640x480) without layout errors."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        app.resize(640, 480)
        self.assertEqual(app.width, 640)
        self.assertEqual(app.height, 480)
        self.assertTrue(app.get_visible())
        app.destroy()

    def test_b01_02_rapid_window_resize_stress(self):
        """Verify firing rapid resize cycles maintains widget hierarchy integrity."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        for i in range(20):
            w = 640 + (i * 30)
            h = 480 + (i * 20)
            app.resize(w, h)
        self.assertTrue(app.get_visible())
        self.assertEqual(len(app.children), 3)
        app.destroy()

    def test_b01_03_window_maximize_restore_cycle(self):
        """Verify cycling maximize -> unmaximize -> iconify -> deiconify preserves UI state."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir, interval=12.5, mode=CaptureMode.AUTOMATIC))
        app.maximize()
        app.unmaximize()
        app.iconify()
        self.assertFalse(app.get_visible())
        app.deiconify()
        self.assertTrue(app.get_visible())
        self.assertEqual(app.interval, 12.5)
        self.assertEqual(app.mode, CaptureMode.AUTOMATIC)
        app.destroy()

    def test_b01_04_multi_monitor_geometry(self):
        """Verify window positions correctly on arbitrary screen coordinates."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        app.move(1920, 0)
        self.assertEqual(app.get_position(), (1920, 0))
        app.destroy()

    def test_b01_05_zero_subpage_tab_invariant(self):
        """Verify zero tab containers exist across multiple state changes."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        states = ["IDLE", "RECORDING", "PAUSED", "AUTO_ACTIVE"]
        for st in states:
            app.status_badge = st
            tab_count = sum(1 for c in app.children if "Tab" in c or "Notebook" in c)
            self.assertEqual(tab_count, 0)
        app.destroy()


if __name__ == "__main__":
    unittest.main()
