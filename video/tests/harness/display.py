"""
tests/harness/display.py
Headless X11 Display management and event loop synchronization.
"""

import os
import time
from typing import Optional


class DisplayManager:
    """Manages X11 display environment and event pumping for headless test runs."""

    @staticmethod
    def get_display() -> str:
        """Returns the active X11 display string (defaulting to ':0')."""
        return os.environ.get("DISPLAY", ":0")

    @staticmethod
    def ensure_display() -> bool:
        """Ensures DISPLAY environment variable is populated."""
        if "DISPLAY" not in os.environ:
            os.environ["DISPLAY"] = ":0"
        return True

    @staticmethod
    def pump_tkinter_events(root, iterations: int = 10, delay_sec: float = 0.005) -> None:
        """
        Synchronously flushes all pending Tkinter events and idle tasks.
        Ensures UI updates, timer callbacks, and geometry updates complete.
        """
        if root is None:
            return
        for _ in range(iterations):
            try:
                root.update_idletasks()
                root.update()
            except Exception:
                break
            if delay_sec > 0:
                time.sleep(delay_sec)

    @staticmethod
    def pump_gtk_events(iterations: int = 10, delay_sec: float = 0.005) -> None:
        """
        Synchronously flushes all pending GTK3 main context iterations.
        """
        try:
            import gi
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk
            for _ in range(iterations):
                while Gtk.events_pending():
                    Gtk.main_iteration_do(False)
                if delay_sec > 0:
                    time.sleep(delay_sec)
        except Exception:
            pass
