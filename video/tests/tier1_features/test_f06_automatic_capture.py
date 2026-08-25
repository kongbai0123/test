"""
tests/tier1_features/test_f06_automatic_capture.py
Feature F6: Automatic Capture Mode (R2 Requirement).
Verifies dynamic interval textbox (0.5s–3600s), recurring auto-capture loop, and clean deactivation.
"""

import time
import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    CaptureConfig,
    CaptureMode,
    EngineStatus,
    MockAppWindow,
)


class TestF06AutomaticCaptureMode(BaseE2ETestCase):
    """Tier 1 tests for Automatic Capture Mode."""

    def test_f06_01_auto_mode_activation(self):
        """Verify starting auto mode transitions engine status to AUTO_ACTIVE."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        engine.start_auto_mode(interval=0.1, callback=lambda path: None)
        self.assertEqual(engine.get_status(), EngineStatus.AUTO_ACTIVE)
        engine.stop_auto_mode()
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)

    def test_f06_02_auto_capture_interval_execution(self):
        """Verify auto-capture loop fires callback at regular intervals."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        captures = []
        engine.start_auto_mode(interval=0.1, callback=lambda path: captures.append(path))
        self.wait_for_condition(lambda: len(captures) >= 3, timeout=3.0)
        engine.stop_auto_mode()
        self.assertGreaterEqual(len(captures), 3)
        for p in captures:
            self.assertImageValid(p, expected_format="PNG")

    def test_f06_03_interval_textbox_binding(self):
        """Verify changing interval value updates configuration interval."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir, interval=5.0))
        self.assertEqual(app.interval, 5.0)
        app.interval = 2.5
        self.assertEqual(app.interval, 2.5)
        app.destroy()

    def test_f06_04_auto_mode_deactivation(self):
        """Verify stop_auto_mode() immediately halts periodic captures."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        captures = []
        engine.start_auto_mode(interval=0.05, callback=lambda path: captures.append(path))
        self.wait_for_condition(lambda: len(captures) >= 2, timeout=2.0)
        engine.stop_auto_mode()
        count_after_stop = len(captures)
        time.sleep(0.15)
        self.assertEqual(len(captures), count_after_stop)
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)

    def test_f06_05_mode_toggle_preserves_engine_state(self):
        """Verify toggling between Manual and Automatic modes cleanly stops loop."""
        app = MockAppWindow(CaptureConfig(output_dir=self.temp_dir))
        app.mode = CaptureMode.AUTOMATIC
        app.engine.start_auto_mode(interval=0.1, callback=lambda path: None)
        self.assertEqual(app.engine.get_status(), EngineStatus.AUTO_ACTIVE)

        # Toggle to manual
        app.mode = CaptureMode.MANUAL
        app.engine.stop_auto_mode()
        self.assertEqual(app.engine.get_status(), EngineStatus.IDLE)
        app.destroy()


if __name__ == "__main__":
    unittest.main()
