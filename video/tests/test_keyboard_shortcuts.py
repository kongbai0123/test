"""Regression tests for the global capture-mode keyboard shortcut."""

import unittest
from types import SimpleNamespace

import gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

from src.config import CaptureMode
from src.gui.app import MainWindow


class _ShortcutTarget:
    def __init__(self):
        self.toggle_count = 0

    def _toggle_mode_shortcut(self):
        self.toggle_count += 1


class TestModeKeyboardShortcut(unittest.TestCase):
    def test_tab_toggles_mode_and_consumes_key(self):
        target = _ShortcutTarget()
        handled = MainWindow._on_key_press(
            target,
            None,
            SimpleNamespace(keyval=Gdk.KEY_Tab),
        )

        self.assertTrue(handled)
        self.assertEqual(target.toggle_count, 1)

    def test_shift_tab_also_toggles_mode(self):
        target = _ShortcutTarget()
        handled = MainWindow._on_key_press(
            target,
            None,
            SimpleNamespace(keyval=Gdk.KEY_ISO_Left_Tab),
        )

        self.assertTrue(handled)
        self.assertEqual(target.toggle_count, 1)

    def test_toggle_selects_opposite_mode(self):
        selected = []
        target = SimpleNamespace(
            config=SimpleNamespace(mode=CaptureMode.MANUAL),
            header=SimpleNamespace(
                mode_combo=SimpleNamespace(set_active_id=selected.append)
            ),
        )

        MainWindow._toggle_mode_shortcut(target)
        self.assertEqual(selected, [CaptureMode.AUTOMATIC.value])


if __name__ == "__main__":
    unittest.main()
