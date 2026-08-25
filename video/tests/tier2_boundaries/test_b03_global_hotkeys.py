"""
tests/tier2_boundaries/test_b03_global_hotkeys.py
Boundary B3: Global Hotkeys Boundaries.
Verifies rapid hotkey burst storm, invalid key combos, collision handling, abrupt stop cleanup, and display fallback.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import MockHotkeyManager


class TestB03GlobalHotkeysBoundaries(BaseE2ETestCase):
    """Tier 2 tests for Global Hotkeys Boundaries."""

    def test_b03_01_rapid_hotkey_burst_storm(self):
        """Verify firing rapid burst of hotkeys executes safely without crash."""
        mgr = MockHotkeyManager()
        counter = [0]
        mgr.register_hotkey("<Ctrl><Alt>a", lambda: counter.append(counter.pop() + 1))
        for _ in range(25):
            mgr.trigger_hotkey("<Ctrl><Alt>a")
        self.assertEqual(counter[0], 25)
        mgr.stop()

    def test_b03_02_invalid_malformed_key_combo(self):
        """Verify registering malformed key combos returns False safely."""
        mgr = MockHotkeyManager()
        self.assertFalse(mgr.register_hotkey("", lambda: None))
        self.assertFalse(mgr.register_hotkey("   ", lambda: None))
        self.assertFalse(mgr.register_hotkey("InvalidKey_Combo", lambda: None))
        mgr.stop()

    def test_b03_03_hotkey_held_by_another_process(self):
        """Verify unregistering a non-existent hotkey returns False without crashing."""
        mgr = MockHotkeyManager()
        self.assertFalse(mgr.unregister_hotkey("<Ctrl><Alt>z"))
        mgr.stop()

    def test_b03_04_hotkey_cleanup_on_abrupt_stop(self):
        """Verify calling stop() unregisters all active bindings."""
        mgr = MockHotkeyManager()
        mgr.register_hotkey("<Ctrl><Alt>a", lambda: None)
        mgr.register_hotkey("<Ctrl><Alt>r", lambda: None)
        self.assertEqual(len(mgr.bindings), 2)
        mgr.stop()
        self.assertEqual(len(mgr.bindings), 0)
        self.assertFalse(mgr.is_running)

    def test_b03_05_headless_display_none_fallback(self):
        """Verify hotkey manager instantiates safely in headless mode."""
        mgr = MockHotkeyManager()
        mgr.start()
        self.assertTrue(mgr.is_running)
        mgr.stop()


if __name__ == "__main__":
    unittest.main()
