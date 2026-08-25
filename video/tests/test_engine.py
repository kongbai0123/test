"""
tests/test_engine.py
Comprehensive unit and integration test suite for Milestone 1 Core Engine & Capture Backends.
Tests configuration models, screenshot engine, video recorder, audio mixer, scheduler, and CaptureEngine facade.
"""

import os
import shutil
import tempfile
import time
import unittest
from typing import List

import cv2
import numpy as np
from PIL import Image

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
from src.engine import (
    AudioDevice,
    AudioDiscovery,
    AudioMixer,
    AutoScheduler,
    CaptureEngine,
    MonotonicScheduler,
    ScreenGrabber,
    ScreenshotEngine,
    VideoRecorder,
    normalize_roi,
    normalize_video_roi,
)
from tests.harness.media_validator import ImageValidator, MediaValidator, VideoValidator


class TestConfig(unittest.TestCase):
    """Unit tests for configuration models and validations."""

    def test_default_config(self):
        cfg = CaptureConfig()
        self.assertEqual(cfg.mode, CaptureMode.MANUAL)
        self.assertIn(cfg.interval, (3.0, 5.0))
        self.assertIsNone(cfg.region)
        self.assertFalse(cfg.audio_enabled)
        self.assertEqual(cfg.audio_source, "default")
        self.assertEqual(cfg.image_format, OutputFormat.PNG)
        self.assertEqual(cfg.video_format, OutputFormat.MP4)
        self.assertEqual(cfg.fps, 30)
        self.assertEqual(cfg.jpg_quality, 90)
        self.assertTrue(cfg.nvenc_enabled)

    def test_interval_validation(self):
        # Valid boundaries
        cfg1 = CaptureConfig(interval=0.5)
        self.assertEqual(cfg1.interval, 0.5)
        cfg2 = CaptureConfig(interval=3600.0)
        self.assertEqual(cfg2.interval, 3600.0)

        # Invalid intervals
        with self.assertRaises(ValueError):
            CaptureConfig(interval=0.49)
        with self.assertRaises(ValueError):
            CaptureConfig(interval=0.0)
        with self.assertRaises(ValueError):
            CaptureConfig(interval=-1.0)
        with self.assertRaises(ValueError):
            CaptureConfig(interval=3600.1)
        with self.assertRaises(ValueError):
            CaptureConfig(interval="invalid")

    def test_region_validation(self):
        # Valid region
        reg = Region(10, 20, 300, 400)
        cfg = CaptureConfig(region=reg)
        self.assertEqual(cfg.region, reg)

        # Region from 4-tuple
        cfg2 = CaptureConfig(region=(0, 0, 100, 100))
        self.assertEqual(cfg2.region, Region(0, 0, 100, 100))

        # Negative coordinates or dimensions
        with self.assertRaises(ValueError):
            CaptureConfig(region=Region(-5, 10, 100, 100))
        with self.assertRaises(ValueError):
            CaptureConfig(region=Region(10, -5, 100, 100))
        with self.assertRaises(ValueError):
            CaptureConfig(region=Region(10, 10, 0, 100))
        with self.assertRaises(ValueError):
            CaptureConfig(region=Region(10, 10, 100, -1))

    def test_format_validation(self):
        # Image formats
        cfg_png = CaptureConfig(image_format="png")
        self.assertEqual(cfg_png.image_format, OutputFormat.PNG)
        cfg_jpg = CaptureConfig(image_format="jpeg")
        self.assertEqual(cfg_jpg.image_format, OutputFormat.JPG)

        with self.assertRaises(ValueError):
            CaptureConfig(image_format="mp4")  # Not an image format

        # Video formats
        cfg_mp4 = CaptureConfig(video_format="mp4")
        self.assertEqual(cfg_mp4.video_format, OutputFormat.MP4)
        cfg_webm = CaptureConfig(video_format="webm")
        self.assertEqual(cfg_webm.video_format, OutputFormat.WEBM)

        with self.assertRaises(ValueError):
            CaptureConfig(video_format="png")  # Not a video format

    def test_format_properties(self):
        self.assertTrue(OutputFormat.PNG.is_image)
        self.assertFalse(OutputFormat.PNG.is_video)
        self.assertEqual(OutputFormat.PNG.file_extension, ".png")
        self.assertEqual(OutputFormat.PNG.mime_type, "image/png")

        self.assertTrue(OutputFormat.MP4.is_video)
        self.assertFalse(OutputFormat.MP4.is_image)
        self.assertEqual(OutputFormat.MP4.file_extension, ".mp4")
        self.assertEqual(OutputFormat.MP4.mime_type, "video/mp4")

    def test_region_helpers(self):
        reg = Region(10, 20, 100, 200)
        self.assertEqual(reg.right, 110)
        self.assertEqual(reg.bottom, 220)
        self.assertEqual(reg.to_tuple(), (10, 20, 100, 200))
        self.assertEqual(reg.to_box(), (10, 20, 110, 220))
        self.assertEqual(reg.to_gstreamer_crop(), (10, 20, 109, 219))

        # from_points
        reg_pts = Region.from_points(110, 220, 10, 20)
        self.assertEqual(reg_pts, Region(10, 20, 100, 200))

    def test_serialization_round_trip(self):
        cfg = CaptureConfig(
            mode=CaptureMode.AUTOMATIC,
            interval=2.5,
            region=Region(50, 60, 400, 300),
            audio_enabled=True,
            audio_source="hw:1,0",
            image_format=OutputFormat.JPG,
            video_format=OutputFormat.WEBM,
            fps=60,
            jpg_quality=80,
            nvenc_enabled=False,
        )
        d = cfg.to_dict()
        cfg_restored = CaptureConfig.from_dict(d)
        self.assertEqual(cfg, cfg_restored)


class TestScreenshotEngine(unittest.TestCase):
    """Unit and integration tests for screenshot engine and fallback backends."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_screenshots_")
        self.engine = ScreenshotEngine()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_screen_size(self):
        w, h = self.engine.get_screen_size()
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_normalize_roi(self):
        # Full screen None
        self.assertEqual(normalize_roi(None, 1920, 1080), (0, 0, 1920, 1080))
        # Standard inside bounds
        self.assertEqual(normalize_roi(Region(10, 20, 100, 200), 1920, 1080), (10, 20, 100, 200))
        # Inverted drag
        self.assertEqual(normalize_roi(Region(110, 220, -100, -200), 1920, 1080), (10, 20, 100, 200))
        # Out of bounds clamping
        x, y, w, h = normalize_roi(Region(1900, 1000, 100, 100), 1920, 1080)
        self.assertEqual(x, 1900)
        self.assertEqual(y, 1000)
        self.assertEqual(w, 20)
        self.assertEqual(h, 80)

    def test_capture_fullscreen_png(self):
        path = self.engine.capture_to_file(self.test_dir, region=None, image_format=OutputFormat.PNG)
        self.assertTrue(os.path.exists(path))
        valid, msg = ImageValidator.validate_png(path)
        self.assertTrue(valid, f"PNG validation failed: {msg}")

    def test_capture_fullscreen_jpg(self):
        path = self.engine.capture_to_file(self.test_dir, region=None, image_format=OutputFormat.JPG, quality=85)
        self.assertTrue(os.path.exists(path))
        valid, msg = ImageValidator.validate_jpg(path)
        self.assertTrue(valid, f"JPG validation failed: {msg}")

    def test_capture_roi_png(self):
        roi = Region(50, 50, 320, 240)
        path = self.engine.capture_to_file(self.test_dir, region=roi, image_format=OutputFormat.PNG)
        self.assertTrue(os.path.exists(path))
        with Image.open(path) as img:
            self.assertEqual(img.size, (320, 240))
        valid, msg = ImageValidator.validate_png(path)
        self.assertTrue(valid, msg)

    def test_capture_roi_jpg(self):
        roi = Region(100, 100, 200, 150)
        path = self.engine.capture_to_file(self.test_dir, region=roi, image_format=OutputFormat.JPG)
        self.assertTrue(os.path.exists(path))
        with Image.open(path) as img:
            self.assertEqual(img.size, (200, 150))
        valid, msg = ImageValidator.validate_jpg(path)
        self.assertTrue(valid, msg)

    def test_x11_fallback_backend(self):
        img = self.engine._grab_x11(10, 10, 100, 100)
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (100, 100))

    def test_pil_fallback_backend(self):
        img = self.engine._grab_pil(10, 10, 100, 100)
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (100, 100))

    def test_collision_safe_filenames(self):
        p1 = self.engine.capture_to_file(self.test_dir, image_format=OutputFormat.PNG)
        p2 = self.engine.capture_to_file(self.test_dir, image_format=OutputFormat.PNG)
        self.assertNotEqual(p1, p2)
        self.assertTrue(os.path.exists(p1))
        self.assertTrue(os.path.exists(p2))


class TestAudioSubsystem(unittest.TestCase):
    """Unit tests for audio discovery and pipeline branches."""

    def test_device_discovery(self):
        devs = AudioDiscovery.get_all_devices()
        self.assertGreater(len(devs), 0)
        # Verify default device presence
        default_dev = AudioDiscovery.get_default_device()
        self.assertIsNotNone(default_dev)
        self.assertTrue(default_dev.is_default)

    def test_resolve_audio_source(self):
        src_default = AudioDiscovery.resolve_audio_source("default")
        self.assertTrue(
            src_default.startswith("pulsesrc")
            or src_default.startswith("alsasrc")
            or "audiotestsrc" in src_default,
            f"Unexpected resolved audio source: {src_default}",
        )

        src_silence = AudioDiscovery.resolve_audio_source("silence")
        self.assertEqual(src_silence, "audiotestsrc is-live=true wave=silence")

    def test_audio_mixer_mp4_branch(self):
        branch = AudioMixer.build_audio_branch("default", "mp4")
        self.assertIn("mux.audio_0", branch)
        self.assertTrue("voaacenc" in branch or "avenc_aac" in branch or "lamemp3enc" in branch)

    def test_audio_mixer_webm_branch(self):
        branch = AudioMixer.build_audio_branch("default", "webm")
        self.assertIn("mux.audio_0", branch)
        self.assertTrue("opusenc" in branch or "vorbisenc" in branch)


class TestVideoRecorder(unittest.TestCase):
    """Integration tests for video recording, pause/resume, and container validation."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_recorder_")
        self.recorder = VideoRecorder()

    def tearDown(self):
        if self.recorder.status != EngineStatus.IDLE:
            try:
                self.recorder.stop()
            except Exception:
                pass
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_normalize_video_roi(self):
        # Odd dimensions must become even
        x, y, w, h = normalize_video_roi(Region(11, 13, 321, 241), 1920, 1080)
        self.assertEqual(w % 2, 0)
        self.assertEqual(h % 2, 0)
        self.assertEqual(w, 320)
        self.assertEqual(h, 240)

        # Out of bounds clamping
        x2, y2, w2, h2 = normalize_video_roi(Region(1900, 1000, 100, 100), 1920, 1080)
        self.assertEqual(w2 % 2, 0)
        self.assertEqual(h2 % 2, 0)
        self.assertLessEqual(x2 + w2, 1920)
        self.assertLessEqual(y2 + h2, 1080)

    def test_mp4_recording_with_faststart(self):
        cfg = CaptureConfig(
            video_format=OutputFormat.MP4,
            region=Region(0, 0, 320, 240),
            output_dir=self.test_dir,
        )
        self.recorder.start_recording(cfg)
        self.assertTrue(self.recorder.is_recording())
        time.sleep(1.0)
        filepath = self.recorder.stop_recording()

        self.assertEqual(self.recorder.status, EngineStatus.IDLE)
        self.assertTrue(os.path.exists(filepath))

        valid, msg = VideoValidator.validate_mp4(filepath, check_faststart=True)
        self.assertTrue(valid, f"MP4 faststart validation failed: {msg}")

        # Check OpenCV decodability and resolution
        cap = cv2.VideoCapture(filepath)
        self.assertTrue(cap.isOpened())
        self.assertEqual(int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), 320)
        self.assertEqual(int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), 240)
        cap.release()

    def test_webm_recording(self):
        cfg = CaptureConfig(
            video_format=OutputFormat.WEBM,
            region=Region(0, 0, 320, 240),
            output_dir=self.test_dir,
        )
        self.recorder.start_recording(cfg)
        time.sleep(1.0)
        filepath = self.recorder.stop_recording()

        self.assertTrue(os.path.exists(filepath))
        valid, msg = VideoValidator.validate_webm(filepath)
        self.assertTrue(valid, f"WebM validation failed: {msg}")

    def test_pause_resume_lifecycle(self):
        cfg = CaptureConfig(
            video_format=OutputFormat.MP4,
            region=Region(0, 0, 320, 240),
            output_dir=self.test_dir,
        )
        self.recorder.start_recording(cfg)
        time.sleep(0.6)

        # Pause
        self.recorder.pause_recording()
        self.assertTrue(self.recorder.is_paused())
        elapsed_at_pause = self.recorder.get_elapsed_seconds()
        time.sleep(0.4)
        elapsed_during_pause = self.recorder.get_elapsed_seconds()
        self.assertAlmostEqual(elapsed_at_pause, elapsed_during_pause, delta=0.05)

        # Resume
        self.recorder.resume_recording()
        self.assertTrue(self.recorder.is_recording())
        time.sleep(0.6)

        filepath = self.recorder.stop_recording()
        self.assertTrue(os.path.exists(filepath))
        valid, msg = VideoValidator.validate_mp4(filepath, check_faststart=True)
        self.assertTrue(valid, f"Pause/Resume MP4 validation failed: {msg}")

    def test_audio_muxing_recording(self):
        cfg = CaptureConfig(
            video_format=OutputFormat.MP4,
            audio_enabled=True,
            region=Region(0, 0, 320, 240),
            output_dir=self.test_dir,
        )
        self.recorder.start_recording(cfg)
        time.sleep(1.0)
        filepath = self.recorder.stop_recording()

        self.assertTrue(os.path.exists(filepath))
        valid, msg = MediaValidator.validate_video(filepath, check_audio=True)
        self.assertTrue(valid, f"Audio MP4 validation failed: {msg}")

    def test_illegal_state_transitions(self):
        # Pause on IDLE
        with self.assertRaises(RuntimeError):
            self.recorder.pause_recording()

        # Stop on IDLE
        with self.assertRaises(RuntimeError):
            self.recorder.stop_recording()

        # Resume on IDLE
        with self.assertRaises(RuntimeError):
            self.recorder.resume_recording()


class TestMonotonicScheduler(unittest.TestCase):
    """Unit tests for drift-free monotonic periodic scheduler."""

    def test_sub_millisecond_drift(self):
        scheduler = MonotonicScheduler()
        drifts: List[float] = []

        def tick(t, drift):
            drifts.append(drift)

        scheduler.start(0.5, tick)
        time.sleep(2.6)
        scheduler.stop()

        self.assertEqual(len(drifts), 5)
        for i, d in enumerate(drifts):
            self.assertLess(abs(d), 0.020, f"Tick {i+1} drift {d*1000}ms exceeded threshold")

        avg_drift_ms = (sum(abs(d) for d in drifts) / len(drifts)) * 1000
        self.assertLess(avg_drift_ms, 1.0, f"Average drift {avg_drift_ms}ms must be < 1.0ms")

    def test_dynamic_interval(self):
        scheduler = MonotonicScheduler()
        scheduler.start(0.5, lambda: None)
        scheduler.set_interval(2.0)
        self.assertEqual(scheduler.interval, 2.0)
        scheduler.stop()

    def test_error_isolation(self):
        scheduler = MonotonicScheduler()
        errors = []

        def bad_job():
            raise ValueError("Deliberate tick error")

        scheduler.start(0.5, bad_job, on_error=lambda e: errors.append(e))
        time.sleep(1.2)
        scheduler.stop()

        self.assertGreaterEqual(len(errors), 2)


class TestCaptureEngineFacade(unittest.TestCase):
    """Integration tests for the unified CaptureEngine facade."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_engine_facade_")
        self.config = CaptureConfig(output_dir=self.test_dir)
        self.engine = CaptureEngine(self.config)

    def tearDown(self):
        self.engine.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_initial_status(self):
        self.assertEqual(self.engine.get_status(), EngineStatus.IDLE)

    def test_status_listener_flow(self):
        history = []
        self.engine.add_status_listener(lambda s: history.append(s))

        self.engine.start_recording()
        self.assertEqual(self.engine.get_status(), EngineStatus.RECORDING)

        self.engine.pause_recording()
        self.assertEqual(self.engine.get_status(), EngineStatus.PAUSED)

        self.engine.resume_recording()
        self.assertEqual(self.engine.get_status(), EngineStatus.RECORDING)

        self.engine.stop_recording()
        self.assertEqual(self.engine.get_status(), EngineStatus.IDLE)

        self.assertEqual(
            history,
            [
                EngineStatus.RECORDING,
                EngineStatus.PAUSED,
                EngineStatus.RECORDING,
                EngineStatus.IDLE,
            ],
        )

    def test_capture_screenshot(self):
        path = self.engine.capture_screenshot()
        self.assertTrue(os.path.exists(path))
        valid, msg = ImageValidator.validate_png(path)
        self.assertTrue(valid, msg)

    def test_auto_mode_capture(self):
        captured_files = []

        def on_capture(fpath):
            captured_files.append(fpath)

        self.engine.start_auto_mode(interval=0.5, callback=on_capture)
        self.assertEqual(self.engine.get_status(), EngineStatus.AUTO_ACTIVE)
        time.sleep(1.6)
        self.engine.stop_auto_mode()
        self.assertEqual(self.engine.get_status(), EngineStatus.IDLE)

        self.assertGreaterEqual(len(captured_files), 2)
        for p in captured_files:
            self.assertTrue(os.path.exists(p))
            valid, msg = ImageValidator.validate_png(p)
            self.assertTrue(valid, msg)

    def test_manual_screenshot_during_auto_mode(self):
        captured_files = []
        self.engine.start_auto_mode(interval=0.5, callback=lambda p: captured_files.append(p))

        # Trigger manual screenshot while auto mode is ticking
        manual_path = self.engine.capture_screenshot()
        self.assertTrue(os.path.exists(manual_path))

        time.sleep(1.2)
        self.engine.stop_auto_mode()

        self.assertGreaterEqual(len(captured_files), 2)
        self.assertNotIn(manual_path, captured_files)

    def test_illegal_state_actions(self):
        # Cannot start auto mode while recording
        self.engine.start_recording()
        with self.assertRaises(RuntimeError):
            self.engine.start_auto_mode(1.0, lambda p: None)

        # Cannot start recording while auto mode is active
        self.engine.stop_recording()
        self.engine.start_auto_mode(1.0, lambda p: None)
        with self.assertRaises(RuntimeError):
            self.engine.start_recording()
        self.engine.stop_auto_mode()


if __name__ == "__main__":
    unittest.main()
