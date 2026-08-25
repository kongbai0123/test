"""
src/engine/scheduler.py
High-precision, drift-free periodic scheduler using time.monotonic() target progression.
Maintains sub-millisecond precision (< 1ms drift) over long execution runs.
"""

from __future__ import annotations

import inspect
import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("CaptureEngine.Scheduler")


def _detect_callback_style(cb: Callable) -> str:
    """Inspects callable signature to determine argument dispatch pattern: 'none', 'two', or 'one'."""
    try:
        sig = inspect.signature(cb)
        params = list(sig.parameters.values())
        if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
            return "two"
        req = [
            p
            for p in params
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            and p.default is inspect.Parameter.empty
        ]
        if len(req) == 0:
            return "none"
        elif len(req) == 1:
            return "one"
        else:
            return "two"
    except Exception:
        return "none"


class MonotonicScheduler:
    """
    High-precision, drift-free periodic scheduler using time.monotonic() target alignment.
    Eliminates cumulative timer drift across recurring execution cycles.
    """

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._interval: float = 5.0
        self._callback: Optional[Callable] = None
        self._cb_style: str = "none"
        self._on_error: Optional[Callable[[Exception], None]] = None
        self._is_running: bool = False
        self._tick_count: int = 0

    @property
    def interval(self) -> float:
        with self._lock:
            return self._interval

    def is_running(self) -> bool:
        """Returns True if the scheduler loop is actively running."""
        with self._lock:
            return self._is_running

    def is_active(self) -> bool:
        """Alias for is_running()."""
        return self.is_running()

    def get_tick_count(self) -> int:
        """Returns the number of ticks dispatched since last start."""
        with self._lock:
            return self._tick_count

    def set_interval(self, interval: float) -> None:
        """Dynamically updates the scheduler interval."""
        val = float(interval)
        if not (0.5 <= val <= 3600.0):
            raise ValueError(f"Scheduler interval must be between 0.5s and 3600.0s, got {val}")
        with self._lock:
            self._interval = val

    def start(
        self,
        interval: float,
        callback: Callable[[], None] | Callable[[str], None] | Callable[[float, float], None],
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        """
        Starts periodic execution at the exact specified interval (0.5s - 3600.0s).

        Args:
            interval: Periodic interval in seconds.
            callback: Callable to execute each tick.
            on_error: Optional error callback if tick execution raises an exception.
        """
        interval = float(interval)
        if not (0.5 <= interval <= 3600.0):
            raise ValueError(f"Scheduler interval must be between 0.5s and 3600.0s, got {interval}")

        with self._lock:
            if self._is_running:
                self.stop()

            self._interval = interval
            self._callback = callback
            self._cb_style = _detect_callback_style(callback) if callback is not None else "none"
            self._on_error = on_error
            self._stop_event.clear()
            self._is_running = True
            self._tick_count = 0

            self._thread = threading.Thread(
                target=self._run_loop,
                name="MonotonicSchedulerThread",
                daemon=True,
            )
            self._thread.start()
            logger.info(f"MonotonicScheduler started with interval {interval}s")

    def stop(self, timeout: float = 2.0) -> None:
        """Stops the scheduler cleanly and joins the background worker thread."""
        with self._lock:
            if not self._is_running:
                return
            self._stop_event.set()
            self._is_running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("MonotonicScheduler stopped")

    def _run_loop(self) -> None:
        """Core drift-free target alignment execution loop."""
        with self._lock:
            interval = self._interval

        start_time = time.monotonic()
        target_time = start_time + interval

        while not self._stop_event.is_set():
            now = time.monotonic()
            wait_time = target_time - now

            # Coarse sleep with a 2ms safety margin if wait_time is large enough
            if wait_time > 0.003:
                if self._stop_event.wait(timeout=wait_time - 0.002):
                    break

            # Micro sleep/spin for the final sub-millisecond to eliminate OS scheduling jitter
            while not self._stop_event.is_set():
                rem = target_time - time.monotonic()
                if rem <= 0:
                    break
                if rem > 0.0005:
                    time.sleep(0.0001)

            if self._stop_event.is_set():
                break

            tick_now = time.monotonic()
            drift = tick_now - target_time

            with self._lock:
                self._tick_count += 1
                cb = self._callback
                cb_style = self._cb_style
                if cb is not None and cb_style == "none":
                    cb_style = _detect_callback_style(cb)
                    self._cb_style = cb_style

            # Dispatch callback safely without crashing the scheduler thread
            if cb is not None:
                try:
                    if cb_style == "two":
                        cb(tick_now, drift)
                    elif cb_style == "one":
                        cb(drift)
                    else:
                        cb()
                except Exception as e:
                    self._handle_error(e)

            # Re-read interval in case it was modified dynamically
            with self._lock:
                current_interval = self._interval

            # Advance target time monotonically along the grid
            target_time += current_interval

            # Overrun protection: advance target_time along exact integer multiples of current_interval
            now_after_cb = time.monotonic()
            while target_time <= now_after_cb:
                target_time += current_interval

    def _handle_error(self, e: Exception) -> None:
        logger.error(f"Error in scheduler callback: {e}", exc_info=True)
        if self._on_error:
            try:
                self._on_error(e)
            except Exception:
                pass


# Alias for interface compatibility
AutoScheduler = MonotonicScheduler
AutoCaptureScheduler = MonotonicScheduler
