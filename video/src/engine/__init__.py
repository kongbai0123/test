"""
src/engine/__init__.py
Unified Screen Capture & Video Recording Engine.
Adheres strictly to PROJECT.md § Interface Contracts.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime
import logging
import os
import threading
from typing import Callable, List, Optional

from src.config import (
    CaptureConfig,
    CaptureMode,
    DEFAULT_CAPTURES_DIR,
    EngineStatus,
    MAX_INTERVAL,
    MIN_INTERVAL,
    OutputFormat,
    Region,
)
from src.engine.audio import AudioDevice, AudioDiscovery, AudioMixer
from src.engine.camera import CameraStream
from src.engine.camera_capabilities import (
    enumerate_v4l2_capabilities,
    select_mode_for_fps,
)
from src.engine.recorder import VideoRecorder, normalize_video_roi
from src.engine.scheduler import AutoScheduler, MonotonicScheduler
from src.engine.screenshot import ScreenGrabber, ScreenshotEngine, normalize_roi

logger = logging.getLogger("CaptureEngine")


class CaptureEngine:
    """
    Unified Screen Capture & Video Recording Engine facade.
    Coordinates ScreenshotEngine, VideoRecorder, AudioMixer, and MonotonicScheduler
    behind a thread-safe unified API adhering to PROJECT.md § Interface Contracts.
    """

    def __init__(self, config: Optional[CaptureConfig] = None) -> None:
        self.config: CaptureConfig = config or CaptureConfig()
        self.config.validate()

        self._status: EngineStatus = EngineStatus.IDLE
        self._lock = threading.RLock()

        # Core subsystems
        self._grabber = ScreenshotEngine()
        self._recorder = VideoRecorder()
        self._scheduler = MonotonicScheduler()
        self._auto_executor: Optional[ThreadPoolExecutor] = None

        # Listeners
        self._status_listeners: List[Callable[[EngineStatus], None]] = []

    # -------------------------------------------------------------------------
    # Status & Listener Management
    # -------------------------------------------------------------------------

    def get_status(self) -> EngineStatus:
        """Returns current engine state: IDLE, RECORDING, PAUSED, AUTO_ACTIVE."""
        with self._lock:
            return self._status

    def _set_status(self, new_status: EngineStatus) -> None:
        with self._lock:
            if self._status == new_status:
                return
            self._status = new_status
            listeners = list(self._status_listeners)

        for cb in listeners:
            try:
                cb(new_status)
            except Exception as e:
                logger.error(f"Error in status listener callback: {e}")

    def add_status_listener(self, callback: Callable[[EngineStatus], None]) -> None:
        """Registers a status transition callback."""
        with self._lock:
            if callback not in self._status_listeners:
                self._status_listeners.append(callback)

    def remove_status_listener(self, callback: Callable[[EngineStatus], None]) -> None:
        """Unregisters a status transition callback."""
        with self._lock:
            if callback in self._status_listeners:
                self._status_listeners.remove(callback)

    # -------------------------------------------------------------------------
    # Screenshot Operations
    # -------------------------------------------------------------------------

    def capture_screenshot(self, config: Optional[CaptureConfig] = None) -> str:
        """
        Takes an immediate screenshot, writes to output_dir, and returns the absolute filepath.
        Can be called manually at any time (including during auto-mode).
        """
        active_config = config or self.config
        active_config.validate()

        filepath = self._grabber.capture_to_file(
            output_dir=active_config.output_dir,
            region=active_config.region,
            image_format=active_config.image_format,
            quality=active_config.jpg_quality,
            filename_prefix="Screenshot",
        )
        logger.info(f"Captured screenshot saved to {filepath}")
        return filepath

    # -------------------------------------------------------------------------
    # Video Recording Operations
    # -------------------------------------------------------------------------

    def start_recording(self, config: Optional[CaptureConfig] = None) -> None:
        """
        Starts video recording in background pipeline.
        Raises RuntimeError if recording is already active or engine is in an illegal state.
        """
        with self._lock:
            if self._status == EngineStatus.RECORDING or self._status == EngineStatus.PAUSED:
                raise RuntimeError(f"Cannot start recording: already in state '{self._status.value}'")
            if self._status == EngineStatus.AUTO_ACTIVE:
                raise RuntimeError("Cannot start recording while Auto Mode is active. Stop Auto Mode first.")

            active_config = config or self.config
            active_config.validate()

            self._recorder.start_recording(config=active_config)
            self._set_status(EngineStatus.RECORDING)
            logger.info("Video recording started")

    def pause_recording(self) -> None:
        """
        Pauses the active video recording without corrupting container timeline.
        Raises RuntimeError if engine is not currently RECORDING.
        """
        with self._lock:
            if self._status != EngineStatus.RECORDING:
                raise RuntimeError(f"Cannot pause recording from state '{self._status.value}' (must be RECORDING)")

            self._recorder.pause_recording()
            self._set_status(EngineStatus.PAUSED)
            logger.info("Video recording paused")

    def resume_recording(self) -> None:
        """
        Resumes a paused video recording seamlessly.
        Raises RuntimeError if engine is not currently PAUSED.
        """
        with self._lock:
            if self._status != EngineStatus.PAUSED:
                raise RuntimeError(f"Cannot resume recording from state '{self._status.value}' (must be PAUSED)")

            self._recorder.resume_recording()
            self._set_status(EngineStatus.RECORDING)
            logger.info("Video recording resumed")

    def stop_recording(self) -> str:
        """
        Stops video recording, finalizes container with EOS, and returns absolute filepath.
        Raises RuntimeError if engine is not RECORDING or PAUSED.
        """
        with self._lock:
            if self._status not in (EngineStatus.RECORDING, EngineStatus.PAUSED):
                raise RuntimeError(f"Cannot stop recording from state '{self._status.value}' (must be RECORDING or PAUSED)")

            filepath = self._recorder.stop_recording()
            self._set_status(EngineStatus.IDLE)
            logger.info(f"Video recording stopped and finalized: {filepath}")
            return filepath

    # -------------------------------------------------------------------------
    # Auto-Mode Periodic Capture Operations
    # -------------------------------------------------------------------------

    def start_auto_mode(self, interval: float, callback: Callable[[str], None]) -> None:
        """
        Starts monotonic auto-capture loop with specified interval in seconds.
        Calls callback(filepath) upon each captured frame.
        """
        with self._lock:
            if self._status == EngineStatus.RECORDING or self._status == EngineStatus.PAUSED:
                raise RuntimeError(f"Cannot start auto mode while video recording is active ({self._status.value})")

            val = float(interval)
            if not (MIN_INTERVAL <= val <= MAX_INTERVAL):
                raise ValueError(f"Auto mode interval must be between {MIN_INTERVAL}s and {MAX_INTERVAL}s, got {val}")

            self.config.interval = val
            self.config.validate()

            if self._auto_executor is not None:
                try:
                    self._auto_executor.shutdown(wait=False)
                except Exception:
                    pass

            self._auto_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="AutoCaptureWorker")

            def _auto_tick_job():
                def _do_capture():
                    try:
                        fpath = self.capture_screenshot(self.config)
                        if callback:
                            callback(fpath)
                    except Exception as e:
                        logger.error(f"Auto-capture tick error: {e}")

                executor = self._auto_executor
                if executor is not None:
                    try:
                        executor.submit(_do_capture)
                    except RuntimeError:
                        # Executor is shutting down
                        pass

            self._scheduler.start(interval=val, callback=_auto_tick_job)
            self._set_status(EngineStatus.AUTO_ACTIVE)
            logger.info(f"Auto-capture mode started with interval {val}s")

    def stop_auto_mode(self) -> None:
        """Stops auto-capture loop cleanly."""
        with self._lock:
            if self._status != EngineStatus.AUTO_ACTIVE:
                return

            self._scheduler.stop()
            if self._auto_executor is not None:
                self._auto_executor.shutdown(wait=True)
                self._auto_executor = None
            self._set_status(EngineStatus.IDLE)
            logger.info("Auto-capture mode stopped")

    # -------------------------------------------------------------------------
    # Cleanup & Lifecycle
    # -------------------------------------------------------------------------

    def close(self) -> None:
        """Cleanly terminates all active pipelines and background threads."""
        with self._lock:
            if self._status in (EngineStatus.RECORDING, EngineStatus.PAUSED):
                try:
                    self.stop_recording()
                except Exception:
                    pass
            if self._status == EngineStatus.AUTO_ACTIVE:
                try:
                    self.stop_auto_mode()
                except Exception:
                    pass
            elif self._auto_executor is not None:
                try:
                    self._auto_executor.shutdown(wait=True)
                    self._auto_executor = None
                except Exception:
                    pass
            self._set_status(EngineStatus.IDLE)


__all__ = [
    "CaptureEngine",
    "CaptureConfig",
    "CaptureMode",
    "OutputFormat",
    "EngineStatus",
    "Region",
    "ScreenshotEngine",
    "ScreenGrabber",
    "VideoRecorder",
    "AudioDiscovery",
    "AudioDevice",
    "AudioMixer",
    "CameraStream",
    "enumerate_v4l2_capabilities",
    "select_mode_for_fps",
    "MonotonicScheduler",
    "AutoScheduler",
    "normalize_roi",
    "normalize_video_roi",
]
