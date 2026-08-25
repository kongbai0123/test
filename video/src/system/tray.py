"""
src/system/tray.py
System Tray Integration service using AppIndicator3 / Gtk.StatusIcon.
"""

import logging
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3
    HAS_APP_INDICATOR = True
except Exception:
    HAS_APP_INDICATOR = False

logger = logging.getLogger("System.Tray")


class TrayService:
    """
    Linux System Tray Icon integration service.
    Supports status indicators, context menu actions, and background toggle.
    """

    def __init__(
        self,
        on_show_hide: Optional[Callable[[], None]] = None,
        on_mode_toggle: Optional[Callable[[], None]] = None,
        on_capture: Optional[Callable[[], None]] = None,
        on_record: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
    ):
        self.on_show_hide = on_show_hide
        self.on_mode_toggle = on_mode_toggle
        self.on_capture = on_capture
        self.on_record = on_record
        self.on_quit = on_quit

        self.indicator = None
        self.menu = Gtk.Menu()
        self.is_recording = False

        self._init_tray()

    def _init_tray(self) -> None:
        """Build menu and initialize indicator."""
        # Create Menu items
        self.item_show = Gtk.MenuItem(label="顯示 / 隱藏主視窗")
        if self.on_show_hide:
            self.item_show.connect("activate", lambda w: self.on_show_hide())
        self.menu.append(self.item_show)

        self.item_mode = Gtk.MenuItem(label="切換模式 (手動 / 自動)")
        if self.on_mode_toggle:
            self.item_mode.connect("activate", lambda w: self.on_mode_toggle())
        self.menu.append(self.item_mode)

        self.menu.append(Gtk.SeparatorMenuItem())

        self.item_capture = Gtk.MenuItem(label="拍攝快照 (截圖)")
        if self.on_capture:
            self.item_capture.connect("activate", lambda w: self.on_capture())
        self.menu.append(self.item_capture)

        self.item_record = Gtk.MenuItem(label="開始錄影")
        if self.on_record:
            self.item_record.connect("activate", lambda w: self.on_record())
        self.menu.append(self.item_record)

        self.menu.append(Gtk.SeparatorMenuItem())

        self.item_quit = Gtk.MenuItem(label="結束軟體")
        if self.on_quit:
            self.item_quit.connect("activate", lambda w: self.on_quit())
        self.menu.append(self.item_quit)

        self.menu.show_all()

        if HAS_APP_INDICATOR:
            try:
                self.indicator = AppIndicator3.Indicator.new(
                    "screen-recorder-tray",
                    "media-record",
                    AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
                )
                self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
                self.indicator.set_menu(self.menu)
                logger.info("AppIndicator3 tray service initialized successfully.")
            except Exception as e:
                logger.warning("AppIndicator3 init failed, falling back to GTK StatusIcon: %s", e)
                self._init_fallback_status_icon()
        else:
            self._init_fallback_status_icon()

    def _init_fallback_status_icon(self) -> None:
        """Fallback status icon using Gtk.StatusIcon."""
        try:
            self.status_icon = Gtk.StatusIcon()
            self.status_icon.set_from_icon_name("media-record")
            self.status_icon.connect("popup-menu", self._on_status_icon_menu)
            self.status_icon.connect("activate", lambda w: self.on_show_hide() if self.on_show_hide else None)
            logger.info("GTK StatusIcon initialized as tray fallback.")
        except Exception as e:
            logger.error("Failed to initialize GTK StatusIcon fallback: %s", e)

    def _on_status_icon_menu(self, icon, button, time):
        self.menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time)

    def set_recording_state(self, is_recording: bool) -> None:
        """Update recording status badge/icon in tray."""
        self.is_recording = is_recording
        label = "停止錄影" if is_recording else "開始錄影"
        self.item_record.set_label(label)
        icon_name = "media-record-symbolic" if is_recording else "media-record"
        if self.indicator:
            self.indicator.set_icon_full(icon_name, "Recording" if is_recording else "Idle")
