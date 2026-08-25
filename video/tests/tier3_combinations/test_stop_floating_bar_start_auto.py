"""
tests/tier3_combinations/test_stop_floating_bar_start_auto.py
Tier 3: Combination of F4 (Floating Bar) + F6 (Auto) + F10 (Video Recording).
Verifies stopping video recording via floating bar and immediately starting auto-capture mode.
"""

import unittest
from tests.harness.base import BaseE2ETestCase
from tests.harness.mocks import (
    MockCaptureEngine,
    MockFloatingBar,
    CaptureConfig,
    EngineStatus,
)


class TestStopFloatingBarStartAuto(BaseE2ETestCase):
    """Test stopping recording via floating bar followed by starting auto mode."""

    def test_stop_floating_bar_then_start_auto_mode(self):
        """Verify clean transition: RECORDING -> IDLE -> AUTO_ACTIVE."""
        engine = MockCaptureEngine(CaptureConfig(output_dir=self.temp_dir))
        bar = MockFloatingBar()

        # Start recording
        engine.start_recording()
        bar.show_bar()
        self.assertEqual(engine.get_status(), EngineStatus.RECORDING)

        # Stop recording
        path = engine.stop_recording()
        bar.hide_bar()
        self.assertFalse(bar.get_visible())
        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        self.assertVideoValid(path, expected_format="MP4")

        # Start auto mode
        auto_shots = []
        engine.start_auto_mode(interval=0.1, callback=lambda p: auto_shots.append(p))
        self.assertEqual(engine.get_status(), EngineStatus.AUTO_ACTIVE)
        self.wait_for_condition(lambda: len(auto_shots) >= 2, timeout=2.0)
        engine.stop_auto_mode()

        self.assertEqual(engine.get_status(), EngineStatus.IDLE)
        self.assertGreaterEqual(len(auto_shots), 2)


if __name__ == "__main__":
    unittest.main()
