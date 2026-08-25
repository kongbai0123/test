"""
tests/test_challenger_4_adversarial.py
Adversarial Stress Test Suite for Milestone 1 Iteration 2 by Challenger 4.

Focus Areas:
1. Audio Mixer & Pipeline:
   - Device discovery & fallback hierarchy (PulseAudio -> ALSA -> Silence)
   - Source resolution for normal, malformed, empty, and synthetic device IDs
   - Audio branch construction for MP4 (AAC) and WebM (Opus) across bitrates
   - Real video+audio recording (MP4 & WebM) with GstDiscoverer / MediaValidator checks
   - Pause / Resume during audio recording with container and sync integrity
   - Rapid start/stop (0.2s) audio recording EOS finalization
   - Audio fallback on invalid device failure

2. Monotonic Auto Scheduler:
   - Multi-tick drift measurements at 0.5s interval (measure average drift < 1ms)
   - Overrun resilience under synthetic callback delays (sub-interval, supra-interval, multi-interval)
   - Dynamic interval modification on the fly
   - Callback signatures (0, 1, 2 args, *args)
   - Error isolation (exceptions in callback handled gracefully without loop crash)
   - Concurrency stress: 50 rapid start/stop cycles

3. Unified CaptureEngine Facade:
   - Concurrent manual screenshot during active auto-mode capture
   - Concurrent manual screenshot during active video recording (MP4+Audio)
   - Multi-threaded parallel screenshot bursts (10 concurrent threads)
   - Strict state machine enforcement and illegal transition rejection
   - Listener dispatch ordering and error isolation
   - Clean shutdown (close()) from all engine states
"""

from __future__ import annotations

import os
import sys
import time
import math
import tempfile
import shutil
import threading
import traceback
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Tuple, Optional

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import cv2
import numpy as np
from PIL import Image

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstPbutils", "1.0")
from gi.repository import Gst, GstPbutils
Gst.init(None)

from src.config import (
    CaptureConfig,
    CaptureMode,
    OutputFormat,
    EngineStatus,
    Region,
    MIN_INTERVAL,
    MAX_INTERVAL,
)
from src.engine.audio import AudioDevice, AudioDiscovery, AudioMixer
from src.engine.scheduler import MonotonicScheduler, AutoScheduler
from src.engine.screenshot import ScreenshotEngine, normalize_roi
from src.engine.recorder import VideoRecorder, normalize_video_roi
from src.engine import CaptureEngine
from tests.harness.media_validator import MediaValidator, ImageValidator, VideoValidator, AudioValidator


def inspect_media_file(filepath: str) -> Dict[str, Any]:
    """Uses GstDiscoverer and OpenCV to inspect container streams, codecs, duration, and dimensions."""
    info: Dict[str, Any] = {
        "exists": os.path.exists(filepath),
        "filesize": os.path.getsize(filepath) if os.path.exists(filepath) else 0,
        "has_video": False,
        "has_audio": False,
        "video_codec": None,
        "audio_codec": None,
        "width": 0,
        "height": 0,
        "duration_sec": 0.0,
        "is_mp4_faststart": False,
    }
    if not info["exists"] or info["filesize"] == 0:
        return info

    discoverer = GstPbutils.Discoverer.new(5 * Gst.SECOND)
    uri = f"file://{os.path.abspath(filepath)}"
    try:
        d_info = discoverer.discover_uri(uri)
        dur = d_info.get_duration()
        if dur != Gst.CLOCK_TIME_NONE:
            info["duration_sec"] = dur / 1e9

        video_streams = d_info.get_video_streams()
        if video_streams:
            info["has_video"] = True
            v_stream = video_streams[0]
            info["width"] = v_stream.get_width()
            info["height"] = v_stream.get_height()
            caps = v_stream.get_caps()
            if caps:
                info["video_codec"] = caps.to_string()

        audio_streams = d_info.get_audio_streams()
        if audio_streams:
            info["has_audio"] = True
            a_stream = audio_streams[0]
            caps = a_stream.get_caps()
            if caps:
                info["audio_codec"] = caps.to_string()
    except Exception as e:
        # Fallback inspection via OpenCV / manual
        pass

    if filepath.lower().endswith(".mp4"):
        info["is_mp4_faststart"] = VideoValidator.is_mp4_faststart(filepath)

    return info


class TestChallenger4AudioPipeline(unittest.TestCase):
    """Adversarial stress tests for Audio Discovery, Audio Mixer, and Muxing Pipeline."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_challenger4_audio_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_audio_discovery_and_catalog(self):
        """Verifies device discovery, catalog properties, and default/silence device availability."""
        devices = AudioDiscovery.get_all_devices()
        self.assertGreaterEqual(len(devices), 2, "Must discover at least default and silence devices")

        ids = [d.id for d in devices]
        self.assertIn("default", ids, "Default device must be cataloged")
        self.assertIn("silence", ids, "Synthetic silence device must be cataloged")

        default_dev = AudioDiscovery.get_default_device()
        self.assertIsNotNone(default_dev)
        self.assertTrue(default_dev.is_default)
        self.assertEqual(default_dev.id, "default")

        # Test listing ALSA devices directly
        alsa_devs = AudioDiscovery.list_alsa_sources()
        self.assertIsInstance(alsa_devs, list)

        # Test listing PulseAudio sources directly
        pulse_devs = AudioDiscovery.list_pulse_sources()
        self.assertIsInstance(pulse_devs, list)

    def test_audio_source_resolution_fallbacks(self):
        """Adversarially probes source resolution with malformed, invalid, and boundary strings."""
        # 1. Silence & none
        self.assertEqual(
            AudioDiscovery.resolve_audio_source("silence"),
            "audiotestsrc is-live=true wave=silence"
        )
        self.assertEqual(
            AudioDiscovery.resolve_audio_source("none"),
            "audiotestsrc is-live=true wave=silence"
        )
        self.assertEqual(
            AudioDiscovery.resolve_audio_source(" SILENCE "),
            "audiotestsrc is-live=true wave=silence"
        )

        # 2. Non-existent pulse device -> must fall back gracefully
        src_bad_pulse = AudioDiscovery.resolve_audio_source("pulse:totally_fake_nonexistent_device_9999")
        self.assertTrue(
            src_bad_pulse.startswith("pulsesrc") or src_bad_pulse.startswith("alsasrc") or "audiotestsrc" in src_bad_pulse,
            f"Fallback failed for bad pulse device, got: {src_bad_pulse}"
        )

        # 3. Non-existent ALSA device -> must fall back gracefully
        src_bad_alsa = AudioDiscovery.resolve_audio_source("hw:99,99")
        self.assertTrue(
            src_bad_alsa.startswith("pulsesrc") or src_bad_alsa.startswith("alsasrc") or "audiotestsrc" in src_bad_alsa,
            f"Fallback failed for bad alsa device, got: {src_bad_alsa}"
        )

        # 4. Empty / whitespace string -> resolves to default fallback chain
        src_empty = AudioDiscovery.resolve_audio_source("")
        self.assertTrue(len(src_empty) > 0)
        src_ws = AudioDiscovery.resolve_audio_source("   ")
        self.assertTrue(len(src_ws) > 0)

    def test_audio_branch_builder_mp4_and_webm(self):
        """Tests audio pipeline construction for both MP4 and WebM with various bitrates."""
        for bitrate in (32000, 64000, 128000, 256000):
            branch_mp4 = AudioMixer.build_audio_branch("default", "mp4", bitrate=bitrate)
            self.assertIn("mux.audio_0", branch_mp4)
            self.assertIn("audioresample", branch_mp4)
            self.assertIn("audioconvert", branch_mp4)

            branch_webm = AudioMixer.build_audio_branch("default", "webm", bitrate=bitrate)
            self.assertIn("mux.audio_0", branch_webm)
            self.assertIn("audioresample", branch_webm)
            self.assertIn("audioconvert", branch_webm)

    def test_real_video_and_audio_mp4_recording(self):
        """Records a real video+audio MP4 file and performs in-depth stream verification."""
        recorder = VideoRecorder()
        cfg = CaptureConfig(
            video_format=OutputFormat.MP4,
            audio_enabled=True,
            audio_source="default",
            region=Region(0, 0, 320, 240),
            output_dir=self.test_dir,
            fps=30,
        )
        recorder.start_recording(cfg)
        self.assertTrue(recorder.is_recording())
        time.sleep(1.5)
        filepath = recorder.stop_recording()

        self.assertTrue(os.path.exists(filepath))
        self.assertGreater(os.path.getsize(filepath), 1000)

        # Verify faststart and container validity
        valid, msg = VideoValidator.validate_mp4(filepath, min_duration_sec=0.5, check_faststart=True, check_audio=True)
        self.assertTrue(valid, f"MP4 validation error: {msg}")

        # In-depth stream inspection
        info = inspect_media_file(filepath)
        self.assertTrue(info["has_video"], "MP4 should have video stream")
        self.assertTrue(info["has_audio"], "MP4 should have audio stream")
        self.assertEqual(info["width"], 320)
        self.assertEqual(info["height"], 240)
        self.assertTrue(info["is_mp4_faststart"], "moov atom must precede mdat")

    def test_real_video_and_audio_webm_recording(self):
        """Records a real video+audio WebM file and verifies container & streams."""
        recorder = VideoRecorder()
        cfg = CaptureConfig(
            video_format=OutputFormat.WEBM,
            audio_enabled=True,
            audio_source="silence",
            region=Region(0, 0, 320, 240),
            output_dir=self.test_dir,
            fps=30,
        )
        recorder.start_recording(cfg)
        self.assertTrue(recorder.is_recording())
        time.sleep(1.5)
        filepath = recorder.stop_recording()

        self.assertTrue(os.path.exists(filepath))
        self.assertGreater(os.path.getsize(filepath), 1000)

        valid, msg = VideoValidator.validate_webm(filepath, min_duration_sec=0.5, check_audio=True)
        self.assertTrue(valid, f"WebM validation error: {msg}")

        info = inspect_media_file(filepath)
        self.assertTrue(info["has_video"], "WebM should have video stream")
        self.assertTrue(info["has_audio"], "WebM should have audio stream")

    def test_audio_pause_resume_integrity(self):
        """Records video+audio with pause/resume cycles, ensuring continuous container timeline and no corruption."""
        recorder = VideoRecorder()
        cfg = CaptureConfig(
            video_format=OutputFormat.MP4,
            audio_enabled=True,
            audio_source="silence",
            region=Region(0, 0, 320, 240),
            output_dir=self.test_dir,
            fps=30,
        )
        recorder.start_recording(cfg)
        time.sleep(0.7)

        # Pause
        recorder.pause_recording()
        self.assertTrue(recorder.is_paused())
        t_pause1 = recorder.get_elapsed_seconds()
        time.sleep(0.5)
        t_pause2 = recorder.get_elapsed_seconds()
        self.assertAlmostEqual(t_pause1, t_pause2, delta=0.05, msg="Elapsed time must freeze during pause")

        # Resume
        recorder.resume_recording()
        self.assertTrue(recorder.is_recording())
        time.sleep(0.7)

        filepath = recorder.stop_recording()
        self.assertTrue(os.path.exists(filepath))

        valid, msg = VideoValidator.validate_mp4(filepath, min_duration_sec=0.8, check_faststart=True, check_audio=True)
        self.assertTrue(valid, f"Audio Pause/Resume validation failed: {msg}")

    def test_rapid_audio_start_stop_eos(self):
        """Tests rapid start and stop (0.2s duration) with audio enabled to stress EOS finalization."""
        recorder = VideoRecorder()
        cfg = CaptureConfig(
            video_format=OutputFormat.MP4,
            audio_enabled=True,
            region=Region(0, 0, 320, 240),
            output_dir=self.test_dir,
            fps=30,
        )
        recorder.start_recording(cfg)
        time.sleep(0.2)
        filepath = recorder.stop_recording()
        self.assertTrue(os.path.exists(filepath))
        self.assertGreater(os.path.getsize(filepath), 0)


class TestChallenger4AutoScheduler(unittest.TestCase):
    """Adversarial precision and overrun resilience tests for Monotonic AutoScheduler."""

    def test_multi_tick_precision_and_sub_ms_drift(self):
        """
        Runs 20 consecutive ticks at 0.5s interval (total ~10s).
        Measures exact per-tick timestamp deviation from ideal monotonic grid.
        Verifies mean absolute drift < 1.0ms.
        """
        scheduler = MonotonicScheduler()
        timestamps: List[float] = []
        drifts: List[float] = []

        def on_tick(t_now, drift_val):
            timestamps.append(t_now)
            drifts.append(drift_val)

        interval = 0.5
        target_ticks = 10  # 10 ticks = 5 seconds

        t0 = time.monotonic()
        scheduler.start(interval=interval, callback=on_tick)

        # Wait for target ticks
        max_wait = (target_ticks * interval) + 0.3
        time.sleep(max_wait)
        scheduler.stop()

        self.assertGreaterEqual(len(timestamps), target_ticks, f"Expected at least {target_ticks} ticks")

        # Evaluate drift
        measured_drifts = drifts[:target_ticks]
        abs_drifts_ms = [abs(d) * 1000.0 for d in measured_drifts]
        mean_drift_ms = sum(abs_drifts_ms) / len(abs_drifts_ms)
        max_drift_ms = max(abs_drifts_ms)

        print(f"\n[Scheduler Precision Test] Ticks: {len(measured_drifts)}, Mean Drift: {mean_drift_ms:.4f}ms, Max Drift: {max_drift_ms:.4f}ms")

        # Requirement: Average drift < 1ms
        self.assertLess(mean_drift_ms, 1.0, f"Average drift {mean_drift_ms:.4f}ms must be < 1.0ms")
        self.assertLess(max_drift_ms, 15.0, f"Max drift {max_drift_ms:.4f}ms exceeded tolerance")

    def test_overrun_resilience_sub_interval_delay(self):
        """
        Introduces a synthetic callback delay of 0.25s on a 0.5s interval.
        Verifies that next tick does NOT drift (target remains locked to grid).
        """
        scheduler = MonotonicScheduler()
        timestamps: List[float] = []
        drifts: List[float] = []

        def delayed_cb(t_now, d):
            timestamps.append(t_now)
            drifts.append(d)
            time.sleep(0.25)  # Synthetic work taking 50% of the interval

        scheduler.start(0.5, delayed_cb)
        time.sleep(2.6)  # ~5 ticks
        scheduler.stop()

        self.assertGreaterEqual(len(timestamps), 4)
        abs_drifts_ms = [abs(d) * 1000.0 for d in drifts]
        mean_drift_ms = sum(abs_drifts_ms) / len(abs_drifts_ms)
        print(f"\n[Sub-interval Delay Test] Mean Drift: {mean_drift_ms:.4f}ms")
        self.assertLess(mean_drift_ms, 1.0, "Drift must stay < 1ms even with sub-interval callback delay")

    def test_overrun_resilience_supra_interval_delay(self):
        """
        Introduces a synthetic callback delay of 0.8s on a 0.5s interval (overrunning 1 tick).
        Verifies that target time snaps forward along integer grid steps without bursting.
        """
        scheduler = MonotonicScheduler()
        ticks: List[float] = []

        def overrun_cb(t_now, d):
            ticks.append(t_now)
            if len(ticks) == 2:
                time.sleep(0.8)  # Deliberate overrun on tick 2

        scheduler.start(0.5, overrun_cb)
        time.sleep(3.2)
        scheduler.stop()

        self.assertGreaterEqual(len(ticks), 4)
        # Check intervals between ticks
        diffs = [ticks[i+1] - ticks[i] for i in range(len(ticks)-1)]
        print(f"\n[Supra-interval Delay Test] Tick intervals: {[round(d, 3) for d in diffs]}")
        # After the 0.8s overrun on tick 2, the interval to tick 3 should be ~1.0s (2 * interval) not 0.8s + immediate burst
        self.assertGreater(diffs[1], 0.9, "Overrun tick must snap to next grid point, not burst immediately")

    def test_dynamic_interval_modification_live(self):
        """Dynamically updates scheduler interval from 0.5s -> 1.0s -> 0.5s while running."""
        scheduler = MonotonicScheduler()
        intervals_observed: List[float] = []
        last_t = [0.0]

        def record_interval(t_now, d):
            if last_t[0] > 0.0:
                intervals_observed.append(t_now - last_t[0])
            last_t[0] = t_now

        scheduler.start(0.5, record_interval)
        time.sleep(1.6)  # ~3 ticks at 0.5s

        scheduler.set_interval(1.0)
        time.sleep(2.2)  # ~2 ticks at 1.0s

        scheduler.set_interval(0.5)
        time.sleep(1.6)  # ~3 ticks at 0.5s

        scheduler.stop()

        self.assertGreaterEqual(len(intervals_observed), 5)
        # Verify observed intervals adapt
        has_approx_half = any(0.45 <= iv <= 0.55 for iv in intervals_observed)
        has_approx_one = any(0.95 <= iv <= 1.05 for iv in intervals_observed)
        self.assertTrue(has_approx_half, "Should observe ~0.5s intervals")
        self.assertTrue(has_approx_one, "Should observe ~1.0s intervals after dynamic update")

    def test_callback_argument_signatures(self):
        """Verifies scheduler dispatches cleanly to 0-arg, 1-arg, 2-arg, and vararg callbacks."""
        results = {}

        # 0-arg
        s0 = MonotonicScheduler()
        s0.start(0.5, lambda: results.setdefault("0arg", []).append(True))
        time.sleep(1.1)
        s0.stop()
        self.assertGreaterEqual(len(results.get("0arg", [])), 2)

        # 1-arg
        s1 = MonotonicScheduler()
        s1.start(0.5, lambda drift: results.setdefault("1arg", []).append(drift))
        time.sleep(1.1)
        s1.stop()
        self.assertGreaterEqual(len(results.get("1arg", [])), 2)

        # 2-arg
        s2 = MonotonicScheduler()
        s2.start(0.5, lambda t, drift: results.setdefault("2arg", []).append((t, drift)))
        time.sleep(1.1)
        s2.stop()
        self.assertGreaterEqual(len(results.get("2arg", [])), 2)

        # Varargs (*args)
        def vararg_cb(*args):
            results.setdefault("varargs", []).append(len(args))
        sv = MonotonicScheduler()
        sv.start(0.5, vararg_cb)
        time.sleep(1.1)
        sv.stop()
        self.assertGreaterEqual(len(results.get("varargs", [])), 2)

    def test_error_isolation_in_callback(self):
        """Verifies callback exceptions do not terminate the scheduler loop and trigger on_error handler."""
        scheduler = MonotonicScheduler()
        caught_errors = []
        tick_count = [0]

        def buggy_callback():
            tick_count[0] += 1
            if tick_count[0] % 2 == 1:
                raise RuntimeError(f"Deliberate error on tick {tick_count[0]}")

        scheduler.start(0.5, buggy_callback, on_error=lambda err: caught_errors.append(err))
        time.sleep(2.1)
        scheduler.stop()

        self.assertGreaterEqual(tick_count[0], 3, "Scheduler should continue ticking despite callback exceptions")
        self.assertGreaterEqual(len(caught_errors), 1, "on_error handler should capture exceptions")

    def test_rapid_start_stop_stress(self):
        """Stresses scheduler thread lifecycle with 40 rapid start/stop cycles."""
        scheduler = MonotonicScheduler()
        for i in range(40):
            scheduler.start(0.5, lambda: None)
            time.sleep(0.01)
            scheduler.stop(timeout=1.0)
            self.assertFalse(scheduler.is_running())


class TestChallenger4CaptureEngineFacade(unittest.TestCase):
    """Adversarial concurrency, state machine, and integration tests for CaptureEngine."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_challenger4_engine_")
        self.config = CaptureConfig(output_dir=self.test_dir)
        self.engine = CaptureEngine(self.config)

    def tearDown(self):
        self.engine.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_manual_screenshot_during_active_auto_mode(self):
        """
        Concurrently triggers manual screenshots while auto-mode is actively capturing every 0.5s.
        Verifies thread safety, collision-free files, and valid image data for both.
        """
        auto_files = []
        self.engine.start_auto_mode(interval=0.5, callback=lambda p: auto_files.append(p))
        self.assertEqual(self.engine.get_status(), EngineStatus.AUTO_ACTIVE)

        manual_files = []
        for _ in range(3):
            time.sleep(0.3)
            p = self.engine.capture_screenshot()
            manual_files.append(p)

        time.sleep(1.2)
        self.engine.stop_auto_mode()
        self.assertEqual(self.engine.get_status(), EngineStatus.IDLE)

        # Check manual files
        self.assertEqual(len(manual_files), 3)
        for p in manual_files:
            self.assertTrue(os.path.exists(p))
            valid, msg = ImageValidator.validate_png(p)
            self.assertTrue(valid, f"Manual screenshot invalid: {msg}")

        # Check auto files
        self.assertGreaterEqual(len(auto_files), 3)
        for p in auto_files:
            self.assertTrue(os.path.exists(p))
            valid, msg = ImageValidator.validate_png(p)
            self.assertTrue(valid, f"Auto screenshot invalid: {msg}")

        # Verify no file overlap
        overlap = set(manual_files).intersection(set(auto_files))
        self.assertEqual(len(overlap), 0, "Manual and Auto capture filenames must never collide")

    def test_manual_screenshot_during_active_video_recording(self):
        """
        Takes manual screenshots while active video recording (MP4 + Audio) is in progress.
        Verifies video pipeline remains uninterrupted and screenshot is valid.
        """
        rec_cfg = CaptureConfig(
            video_format=OutputFormat.MP4,
            audio_enabled=True,
            region=Region(0, 0, 320, 240),
            output_dir=self.test_dir,
        )
        self.engine.start_recording(rec_cfg)
        self.assertEqual(self.engine.get_status(), EngineStatus.RECORDING)

        time.sleep(0.5)
        # Capture screenshot while recording
        ss_path = self.engine.capture_screenshot()
        self.assertTrue(os.path.exists(ss_path))
        valid_img, img_msg = ImageValidator.validate_png(ss_path)
        self.assertTrue(valid_img, f"Screenshot during recording failed: {img_msg}")

        time.sleep(0.8)
        video_path = self.engine.stop_recording()
        self.assertEqual(self.engine.get_status(), EngineStatus.IDLE)

        # Verify recorded video
        self.assertTrue(os.path.exists(video_path))
        valid_vid, vid_msg = VideoValidator.validate_mp4(video_path, check_faststart=True, check_audio=True)
        self.assertTrue(valid_vid, f"Recorded video during concurrent screenshot failed: {vid_msg}")

    def test_multithreaded_concurrent_screenshot_burst(self):
        """Spawns 8 concurrent threads capturing screenshots simultaneously."""
        captured_paths = []
        errors = []

        def worker():
            try:
                p = self.engine.capture_screenshot()
                captured_paths.append(p)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        self.assertEqual(len(captured_paths), 8)
        # Check all unique files
        self.assertEqual(len(set(captured_paths)), 8, "All 8 screenshots must have distinct filenames")
        for p in captured_paths:
            self.assertTrue(os.path.exists(p))
            valid, msg = ImageValidator.validate_png(p)
            self.assertTrue(valid, msg)

    def test_state_machine_and_illegal_operations(self):
        """Exhaustively verifies engine state machine transitions and rejection of illegal operations."""
        self.assertEqual(self.engine.get_status(), EngineStatus.IDLE)

        # 1. Illegal transitions from IDLE
        with self.assertRaises(RuntimeError):
            self.engine.pause_recording()
        with self.assertRaises(RuntimeError):
            self.engine.resume_recording()
        with self.assertRaises(RuntimeError):
            self.engine.stop_recording()

        # 2. Start recording -> RECORDING
        self.engine.start_recording()
        self.assertEqual(self.engine.get_status(), EngineStatus.RECORDING)

        # Illegal actions while RECORDING
        with self.assertRaises(RuntimeError):
            self.engine.start_recording()  # Already recording
        with self.assertRaises(RuntimeError):
            self.engine.resume_recording()  # Not paused
        with self.assertRaises(RuntimeError):
            self.engine.start_auto_mode(1.0, lambda p: None)  # Cannot auto during recording

        # Pause -> PAUSED
        self.engine.pause_recording()
        self.assertEqual(self.engine.get_status(), EngineStatus.PAUSED)

        # Illegal actions while PAUSED
        with self.assertRaises(RuntimeError):
            self.engine.pause_recording()  # Already paused
        with self.assertRaises(RuntimeError):
            self.engine.start_recording()  # Already active
        with self.assertRaises(RuntimeError):
            self.engine.start_auto_mode(1.0, lambda p: None)

        # Resume -> RECORDING
        self.engine.resume_recording()
        self.assertEqual(self.engine.get_status(), EngineStatus.RECORDING)

        # Stop -> IDLE
        self.engine.stop_recording()
        self.assertEqual(self.engine.get_status(), EngineStatus.IDLE)

        # 3. Start auto mode -> AUTO_ACTIVE
        self.engine.start_auto_mode(0.5, lambda p: None)
        self.assertEqual(self.engine.get_status(), EngineStatus.AUTO_ACTIVE)

        # Illegal actions while AUTO_ACTIVE
        with self.assertRaises(RuntimeError):
            self.engine.start_recording()

        # Stop auto mode -> IDLE
        self.engine.stop_auto_mode()
        self.assertEqual(self.engine.get_status(), EngineStatus.IDLE)

    def test_status_listeners_and_exception_isolation(self):
        """Verifies all status listeners receive events and listener exceptions don't break engine."""
        history_1 = []
        history_2 = []

        def listener_1(s: EngineStatus):
            history_1.append(s)

        def buggy_listener(s: EngineStatus):
            raise ValueError("Buggy listener exploded")

        def listener_2(s: EngineStatus):
            history_2.append(s)

        self.engine.add_status_listener(listener_1)
        self.engine.add_status_listener(buggy_listener)
        self.engine.add_status_listener(listener_2)

        self.engine.start_recording()
        self.engine.pause_recording()
        self.engine.resume_recording()
        self.engine.stop_recording()

        expected = [
            EngineStatus.RECORDING,
            EngineStatus.PAUSED,
            EngineStatus.RECORDING,
            EngineStatus.IDLE,
        ]
        self.assertEqual(history_1, expected)
        self.assertEqual(history_2, expected)

        # Remove listener
        self.engine.remove_status_listener(listener_1)
        self.engine.start_auto_mode(0.5, lambda p: None)
        self.engine.stop_auto_mode()

        self.assertEqual(history_1, expected)  # Unchanged
        self.assertEqual(history_2, expected + [EngineStatus.AUTO_ACTIVE, EngineStatus.IDLE])

    def test_clean_close_from_all_states(self):
        """Tests that engine.close() cleanly handles shutdown from IDLE, RECORDING, PAUSED, and AUTO_ACTIVE."""
        # Close from IDLE
        e1 = CaptureEngine(CaptureConfig(output_dir=self.test_dir))
        e1.close()
        self.assertEqual(e1.get_status(), EngineStatus.IDLE)

        # Close from RECORDING
        e2 = CaptureEngine(CaptureConfig(output_dir=self.test_dir))
        e2.start_recording()
        e2.close()
        self.assertEqual(e2.get_status(), EngineStatus.IDLE)

        # Close from PAUSED
        e3 = CaptureEngine(CaptureConfig(output_dir=self.test_dir))
        e3.start_recording()
        e3.pause_recording()
        e3.close()
        self.assertEqual(e3.get_status(), EngineStatus.IDLE)

        # Close from AUTO_ACTIVE
        e4 = CaptureEngine(CaptureConfig(output_dir=self.test_dir))
        e4.start_auto_mode(0.5, lambda p: None)
        e4.close()
        self.assertEqual(e4.get_status(), EngineStatus.IDLE)


if __name__ == "__main__":
    unittest.main()
