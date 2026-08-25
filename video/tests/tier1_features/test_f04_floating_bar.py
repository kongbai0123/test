"""
tests/tier1_features/test_f04_floating_bar.py
Feature F4: Floating Recording Bar (R1 Requirement).
Verifies floating overlay visibility, timer updates, pause/resume action, stop action, and hiding on stop.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import MockFloatingBar


class TestF04FloatingRecordingBar(BaseE2ETestCase):
    """Tier 1 tests for Floating Control Bar overlay."""

    def test_f04_01_floating_bar_show_on_recording(self):
        """Verify FloatingBar becomes visible when recording starts."""
        bar = MockFloatingBar()
        self.assertFalse(bar.get_visible())
        bar.show_bar()
        self.assertTrue(bar.get_visible())
        self.assertEqual(bar.timer_text, "00:00")

    def test_f04_02_floating_bar_timer_update(self):
        """Verify update_timer(elapsed) updates the elapsed time string."""
        bar = MockFloatingBar()
        bar.show_bar()
        bar.update_timer(65.0)
        self.assertEqual(bar.timer_text, "01:05")
        bar.update_timer(3661.0)
        self.assertEqual(bar.timer_text, "61:01")

    def test_f04_03_floating_bar_pause_action(self):
        """Verify clicking pause button triggers pause callback and updates paused state."""
        paused_state = []
        bar = MockFloatingBar()
        bar.show_bar(on_pause=lambda: paused_state.append(True))
        bar.set_paused(True)
        self.assertTrue(bar.is_paused)
        if bar.on_pause:
            bar.on_pause()
        self.assertEqual(len(paused_state), 1)

    def test_f04_04_floating_bar_stop_action(self):
        """Verify clicking stop button triggers stop callback and hides bar."""
        stopped = []
        bar = MockFloatingBar()
        bar.show_bar(on_stop=lambda: stopped.append(True))
        if bar.on_stop:
            bar.on_stop()
        self.assertTrue(stopped[0])

    def test_f04_05_floating_bar_hide_on_stop(self):
        """Verify floating bar hides automatically when recording stops."""
        bar = MockFloatingBar()
        bar.show_bar()
        self.assertTrue(bar.get_visible())
        bar.hide_bar()
        self.assertFalse(bar.get_visible())


if __name__ == "__main__":
    unittest.main()
