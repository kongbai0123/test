"""
tests/test_gui_integration.py
GUI and System Integration component tests for single-window dashboard.
"""

import os
import unittest

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from src.config import CaptureMode, Region
from src.gui.controls import ControlsWidget
from src.gui.header import HeaderWidget
from src.gui.media_panel import MediaPanelWidget
from src.media.manager import MediaManager
from src.media.thumbnail import ThumbnailGenerator
from src.system.floating_bar import FloatingBar
from src.system.hotkeys import HotkeyManager
from src.system.tray import TrayService


class TestGUIComponents(unittest.TestCase):
    """Test instantiation and basic state changes of GUI components."""

    def test_header_widget(self):
        mode_changed = []
        interval_changed = []

        header = HeaderWidget(
            on_mode_changed=lambda m: mode_changed.append(m),
            on_interval_changed=lambda i: interval_changed.append(i),
        )

        header.update_status_badge("RECORDING", "red")
        self.assertTrue(any(tag in header.status_badge.get_text() for tag in ("RECORDING", "錄影中")))

        # Test mode combo selection
        header.mode_combo.set_active_id("automatic")
        self.assertEqual(header.current_mode, CaptureMode.AUTOMATIC)
        self.assertIn(CaptureMode.AUTOMATIC, mode_changed)

        # Test interval entry change
        header.interval_entry.set_text("10.5")
        self.assertEqual(header.interval_val, 10.5)
        self.assertIn(10.5, interval_changed)

    def test_controls_widget(self):
        captured = []
        recorded = []
        region_selected = []
        audio_toggled = []

        controls = ControlsWidget(
            on_capture_screenshot=lambda: captured.append(True),
            on_toggle_record=lambda: recorded.append(True),
            on_select_region=lambda: region_selected.append(True),
            on_toggle_audio=lambda a: audio_toggled.append(a),
        )

        controls.cap_btn.clicked()
        self.assertTrue(captured)

        controls.rec_btn.clicked()
        self.assertTrue(recorded)

        controls.set_recording_state(True)
        self.assertTrue("停止錄影" in controls.rec_btn.get_label() or "Stop Recording" in controls.rec_btn.get_label())

        controls.set_region_label("ROI (800x600)")
        self.assertIn("800x600", controls.region_btn.get_label())

    def test_floating_bar(self):
        bar = FloatingBar()
        bar.update_timer(125.0)
        self.assertIn("02:05", bar.status_lbl.get_text())

        bar.set_paused(True)
        self.assertTrue(bar.is_paused)
        self.assertTrue(bar.pause_btn.get_label() in ("Resume", "繼續"))

    def test_media_manager_and_thumbs(self):
        test_dir = "/tmp/video_test_captures"
        os.makedirs(test_dir, exist_ok=True)

        # Create dummy image
        dummy_img = os.path.join(test_dir, "shot1.png")
        with open(dummy_img, "wb") as f:
            f.write(b"dummy image data")

        manager = MediaManager()
        items = manager.scan_captures(test_dir)
        self.assertTrue(len(items) >= 1)
        self.assertEqual(items[0].media_type, "image")

        thumb_gen = ThumbnailGenerator(cache_dir="/tmp/video_test_thumbs")
        thumb_path = thumb_gen.get_thumbnail(items[0], size=64)
        # Verify generator handled dummy safely

    def test_hotkey_manager(self):
        triggered = []
        mgr = HotkeyManager()
        mgr.register_hotkey("Ctrl+Alt+A", lambda: triggered.append("A"))
        mgr.trigger_hotkey("Ctrl+Alt+A")
        self.assertIn("A", triggered)


if __name__ == "__main__":
    unittest.main()
