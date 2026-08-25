"""
src/system/floating_bar.py
Floating recording control bar overlay with live timer display, pause/resume, and stop controls.
"""

import logging
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk

logger = logging.getLogger("System.FloatingBar")


class FloatingBar(Gtk.Window):
    """
    Topmost, borderless floating bar overlay during active recording.
    """

    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("錄影控制工具列")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_resizable(False)

        self.on_pause: Optional[Callable[[], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None
        self.is_paused = False
        self.elapsed_seconds = 0.0

        self._init_ui()

    def _init_ui(self) -> None:
        """Construct Floating Control Bar layout."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        main_box.set_border_width(8)

        # Style CSS
        css_provider = Gtk.CssProvider()
        css_data = b"""
        window {
            background-color: rgba(30, 30, 40, 0.92);
            border-radius: 10px;
            border: 1px solid #FF5555;
        }
        label {
            color: #FFFFFF;
            font-weight: bold;
            font-size: 14px;
        }
        button {
            background-color: #2A2A38;
            background-image: none;
            color: #FFFFFF;
            border-radius: 6px;
            padding: 4px 10px;
            border: 1px solid #444455;
        }
        button:hover {
            background-color: #3B3B4F;
            background-image: none;
        }
        button#stop-btn {
            background-color: #E74C3C;
            background-image: none;
            border: 1px solid #C0392B;
        }
        button#stop-btn:hover {
            background-color: #FF5555;
            background-image: none;
        }
        button label, button * {
            color: #FFFFFF;
            font-weight: bold;
        }
        """
        css_provider.load_from_data(css_data)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Recording Status Indicator (red dot)
        self.status_lbl = Gtk.Label(label="🔴 00:00")
        main_box.pack_start(self.status_lbl, False, False, 5)

        # Pause / Resume Button
        self.pause_btn = Gtk.Button(label="暫停")
        self.pause_btn.connect("clicked", self._on_pause_clicked)
        main_box.pack_start(self.pause_btn, False, False, 0)

        # Stop Button
        self.stop_btn = Gtk.Button(label="停止錄影")
        self.stop_btn.set_name("stop-btn")
        self.stop_btn.connect("clicked", self._on_stop_clicked)
        main_box.pack_start(self.stop_btn, False, False, 0)

        self.add(main_box)

        # Enable window dragging
        self.connect("button-press-event", self._on_button_press)

    def _on_button_press(self, widget, event):
        if event.button == 1:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)

    def show_bar(self, on_pause: Optional[Callable[[], None]] = None, on_stop: Optional[Callable[[], None]] = None) -> None:
        """Show floating bar at top center of screen."""
        self.on_pause = on_pause
        self.on_stop = on_stop
        self.is_paused = False
        self.elapsed_seconds = 0.0
        self.pause_btn.set_label("暫停")
        self.update_timer(0.0)

        # Position top center
        screen = Gdk.Screen.get_default()
        sw = screen.get_width() if screen else 1920
        self.move(sw // 2 - 100, 30)
        self.show_all()

    def hide_bar(self) -> None:
        """Hide floating bar."""
        self.hide()

    def update_timer(self, elapsed_seconds: float) -> None:
        """Update live timer label."""
        self.elapsed_seconds = elapsed_seconds
        mins = int(elapsed_seconds) // 60
        secs = int(elapsed_seconds) % 60
        dot = "🟡" if self.is_paused else "🔴"
        self.status_lbl.set_text(f"{dot} {mins:02d}:{secs:02d}")

    def set_paused(self, is_paused: bool) -> None:
        """Update pause/resume button state."""
        self.is_paused = is_paused
        self.pause_btn.set_label("繼續" if is_paused else "暫停")
        self.update_timer(self.elapsed_seconds)

    def _on_pause_clicked(self, btn):
        if self.on_pause:
            self.on_pause()

    def _on_stop_clicked(self, btn):
        if self.on_stop:
            self.on_stop()
