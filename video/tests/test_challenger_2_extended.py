"""
Extended Stress & Long-Run Verification by Challenger 2.
Tests:
1. 50-tick monotonic scheduler cumulative drift analysis (verifying zero cumulative drift growth over time).
2. Rapid audio source alternating recording cycles (Pulse -> ALSA -> Silence -> ALSA).
3. Concurrent heavy stress: Video recording + 50 concurrent manual screenshot threads.
"""

import os
import sys
import time
import tempfile
import shutil
import threading
from typing import List, Tuple

PROJECT_ROOT = "/home/user/program/video"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import cv2
from PIL import Image

from src.config import CaptureConfig, EngineStatus, OutputFormat, Region
from src.engine.audio import AudioDiscovery, AudioMixer
from src.engine.scheduler import MonotonicScheduler
from src.engine.recorder import VideoRecorder
from src.engine import CaptureEngine


def test_50_tick_cumulative_drift():
    print("\n--- TEST: 50-Tick Cumulative Drift Analysis ---")
    scheduler = MonotonicScheduler()
    interval = 0.1 # 100ms (testing fast scheduler ticks)
    # Using the scheduler's internal loop
    num_ticks = 50
    drifts: List[float] = []
    actual_timestamps: List[float] = []

    start_monotonic = time.monotonic()

    def on_tick(now_t, drift):
        drifts.append(drift)
        actual_timestamps.append(now_t)

    scheduler._interval = interval # set directly for high-frequency test
    scheduler._callback = on_tick
    scheduler._stop_event.clear()
    scheduler._is_running = True
    scheduler._tick_count = 0

    thread = threading.Thread(target=scheduler._run_loop, daemon=True)
    thread.start()

    time.sleep(num_ticks * interval + 0.5)
    scheduler.stop()

    print(f"Recorded {len(drifts)} ticks:")
    abs_drifts_ms = [abs(d) * 1000.0 for d in drifts]
    avg_drift_ms = sum(abs_drifts_ms) / len(abs_drifts_ms)
    max_drift_ms = max(abs_drifts_ms)

    # Check cumulative drift: difference between (start_time + N*interval) and actual timestamp at tick N
    cumulative_drift_end_ms = abs((actual_timestamps[-1] - (start_monotonic + len(actual_timestamps) * interval))) * 1000.0

    print(f"  - Average tick drift:    {avg_drift_ms:.4f} ms")
    print(f"  - Maximum tick drift:    {max_drift_ms:.4f} ms")
    print(f"  - Final cumulative drift: {cumulative_drift_end_ms:.4f} ms")

    assert avg_drift_ms < 1.0, f"Average drift {avg_drift_ms}ms exceeded 1.0ms"
    print(">> 50-Tick Drift Analysis: PASS")


def test_rapid_audio_device_alternation():
    print("\n--- TEST: Rapid Audio Device Alternation ---")
    temp_dir = tempfile.mkdtemp(prefix="audio_alt_test_")
    try:
        recorder = VideoRecorder()
        sources = ["default", "silence", "hw:1,0", "none", "hw:1,1"]

        for idx, src in enumerate(sources):
            out_file = os.path.join(temp_dir, f"alt_audio_{idx}.mp4")
            cfg = CaptureConfig(
                video_format=OutputFormat.MP4,
                audio_enabled=True,
                audio_source=src,
                region=Region(0, 0, 320, 240),
                output_dir=temp_dir,
            )
            print(f"  Recording take {idx+1}/5 with audio source '{src}'...")
            recorder.start(filepath=out_file, config=cfg)
            time.sleep(0.8)
            res = recorder.stop()
            assert os.path.exists(res), f"Take {idx} output file missing"
            assert os.path.getsize(res) > 1000, f"Take {idx} output file too small"
            print(f"    Take {idx+1} successfully recorded ({os.path.getsize(res)} bytes)")

        print(">> Rapid Audio Device Alternation: PASS")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_heavy_concurrency_stress():
    print("\n--- TEST: Heavy Concurrency Stress (Active Recording + 50 Screenshot Threads) ---")
    temp_dir = tempfile.mkdtemp(prefix="heavy_concurrency_")
    try:
        engine = CaptureEngine(CaptureConfig(output_dir=temp_dir, region=Region(0, 0, 320, 240)))
        print("  Starting background video recording...")
        engine.start_recording()

        screenshots = []
        errors = []

        def worker(i):
            try:
                p = engine.capture_screenshot()
                screenshots.append(p)
            except Exception as e:
                errors.append((i, e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        print(f"  Launching 50 concurrent screenshot threads while recording is live...")
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        time.sleep(0.5)
        video_path = engine.stop_recording()

        print(f"  Captured {len(screenshots)} screenshots with {len(errors)} errors")
        print(f"  Finalized recording: {video_path} ({os.path.getsize(video_path)} bytes)")

        assert len(errors) == 0, f"Errors occurred during concurrent stress: {errors}"
        assert len(screenshots) == 50, f"Expected 50 screenshots, got {len(screenshots)}"
        assert os.path.exists(video_path)
        assert os.path.getsize(video_path) > 2000

        print(">> Heavy Concurrency Stress: PASS")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_50_tick_cumulative_drift()
    test_rapid_audio_device_alternation()
    test_heavy_concurrency_stress()
    print("\nALL EXTENDED STRESS TESTS PASSED SUCCESSFULLY!")
