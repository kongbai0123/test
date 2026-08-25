"""
tests/harness/base.py
Base test case classes with setup/teardown, isolation, and assertion helpers.
"""

import os
import sys
import time
import shutil
import signal
import tempfile
import subprocess
import unittest
from typing import Optional, List, Dict, Any, Tuple, Callable

from tests.harness.display import DisplayManager
from tests.harness.media_validator import ImageValidator, VideoValidator, AudioValidator, MediaValidator
from tests.harness.mocks import MockScreenGrabber


class BaseE2ETestCase(unittest.TestCase):
    """
    Foundational test case for opaque-box E2E testing.
    Provides isolated temporary directories, process lifecycle tracking,
    and high-level assertion helpers for media outputs.
    """

    def setUp(self):
        super().setUp()
        DisplayManager.ensure_display()
        self.temp_dir = tempfile.mkdtemp(prefix="e2e_test_")
        self._spawned_processes: List[subprocess.Popen] = []

    def tearDown(self):
        # 1. Terminate all active spawned processes cleanly
        for proc in self._spawned_processes:
            if proc.poll() is None:
                try:
                    proc.send_signal(signal.SIGINT)
                    proc.wait(timeout=1.0)
                except Exception:
                    try:
                        proc.terminate()
                        proc.wait(timeout=0.5)
                    except Exception:
                        proc.kill()
        self._spawned_processes.clear()

        # 2. Remove temporary directory
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

        super().tearDown()

    def pump_events(self, duration: float = 0.02, step: float = 0.005) -> None:
        """Pumps GUI events deterministically for a short duration."""
        end_time = time.monotonic() + duration
        while time.monotonic() < end_time:
            if hasattr(self, "root") and getattr(self, "root", None) is not None:
                DisplayManager.pump_tkinter_events(self.root, iterations=2, delay_sec=0)
            DisplayManager.pump_gtk_events(iterations=2, delay_sec=0)
            time.sleep(step)

    def wait_for_condition(
        self,
        predicate: Callable[[], bool],
        timeout: float = 4.0,
        interval: float = 0.02,
        msg: str = "Condition not met within timeout",
    ) -> None:
        """Polls predicate until True or raises AssertionError on timeout."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            self.pump_events(duration=interval, step=interval / 2)
            try:
                if predicate():
                    return
            except Exception:
                pass
            time.sleep(interval)
        if not predicate():
            raise AssertionError(f"{msg} (timeout {timeout}s)")

    def create_sample_image(
        self, filename: str, width: int = 640, height: int = 480, fmt: str = "PNG"
    ) -> str:
        path = os.path.join(self.temp_dir, filename)
        return MockScreenGrabber.save_synthetic_image(path, width=width, height=height, fmt=fmt)

    def create_sample_video(
        self,
        filename: str,
        duration: float = 1.0,
        fps: float = 30.0,
        width: int = 320,
        height: int = 240,
        fmt: str = "MP4",
    ) -> str:
        path = os.path.join(self.temp_dir, filename)
        frames = int(max(1, duration * fps))
        return MockScreenGrabber.save_synthetic_video(
            path, width=width, height=height, frames=frames, fps=fps
        )

    def launch_app_process(
        self,
        extra_args: Optional[List[str]] = None,
        env_overrides: Optional[Dict[str, str]] = None,
        wait_startup_sec: float = 0.5,
    ) -> subprocess.Popen:
        """Launches the application as a subprocess if src/main.py is available."""
        cmd = [sys.executable, "-m", "src.main"]
        if extra_args:
            cmd.extend(extra_args)

        env = os.environ.copy()
        env["DISPLAY"] = DisplayManager.get_display()
        env["RECORDING_OUTPUT_DIR"] = self.temp_dir
        if env_overrides:
            env.update(env_overrides)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")),
        )
        self._spawned_processes.append(proc)
        time.sleep(wait_startup_sec)
        return proc

    # Media assertion helpers
    def assertImageValid(
        self,
        filepath: str,
        expected_format: str = "PNG",
        min_width: int = 1,
        min_height: int = 1,
        check_non_blank: bool = True,
        msg: Optional[str] = None,
    ):
        """Asserts that a file is a valid, readable, non-empty image conforming to constraints."""
        self.assertTrue(os.path.exists(filepath), msg=f"Image file does not exist: {filepath}")
        self.assertGreater(os.path.getsize(filepath), 0, msg=f"Image file is 0 bytes: {filepath}")

        if expected_format.upper() == "PNG":
            is_valid, reason = ImageValidator.validate_png(
                filepath, min_width=min_width, min_height=min_height, check_non_blank=check_non_blank
            )
        elif expected_format.upper() in ("JPG", "JPEG"):
            is_valid, reason = ImageValidator.validate_jpg(
                filepath, min_width=min_width, min_height=min_height, check_non_blank=check_non_blank
            )
        else:
            is_valid, reason = False, f"Unsupported format: {expected_format}"

        self.assertTrue(
            is_valid, msg=f"Image validation failed for {filepath}: {reason}" + (f" ({msg})" if msg else "")
        )

    def assertVideoValid(
        self,
        filepath: str,
        expected_format: str = "MP4",
        min_duration_sec: float = 0.05,
        min_frames: int = 1,
        check_faststart: bool = False,
        check_audio: bool = False,
        msg: Optional[str] = None,
    ):
        """Asserts that a file is a valid, playable video container conforming to constraints."""
        self.assertTrue(os.path.exists(filepath), msg=f"Video file does not exist: {filepath}")
        self.assertGreater(os.path.getsize(filepath), 0, msg=f"Video file is 0 bytes: {filepath}")

        if expected_format.upper() == "MP4":
            is_valid, reason = VideoValidator.validate_mp4(
                filepath,
                min_duration_sec=min_duration_sec,
                min_frames=min_frames,
                check_faststart=check_faststart,
                check_audio=check_audio,
            )
        elif expected_format.upper() == "WEBM":
            is_valid, reason = VideoValidator.validate_webm(
                filepath, min_duration_sec=min_duration_sec, min_frames=min_frames, check_audio=check_audio
            )
        else:
            is_valid, reason = False, f"Unsupported video format: {expected_format}"

        self.assertTrue(
            is_valid, msg=f"Video validation failed for {filepath}: {reason}" + (f" ({msg})" if msg else "")
        )

    def assertAudioStreamPresent(self, filepath: str, msg: Optional[str] = None):
        """Asserts that the media file contains an active audio stream track."""
        is_valid, reason = AudioValidator.validate_audio_stream(filepath)
        self.assertTrue(
            is_valid, msg=f"Audio stream verification failed for {filepath}: {reason}" + (f" ({msg})" if msg else "")
        )


class BaseHeadlessGuiTestCase(BaseE2ETestCase):
    """
    Subclass tailored for direct in-process Tkinter/GTK GUI testing.
    Provides headless window lifecycle and simulated event injection.
    """

    def setUp(self):
        super().setUp()
        self.root = None

    def tearDown(self):
        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = None
        super().tearDown()


# Interoperable alias
BaseTestCase = BaseE2ETestCase
