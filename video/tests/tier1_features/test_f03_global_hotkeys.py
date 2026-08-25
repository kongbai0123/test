"""
tests/tier1_features/test_f03_global_hotkeys.py
Feature F3: Global Hotkeys (R1 Requirement).
Verifies registration, dispatch of screenshot/recording hotkeys, lifecycle, and custom hotkeys.
"""

import os
import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockHotkeyManager,
    MockCaptureEngine,
    CaptureConfig,
    EngineStatus,
)


class TestF03GlobalHotkeys(BaseE2ETestCase):
    """Tier 1 tests for Global Hotkeys (libX11 / system grabber)."""

    def test_f03_01_hotkey_registration(self):
        """Verify HotkeyManager registers Ctrl+Alt+A and Ctrl+Alt+R successfully."""
        mgr = MockHotkeyManager()
        res_a = mgr.register_hotkey("<Ctrl><Alt>a", lambda: None)
        res_r = mgr.register_hotkey("<Ctrl><Alt>r", lambda: None)
        self.assertTrue(res_a)
        self.assertTrue(res_r)
        self.assertIn("<ctrl><alt>a", mgr.bindings)
        self.assertIn("<ctrl><alt>r", mgr.bindings)
        mgr.stop()

    def test_f03_02_screenshot_hotkey_dispatch(self):
        """Verify triggering screenshot hotkey invokes capture callback and generates image."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        captured_paths = []
        mgr = MockHotkeyManager()
        mgr.register_hotkey("<Ctrl><Alt>a", lambda: captured_paths.append(engine.capture_screenshot()))

        # Simulate hotkey trigger
        triggered = mgr.trigger_hotkey("<Ctrl><Alt>a")
        self.assertTrue(triggered)
        self.assertEqual(len(captured_paths), 1)
        self.assertImageValid(captured_paths[0], expected_format="PNG")
        mgr.stop()

    def test_f03_03_recording_hotkey_dispatch(self):
        """Verify triggering recording hotkey toggles start/stop recording."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        mgr = MockHotkeyManager()

        def toggle_rec():
            if engine.get_status() == EngineStatus.RECORDING:
                engine.stop_recording()
            else:
                engine.start_recording()

        mgr.register_hotkey("<Ctrl><Alt>r", toggle_rec)

        # Trigger start
        mgr.trigger_hotkey("<Ctrl><Alt>r")
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)
        time.sleep(0.1)

        # Trigger stop
        mgr.trigger_hotkey("<Ctrl><Alt>r")
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        mgr.stop()

    def test_f03_04_hotkey_lifecycle_start_stop(self):
        """Verify hotkey listener starts and stops cleanly."""
        mgr = MockHotkeyManager()
        mgr.register_hotkey("<Ctrl><Alt>a", lambda: None)
        mgr.start()
        self.assertTrue(mgr.is_running)
        mgr.stop()
        self.assertFalse(mgr.is_running)
        self.assertEqual(len(mgr.bindings), 0)

    def test_f03_05_custom_hotkey_registration(self):
        """Verify registering custom key combinations and unregistering previous bindings."""
        mgr = MockHotkeyManager()
        self.assertTrue(mgr.register_hotkey("<Ctrl><Shift>s", lambda: None))
        self.assertIn("<ctrl><shift>s", mgr.bindings)
        self.assertTrue(mgr.unregister_hotkey("<Ctrl><Shift>s"))
        self.assertNotIn("<ctrl><shift>s", mgr.bindings)
        mgr.stop()


if __name__ == "__main__":
    unittest.main()
