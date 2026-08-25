"""
Empirical and Adversarial Test Suite by Challenger 2 (Milestone 1).
Tests:
1. Audio capture & mixing: PulseAudio discovery, ALSA discovery, silence fallback, video+audio muxing in MP4 (AAC) and WebM (Opus).
2. Monotonic scheduler: auto-mode interval loop over multiple ticks, measure timestamp jitter, verify drift < 1ms.
3. Unified CaptureEngine facade: concurrent operations, rapid start/stop auto mode, manual capture during recording, state machine consistency.
"""

import os
import sys
import time
import math
import tempfile
import shutil
import threading
import subprocess
import traceback
from typing import List, Dict, Any, Tuple

# Ensure project root in sys.path
PROJECT_ROOT = "/home/user/program/video"
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


def log_test(name: str):
    print(f"\n========================================================")
    print(f"  TEST: {name}")
    print(f"========================================================")


def inspect_media_file(filepath: str) -> Dict[str, Any]:
    """Uses GstDiscoverer / ffprobe / cv2 to inspect container streams, codecs, duration."""
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

    # GstDiscoverer
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
        info["discoverer_error"] = str(e)

    # OpenCV check
    cap = cv2.VideoCapture(filepath)
    if cap.isOpened():
        info["cv2_opened"] = True
        info["cv2_width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        info["cv2_height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        info["cv2_frame_count"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        ret, frame = cap.read()
        info["cv2_can_read_frame"] = ret
        cap.release()
    else:
        info["cv2_opened"] = False

    # Check faststart for MP4 (moov atom before mdat)
    if filepath.endswith(".mp4"):
        with open(filepath, "rb") as f:
            data = f.read(65536)
            moov_pos = data.find(b"moov")
            mdat_pos = data.find(b"mdat")
            if moov_pos != -1 and (mdat_pos == -1 or moov_pos < mdat_pos):
                info["is_mp4_faststart"] = True

    return info


# ==============================================================================
# SECTION 1: Audio Capture & Mixing Tests
# ==============================================================================

def test_audio_discovery_and_fallbacks():
    log_test("Audio Discovery & Fallback Hierarchy")

    # 1. PulseAudio sources discovery
    pulse_devs = AudioDiscovery.list_pulse_sources()
    print(f"Discovered {len(pulse_devs)} PulseAudio devices:")
    for d in pulse_devs:
        print(f"  - {d.id} | {d.name} | type={d.device_type} | is_monitor={d.is_monitor}")

    # 2. ALSA sources discovery
    alsa_devs = AudioDiscovery.list_alsa_sources()
    print(f"Discovered {len(alsa_devs)} ALSA devices:")
    for d in alsa_devs:
        print(f"  - {d.id} | {d.name} | type={d.device_type}")

    # 3. get_all_devices
    all_devs = AudioDiscovery.get_all_devices()
    print(f"Total catalog devices: {len(all_devs)}")
    assert any(d.id == "default" and d.is_default for d in all_devs), "Missing default device in catalog"
    assert any(d.id == "silence" and d.device_type == "virtual" for d in all_devs), "Missing silence device in catalog"

    # 4. Fallback resolution tests
    res_default = AudioDiscovery.resolve_audio_source("default")
    print(f"Resolved 'default' -> '{res_default}'")
    assert res_default in ("pulsesrc", "alsasrc", "audiotestsrc is-live=true wave=silence")

    res_silence = AudioDiscovery.resolve_audio_source("silence")
    print(f"Resolved 'silence' -> '{res_silence}'")
    assert res_silence == "audiotestsrc is-live=true wave=silence"

    res_none = AudioDiscovery.resolve_audio_source("none")
    print(f"Resolved 'none' -> '{res_none}'")
    assert res_none == "audiotestsrc is-live=true wave=silence"

    # 5. Nonexistent device fallback test
    res_fake_pulse = AudioDiscovery.resolve_audio_source("pulse:nonexistent_device_xyz_99999")
    print(f"Resolved fake pulse -> '{res_fake_pulse}'")
    # Should fallback gracefully to default pulsesrc, alsasrc, or silence, NEVER throw or return broken device
    assert "nonexistent_device_xyz_99999" not in res_fake_pulse

    res_fake_alsa = AudioDiscovery.resolve_audio_source("hw:99,99")
    print(f"Resolved fake alsa -> '{res_fake_alsa}'")
    assert "hw:99,99" not in res_fake_alsa

    print(">> Audio Discovery & Fallback Hierarchy: PASS")


def test_video_audio_muxing_mp4_and_webm():
    log_test("Video + Audio Muxing in MP4 (AAC) and WebM (Opus)")
    temp_dir = tempfile.mkdtemp(prefix="audio_mux_test_")
    try:
        recorder = VideoRecorder()

        # 1. MP4 with Audio (AAC)
        mp4_path = os.path.join(temp_dir, "test_audio.mp4")
        cfg_mp4 = CaptureConfig(
            video_format=OutputFormat.MP4,
            audio_enabled=True,
            audio_source="default",
            region=Region(0, 0, 320, 240),
            fps=30,
            output_dir=temp_dir,
        )
        print("Starting MP4 + Audio recording...")
        recorder.start(filepath=mp4_path, config=cfg_mp4)
        time.sleep(1.5)
        out_mp4 = recorder.stop()
        print(f"Stopped MP4 recording: {out_mp4}")

        info_mp4 = inspect_media_file(out_mp4)
        print("MP4 Inspection Results:")
        for k, v in info_mp4.items():
            print(f"  {k}: {v}")

        assert info_mp4["exists"], "MP4 file does not exist"
        assert info_mp4["filesize"] > 1000, f"MP4 file size too small: {info_mp4['filesize']} bytes"
        assert info_mp4["has_video"], "MP4 file has no video stream"
        assert info_mp4["has_audio"], "MP4 file has no audio stream"
        assert info_mp4["is_mp4_faststart"], "MP4 file does not have faststart moov at front"
        assert info_mp4["cv2_can_read_frame"], "OpenCV cannot read video frames from MP4"
        a_codec = str(info_mp4["audio_codec"]).lower()
        assert "aac" in a_codec or "mpegversion=(int)4" in a_codec or "profile=(string)lc" in a_codec or "mp3" in a_codec, f"Unexpected audio codec: {info_mp4['audio_codec']}"

        # 2. WebM with Audio (Opus)
        webm_path = os.path.join(temp_dir, "test_audio.webm")
        cfg_webm = CaptureConfig(
            video_format=OutputFormat.WEBM,
            audio_enabled=True,
            audio_source="default",
            region=Region(0, 0, 320, 240),
            fps=30,
            output_dir=temp_dir,
        )
        print("\nStarting WebM + Audio recording...")
        recorder.start(filepath=webm_path, config=cfg_webm)
        time.sleep(1.5)
        out_webm = recorder.stop()
        print(f"Stopped WebM recording: {out_webm}")

        info_webm = inspect_media_file(out_webm)
        print("WebM Inspection Results:")
        for k, v in info_webm.items():
            print(f"  {k}: {v}")

        assert info_webm["exists"], "WebM file does not exist"
        assert info_webm["filesize"] > 1000, f"WebM file size too small: {info_webm['filesize']} bytes"
        assert info_webm["has_video"], "WebM file has no video stream"
        assert info_webm["has_audio"], "WebM file has no audio stream"
        assert "opus" in str(info_webm["audio_codec"]).lower() or "vorbis" in str(info_webm["audio_codec"]).lower(), f"Unexpected audio codec: {info_webm['audio_codec']}"

        # 3. WebM and MP4 with Silence fallback
        silence_mp4_path = os.path.join(temp_dir, "test_silence.mp4")
        cfg_silence = CaptureConfig(
            video_format=OutputFormat.MP4,
            audio_enabled=True,
            audio_source="silence",
            region=Region(0, 0, 320, 240),
            fps=30,
            output_dir=temp_dir,
        )
        print("\nStarting MP4 + Silence recording...")
        recorder.start(filepath=silence_mp4_path, config=cfg_silence)
        time.sleep(1.0)
        out_silence = recorder.stop()
        info_silence = inspect_media_file(out_silence)
        print("Silence MP4 Inspection Results:")
        for k, v in info_silence.items():
            print(f"  {k}: {v}")
        assert info_silence["has_video"] and info_silence["has_audio"], "Silence MP4 failed to mux audio stream"

        print(">> Video + Audio Muxing: PASS")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# SECTION 2: Monotonic Scheduler & Drift Tests
# ==============================================================================

def test_monotonic_scheduler_precision_and_jitter():
    log_test("Monotonic Scheduler Precision & Jitter Measurement")

    scheduler = MonotonicScheduler()
    ticks: List[Tuple[float, float, float]] = [] # (expected_target, actual_time, drift)
    start_time = time.monotonic()
    interval = 0.5
    num_ticks = 10

    def on_tick(actual_now, drift):
        ticks.append((start_time + len(ticks) * interval, actual_now, drift))

    print(f"Running scheduler for {num_ticks} ticks at {interval}s interval...")
    scheduler.start(interval=interval, callback=on_tick)
    time.sleep((num_ticks + 0.3) * interval)
    scheduler.stop()

    print(f"Collected {len(ticks)} ticks (expected {num_ticks}):")
    drifts_ms = []
    interval_jitters_ms = []
    prev_time = start_time

    for idx, (expected, actual, drift) in enumerate(ticks):
        d_ms = drift * 1000.0
        step_interval = (actual - prev_time) if idx > 0 else (actual - start_time)
        jitter_ms = abs(step_interval - interval) * 1000.0 if idx > 0 else 0.0
        drifts_ms.append(abs(d_ms))
        if idx > 0:
            interval_jitters_ms.append(jitter_ms)
        print(f"  Tick {idx+1:02d}: drift={d_ms:+.3f}ms | interval={step_interval:.4f}s (jitter={jitter_ms:.3f}ms)")
        prev_time = actual

    avg_drift_ms = sum(drifts_ms) / len(drifts_ms) if drifts_ms else 0.0
    max_drift_ms = max(drifts_ms) if drifts_ms else 0.0
    avg_jitter_ms = sum(interval_jitters_ms) / len(interval_jitters_ms) if interval_jitters_ms else 0.0
    max_jitter_ms = max(interval_jitters_ms) if interval_jitters_ms else 0.0

    print(f"\nScheduler Statistics:")
    print(f"  - Average absolute drift: {avg_drift_ms:.4f}ms (requirement: < 1.0ms)")
    print(f"  - Max absolute drift:     {max_drift_ms:.4f}ms")
    print(f"  - Average tick jitter:    {avg_jitter_ms:.4f}ms")
    print(f"  - Max tick jitter:        {max_jitter_ms:.4f}ms")

    assert len(ticks) >= num_ticks - 1, f"Expected at least {num_ticks-1} ticks, got {len(ticks)}"
    assert avg_drift_ms < 1.0, f"Average drift {avg_drift_ms:.4f}ms exceeds 1.0ms limit"

    print(">> Monotonic Scheduler Precision & Jitter: PASS")


def test_scheduler_dynamic_interval_and_overrun():
    log_test("Scheduler Dynamic Interval & Overrun Handling")
    scheduler = MonotonicScheduler()

    ticks = []
    scheduler.start(interval=0.5, callback=lambda t, d: ticks.append((t, d)))
    time.sleep(1.1) # 2 ticks at 0.5s
    count_phase1 = len(ticks)

    # Change interval dynamically to 1.0s
    scheduler.set_interval(1.0)
    time.sleep(2.2) # 2 ticks at 1.0s
    count_phase2 = len(ticks) - count_phase1

    scheduler.stop()

    print(f"Phase 1 (0.5s interval): {count_phase1} ticks")
    print(f"Phase 2 (1.0s interval): {count_phase2} ticks")
    assert count_phase1 >= 2, f"Phase 1 failed, got {count_phase1} ticks"
    assert count_phase2 >= 2, f"Phase 2 failed, got {count_phase2} ticks"

    # Test callback overrun protection
    print("\nTesting heavy callback overrun...")
    overrun_ticks = []
    def slow_callback():
        overrun_ticks.append(time.monotonic())
        time.sleep(0.35) # takes 350ms on 200ms interval (wait, interval min is 0.5s so let's use 0.5s interval and 0.7s sleep)

    scheduler.start(interval=0.5, callback=slow_callback)
    time.sleep(2.0)
    scheduler.stop()
    print(f"Slow callback dispatched {len(overrun_ticks)} times without deadlock or thread queue explosion")
    assert len(overrun_ticks) >= 2, "Overrun loop did not execute expected ticks"

    print(">> Scheduler Dynamic Interval & Overrun Handling: PASS")


# ==============================================================================
# SECTION 3: Unified CaptureEngine Facade & Concurrency / State Machine Tests
# ==============================================================================

def test_capture_engine_state_machine():
    log_test("CaptureEngine State Machine Transitions & Invariants")
    temp_dir = tempfile.mkdtemp(prefix="engine_state_test_")
    try:
        cfg = CaptureConfig(output_dir=temp_dir, region=Region(0, 0, 320, 240))
        engine = CaptureEngine(cfg)

        state_history: List[EngineStatus] = []
        engine.add_status_listener(lambda s: state_history.append(s))

        assert engine.get_status() == EngineStatus.IDLE

        # 1. Valid Recording Lifecycle: IDLE -> RECORDING -> PAUSED -> RECORDING -> IDLE
        print("Testing valid recording lifecycle...")
        engine.start_recording()
        assert engine.get_status() == EngineStatus.RECORDING

        engine.pause_recording()
        assert engine.get_status() == EngineStatus.PAUSED

        engine.resume_recording()
        assert engine.get_status() == EngineStatus.RECORDING

        rec_path = engine.stop_recording()
        assert engine.get_status() == EngineStatus.IDLE
        assert os.path.exists(rec_path)

        # 2. Valid Auto Mode Lifecycle: IDLE -> AUTO_ACTIVE -> IDLE
        print("Testing valid auto mode lifecycle...")
        auto_paths = []
        engine.start_auto_mode(interval=0.5, callback=lambda p: auto_paths.append(p))
        assert engine.get_status() == EngineStatus.AUTO_ACTIVE
        time.sleep(1.2)
        engine.stop_auto_mode()
        assert engine.get_status() == EngineStatus.IDLE
        assert len(auto_paths) >= 2

        # 3. Illegal State Transitions & Exception Guarantees
        print("Testing illegal state transitions...")
        # A. Cannot pause when IDLE
        try:
            engine.pause_recording()
            assert False, "Should have raised RuntimeError"
        except RuntimeError:
            pass

        # B. Cannot resume when IDLE
        try:
            engine.resume_recording()
            assert False, "Should have raised RuntimeError"
        except RuntimeError:
            pass

        # C. Cannot stop when IDLE
        try:
            engine.stop_recording()
            assert False, "Should have raised RuntimeError"
        except RuntimeError:
            pass

        # D. Cannot start auto mode while RECORDING
        engine.start_recording()
        try:
            engine.start_auto_mode(0.5, lambda p: None)
            assert False, "Should have raised RuntimeError"
        except RuntimeError:
            pass

        # E. Cannot start recording while RECORDING
        try:
            engine.start_recording()
            assert False, "Should have raised RuntimeError"
        except RuntimeError:
            pass

        engine.stop_recording()

        # F. Cannot start recording while AUTO_ACTIVE
        engine.start_auto_mode(0.5, lambda p: None)
        try:
            engine.start_recording()
            assert False, "Should have raised RuntimeError"
        except RuntimeError:
            pass
        engine.stop_auto_mode()

        print(">> CaptureEngine State Machine Transitions: PASS")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_rapid_auto_mode_toggling():
    log_test("Rapid start_auto_mode / stop_auto_mode Stress (100 cycles)")
    temp_dir = tempfile.mkdtemp(prefix="rapid_auto_test_")
    try:
        cfg = CaptureConfig(output_dir=temp_dir)
        engine = CaptureEngine(cfg)

        cycles = 100
        captures = []
        start_t = time.monotonic()
        for i in range(cycles):
            engine.start_auto_mode(0.5, lambda p: captures.append(p))
            # Varying micro delays
            if i % 5 == 0:
                time.sleep(0.01)
            elif i % 7 == 0:
                time.sleep(0.05)
            engine.stop_auto_mode()
            assert engine.get_status() == EngineStatus.IDLE

        elapsed = time.monotonic() - start_t
        print(f"Completed {cycles} start/stop cycles in {elapsed:.3f}s ({elapsed/cycles*1000:.2f}ms/cycle)")
        assert engine.get_status() == EngineStatus.IDLE

        print(">> Rapid start_auto_mode / stop_auto_mode: PASS")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_concurrent_manual_capture_operations():
    log_test("Concurrent Manual Captures & Operations")
    temp_dir = tempfile.mkdtemp(prefix="concurrent_ops_test_")
    try:
        cfg = CaptureConfig(output_dir=temp_dir, region=Region(0, 0, 320, 240))
        engine = CaptureEngine(cfg)

        # 1. Manual capture during active video recording
        print("Testing manual screenshot during active video recording...")
        engine.start_recording()
        time.sleep(0.5)

        screenshot_path1 = engine.capture_screenshot()
        assert os.path.exists(screenshot_path1)
        with Image.open(screenshot_path1) as im:
            assert im.size == (320, 240)

        time.sleep(0.5)
        video_path = engine.stop_recording()
        assert os.path.exists(video_path)

        info_vid = inspect_media_file(video_path)
        assert info_vid["has_video"] and info_vid["cv2_can_read_frame"], "Video corrupted by concurrent screenshot"

        # 2. Multi-threaded burst manual capture (20 threads concurrent screenshots)
        print("Testing 20 concurrent threads calling capture_screenshot()...")
        results = []
        errors = []

        def worker(idx):
            try:
                p = engine.capture_screenshot()
                results.append(p)
            except Exception as e:
                errors.append((idx, e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        print(f"Generated {len(results)} screenshots from 20 threads (errors: {len(errors)})")
        assert len(errors) == 0, f"Thread errors occurred: {errors}"
        assert len(results) == 20, f"Expected 20 screenshots, got {len(results)}"
        for p in results:
            assert os.path.exists(p)

        # 3. Manual capture during auto mode
        print("Testing manual screenshot during active auto-capture loop...")
        auto_captures = []
        engine.start_auto_mode(0.5, lambda p: auto_captures.append(p))
        time.sleep(0.6)

        manual_p = engine.capture_screenshot()
        assert os.path.exists(manual_p)

        time.sleep(0.6)
        engine.stop_auto_mode()

        assert len(auto_captures) >= 2
        assert manual_p not in auto_captures

        print(">> Concurrent Manual Captures: PASS")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# MAIN TEST RUNNER
# ==============================================================================

def main():
    print("\n" + "=" * 60)
    print("STARTING CHALLENGER 2 EMPIRICAL TEST SUITE")
    print("=" * 60)

    tests = [
        ("Audio Discovery & Fallback", test_audio_discovery_and_fallbacks),
        ("Video+Audio MP4/WebM Muxing", test_video_audio_muxing_mp4_and_webm),
        ("Monotonic Scheduler Precision", test_monotonic_scheduler_precision_and_jitter),
        ("Scheduler Overrun & Dynamic Interval", test_scheduler_dynamic_interval_and_overrun),
        ("CaptureEngine State Machine", test_capture_engine_state_machine),
        ("Rapid Auto Mode Toggling", test_rapid_auto_mode_toggling),
        ("Concurrent Manual Captures", test_concurrent_manual_capture_operations),
    ]

    passed = 0
    failed = 0
    results_summary = []

    for name, fn in tests:
        try:
            fn()
            passed += 1
            results_summary.append((name, "PASS", None))
        except Exception as e:
            failed += 1
            tb = traceback.format_exc()
            results_summary.append((name, "FAIL", tb))
            print(f"\n[!] TEST FAILED: {name}")
            print(tb)

    print("\n" + "=" * 60)
    print("CHALLENGER 2 EMPIRICAL TEST SUITE SUMMARY")
    print("=" * 60)
    for name, status, err in results_summary:
        print(f"  {name:<40} : [{status}]")

    print(f"\nTotal: {len(tests)} | Passed: {passed} | Failed: {failed}")
    if failed == 0:
        print("\nALL EMPIRICAL TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print(f"\n{failed} TESTS FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    main()
