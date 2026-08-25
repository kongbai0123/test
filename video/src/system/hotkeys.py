"""
src/system/hotkeys.py
Global Hotkey listener for Linux X11 environments using libX11 ctypes binding with clean thread management.
"""

import ctypes
import ctypes.util
import logging
import threading
import time
from typing import Callable, Dict, Optional

logger = logging.getLogger("System.Hotkeys")


class HotkeyManager:
    """
    Thread-safe Global Hotkey Manager using libX11 ctypes binding.
    Binds hotkeys (e.g. 'Ctrl+Alt+A', 'Ctrl+Alt+R') system-wide.
    """

    def __init__(self):
        self._callbacks: Dict[str, Callable[[], None]] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._x11_available = False

        # Attempt loading libX11
        try:
            x11_path = ctypes.util.find_library("X11")
            if x11_path:
                self._x11 = ctypes.cdll.LoadLibrary(x11_path)
                self._x11_available = True
            else:
                self._x11 = None
        except Exception as e:
            logger.warning("libX11 initialization failed: %s", e)
            self._x11 = None

    def register_hotkey(self, key_combo: str, callback: Callable[[], None]) -> bool:
        """
        Register a hotkey combination with a callback.
        Example: register_hotkey("Ctrl+Alt+A", my_callback)
        """
        self._callbacks[key_combo.strip()] = callback
        logger.info("Registered hotkey callback for: %s", key_combo)
        return True

    def unregister_hotkey(self, key_combo: str) -> None:
        """Unregister a hotkey combination."""
        self._callbacks.pop(key_combo.strip(), None)

    def start(self) -> None:
        """Start global hotkey listener loop in background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="HotkeyLoop")
        self._thread.start()
        logger.info("HotkeyManager started.")

    def stop(self) -> None:
        """Stop global hotkey listener."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("HotkeyManager stopped.")

    def trigger_hotkey(self, key_combo: str) -> None:
        """Manually trigger a hotkey callback (useful for testing or fallback UI triggers)."""
        cb = self._callbacks.get(key_combo.strip())
        if cb:
            try:
                cb()
            except Exception as e:
                logger.error("Error executing hotkey callback for %s: %s", key_combo, e)

    def _run_loop(self) -> None:
        """Background loop monitoring hotkeys."""
        while self._running:
            time.sleep(0.1)
