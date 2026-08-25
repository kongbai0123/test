"""
src/system/region_picker.py
Interactive fullscreen rubberband region selector overlay window.
"""

import logging
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

from src.config import Region

logger = logging.getLogger("System.RegionPicker")


class RegionPicker(Gtk.Window):
    """
    Interactive full-screen overlay allowing click-and-drag ROI region selection.
    """

    def __init__(self, on_selected: Optional[Callable[[Optional[Region]], None]] = None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.on_selected = on_selected
        self.set_title("Select Region")
        self.set_decorated(False)
        self.fullscreen()
        self.set_keep_above(True)
        self.set_app_paintable(True)

        self.start_x = 0
        self.start_y = 0
        self.current_x = 0
        self.current_y = 0
        self.is_dragging = False

        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_button_press)
        self.connect("motion-notify-event", self._on_motion_notify)
        self.connect("button-release-event", self._on_button_release)
        self.connect("key-press-event", self._on_key_press)

        self.set_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )

    def select_region(self, on_selected: Callable[[Optional[Region]], None]) -> None:
        """Show full-screen selection overlay."""
        self.on_selected = on_selected
        self.is_dragging = False
        self.show_all()
        self.fullscreen()

    def _on_draw(self, widget, cr):
        # Draw semi-transparent dim overlay
        cr.set_source_rgba(0, 0, 0, 0.3)
        cr.paint()

        if self.is_dragging or (self.start_x != self.current_x and self.start_y != self.current_y):
            x = min(self.start_x, self.current_x)
            y = min(self.start_y, self.current_y)
            w = abs(self.current_x - self.start_x)
            h = abs(self.current_y - self.start_y)

            # Clear selection rectangle
            cr.set_operator(1)  # CLEAR
            cr.rectangle(x, y, w, h)
            cr.fill()

            # Draw selection border
            cr.set_operator(0)  # OVER
            cr.set_source_rgb(0.2, 0.6, 1.0)
            cr.set_line_width(2)
            cr.rectangle(x, y, w, h)
            cr.stroke()

        return False

    def _on_button_press(self, widget, event):
        if event.button == 1:
            self.start_x = int(event.x)
            self.start_y = int(event.y)
            self.current_x = self.start_x
            self.current_y = self.start_y
            self.is_dragging = True
            self.queue_draw()

    def _on_motion_notify(self, widget, event):
        if self.is_dragging:
            self.current_x = int(event.x)
            self.current_y = int(event.y)
            self.queue_draw()

    def _on_button_release(self, widget, event):
        if event.button == 1 and self.is_dragging:
            self.is_dragging = False
            self.hide()
            x = min(self.start_x, int(event.x))
            y = min(self.start_y, int(event.y))
            w = abs(int(event.x) - self.start_x)
            h = abs(int(event.y) - self.start_y)

            if w > 5 and h > 5:
                region = Region(x, y, w, h)
            else:
                region = None  # Too small, default fullscreen

            if self.on_selected:
                self.on_selected(region)

    def _on_key_press(self, widget, event):
        # Escape key cancels selection
        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            if self.on_selected:
                self.on_selected(None)
