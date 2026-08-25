"""
src/gui/header.py
Header toolbar widget containing Mode Toggle [Manual | Automatic], Interval Textbox, and Status Badge.
"""

import logging
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from src.config import CaptureMode

logger = logging.getLogger("GUI.Header")


class HeaderWidget(Gtk.HeaderBar):
    """
    Top HeaderBar / Dashboard control header for single-window GUI.
    """

    def __init__(
        self,
        on_mode_changed: Optional[Callable[[CaptureMode], None]] = None,
        on_interval_changed: Optional[Callable[[float], None]] = None,
    ):
        super().__init__()
        self.set_title("視訊鏡頭與螢幕錄製擷取系統")
        self.set_subtitle("Ubuntu Linux (NVIDIA 繪圖硬體加速)")
        self.set_show_close_button(True)

        self.on_mode_changed = on_mode_changed
        self.on_interval_changed = on_interval_changed

        self.current_mode = CaptureMode.MANUAL
        self.interval_val = 3.0

        self._init_ui()

    def _init_ui(self) -> None:
        """Construct header widgets."""
        # Mode Toggle Switch (Manual / Automatic)
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        mode_lbl = Gtk.Label()
        mode_lbl.set_markup('<span foreground="#FFFFFF" weight="bold">模式：</span>')
        mode_box.pack_start(mode_lbl, False, False, 0)

        self.mode_combo = Gtk.ComboBoxText()
        self.mode_combo.append("manual", "手動模式")
        self.mode_combo.append("automatic", "自動模式")
        self.mode_combo.set_active_id("manual")
        self.mode_combo.set_tooltip_text("按 Tab 鍵可快速切換手動／自動模式")
        self.mode_combo.connect("changed", self._on_mode_combo_changed)
        mode_box.pack_start(self.mode_combo, False, False, 0)

        self.pack_start(mode_box)

        # Interval Textbox for Auto Mode
        interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        interval_lbl = Gtk.Label()
        interval_lbl.set_markup('<span foreground="#FFFFFF" weight="bold">擷取間隔 (秒)：</span>')
        interval_box.pack_start(interval_lbl, False, False, 0)

        self.interval_entry = Gtk.Entry()
        self.interval_entry.set_text("3.0")
        self.interval_entry.set_width_chars(6)
        self.interval_entry.connect("changed", self._on_interval_entry_changed)
        interval_box.pack_start(self.interval_entry, False, False, 0)

        self.pack_start(interval_box)

        # Status Badge Indicator
        self.status_badge = Gtk.Label(label=" [ 待命 ] ")
        self.status_badge.set_name("status-badge")
        self.pack_end(self.status_badge)

        # Camera Device Status Badge
        self.camera_badge = Gtk.Label(label=" [ 📷 鏡頭連線中... ] ")
        self.camera_badge.set_name("camera-badge")
        self.pack_end(self.camera_badge)

    def _on_mode_combo_changed(self, combo):
        active_id = combo.get_active_id()
        if active_id == "automatic":
            self.current_mode = CaptureMode.AUTOMATIC
        else:
            self.current_mode = CaptureMode.MANUAL

        if self.on_mode_changed:
            self.on_mode_changed(self.current_mode)

    def _on_interval_entry_changed(self, entry):
        text = entry.get_text().strip()
        try:
            val = float(text)
            if val >= 0.1:
                self.interval_val = val
                if self.on_interval_changed:
                    self.on_interval_changed(val)
        except ValueError:
            pass

    def update_status_badge(self, status_text: str, color_css: str = "green") -> None:
        """Update header status badge text and CSS class for high contrast."""
        display_map = {
            "IDLE": "待命",
            "RECORDING": "錄影中",
            "AUTO_ACTIVE": "自動擷取中",
        }
        translated_status = display_map.get(status_text, status_text)
        self.status_badge.set_text(f" [ {translated_status} ] ")
        style_ctx = self.status_badge.get_style_context()
        style_ctx.remove_class("badge-idle")
        style_ctx.remove_class("badge-recording")
        style_ctx.remove_class("badge-auto")
        if "RECORDING" in status_text or "錄影" in status_text:
            style_ctx.add_class("badge-recording")
        elif "AUTO" in status_text or "自動" in status_text:
            style_ctx.add_class("badge-auto")
        else:
            style_ctx.add_class("badge-idle")

    def update_camera_badge(self, text: str, is_live: bool = False) -> None:
        """Update camera badge status text and styling."""
        self.camera_badge.set_text(f" [ 📷 {text} ] ")
        style_ctx = self.camera_badge.get_style_context()
        style_ctx.remove_class("badge-idle")
        style_ctx.remove_class("badge-auto")
        if is_live:
            style_ctx.add_class("badge-idle")
        else:
            style_ctx.add_class("badge-auto")
