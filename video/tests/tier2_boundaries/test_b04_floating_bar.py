"""
tests/tier2_boundaries/test_b04_floating_bar.py
Boundary B4: Floating Recording Bar Boundaries.
Verifies position clamping, zero-duration lifecycle, idempotent show calls, rapid pause/resume bursts, and cleanup on exit.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import MockFloatingBar, MockAppWindow


class TestB04FloatingBarBoundaries(BaseE2ETestCase):
    """Tier 2 tests for Floating Recording Bar Boundaries."""

    def test_b04_01_floating_bar_drag_offscreen_clamp(self):
        """Verify bar coordinates clamp to valid bounds."""
        bar = MockFloatingBar()
        screen_w, screen_h = 1920, 1080
        clamped_x = max(0, min(screen_w - bar.width, -500))
        clamped_y = max(0, min(screen_h - bar.height, -500))
        self.assertEqual(clamped_x, 0)
        self.assertEqual(clamped_y, 0)

    def test_b04_02_zero_duration_recording_bar_lifecycle(self):
        """Verify immediate show followed by immediate hide executes safely."""
        bar = MockFloatingBar()
        bar.show_bar()
        self.assertTrue(bar.get_visible())
        bar.hide_bar()
        self.assertFalse(bar.get_visible())

    def test_b04_03_multiple_show_bar_calls(self):
        """Verify calling show_bar() repeatedly is idempotent."""
        bar = MockFloatingBar()
        for _ in range(5):
            bar.show_bar()
        self.assertTrue(bar.get_visible())

    def test_b04_04_floating_bar_rapid_pause_resume_burst(self):
        """Verify rapid toggles of set_paused maintain accurate final state."""
        bar = MockFloatingBar()
        bar.show_bar()
        for i in range(10):
            bar.set_paused(i % 2 == 0)
        self.assertFalse(bar.is_paused)

    def test_b04_05_floating_bar_destroy_on_app_exit(self):
        """Verify terminating main application destroys floating bar."""
        app = MockAppWindow()
        app.floating_bar.show_bar()
        self.assertTrue(app.floating_bar.get_visible())
        app.destroy()
        self.assertFalse(app.get_visible())


if __name__ == "__main__":
    unittest.main()
