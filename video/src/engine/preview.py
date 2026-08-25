"""Low-latency, latest-frame-only preview preprocessing."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("CaptureEngine.Preview")


@dataclass(frozen=True)
class PreparedPreviewFrame:
    """RGB preview bytes ready for GTK, plus source/runtime metadata."""

    sequence: int
    data: bytes
    width: int
    height: int
    source_width: int
    source_height: int
    measured_fps: float
    configured_fps: float


class LatestFrameProcessor:
    """Prepare frames off the UI thread without ever building a FIFO backlog.

    At most one input is pending. A newer submission replaces an older pending
    frame, which keeps preview latency bounded when conversion cannot keep up
    with the camera.
    """

    def __init__(self, max_width: int = 1000, max_height: int = 680) -> None:
        self.max_width = max(1, int(max_width))
        self.max_height = max(1, int(max_height))
        self._condition = threading.Condition()
        self._pending = None
        self._latest: Optional[PreparedPreviewFrame] = None
        self._latest_submitted_sequence = -1
        self._stop_requested = False
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        with self._condition:
            return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        with self._condition:
            if self._thread and self._thread.is_alive():
                return
            self._stop_requested = False
            self._thread = threading.Thread(
                target=self._run,
                name="camera-preview-convert",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 1.0) -> bool:
        with self._condition:
            self._stop_requested = True
            self._pending = None
            self._condition.notify_all()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        stopped = not thread or not thread.is_alive()
        with self._condition:
            if stopped and self._thread is thread:
                self._thread = None
        return stopped

    def submit(
        self,
        sequence: int,
        frame: np.ndarray,
        *,
        measured_fps: float = 0.0,
        configured_fps: float = 0.0,
    ) -> bool:
        """Submit a read-only frame reference; replace any older pending input."""
        if frame is None or not getattr(frame, "size", 0):
            return False
        with self._condition:
            if self._stop_requested or sequence <= self._latest_submitted_sequence:
                return False
            self._latest_submitted_sequence = sequence
            self._pending = (sequence, frame, measured_fps, configured_fps)
            self._condition.notify()
            return True

    def get_latest(self, after_sequence: int = -1) -> Optional[PreparedPreviewFrame]:
        """Return a prepared result only when it is newer than the caller has seen."""
        with self._condition:
            if self._latest is None or self._latest.sequence <= after_sequence:
                return None
            return self._latest

    def _prepare(
        self,
        sequence: int,
        frame: np.ndarray,
        measured_fps: float,
        configured_fps: float,
    ) -> PreparedPreviewFrame:
        source_height, source_width = frame.shape[:2]
        scale = min(
            self.max_width / source_width,
            self.max_height / source_height,
            1.0,
        )
        if scale < 1.0:
            width = max(1, int(source_width * scale))
            height = max(1, int(source_height * scale))
            # Resize before colour conversion: this reduces the amount of data
            # handled by the following conversion on high-resolution sources.
            resized = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        else:
            width, height = source_width, source_height
            resized = frame
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        return PreparedPreviewFrame(
            sequence=sequence,
            data=rgb.tobytes(),
            width=width,
            height=height,
            source_width=source_width,
            source_height=source_height,
            measured_fps=float(measured_fps),
            configured_fps=float(configured_fps),
        )

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._stop_requested:
                    self._condition.wait()
                if self._stop_requested:
                    return
                work = self._pending
                self._pending = None

            try:
                prepared = self._prepare(*work)
            except Exception:
                # A single malformed/transient frame must not permanently stop
                # preview conversion while capture continues normally.
                logger.exception("Failed to prepare camera preview frame")
                continue

            with self._condition:
                if self._stop_requested:
                    return
                # If conversion fell behind, discard its stale output. The next
                # loop immediately processes the newest pending frame instead.
                if (
                    self._pending is not None
                    and self._pending[0] > prepared.sequence
                ):
                    continue
                self._latest = prepared
