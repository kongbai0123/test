"""
tests/test_challenger_3_empirical.py
Exhaustive Empirical & Adversarial Test Suite by Challenger 3 (Milestone 1, Iteration 2).

Scope:
1. Screenshot capture across full screen and custom ROI regions (handling negative/inverted coords, odd dimensions).
2. PNG (lossless) and JPG (quality configurable) output file validity and magic headers.
3. MP4 (faststart moov atom at beginning) and WebM video recording, frame decodability via OpenCV cv2.VideoCapture.
4. Rapid pause/resume/stop lifecycles and state machine stress testing.
"""

from __future__ import annotations

import datetime
import math
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstPbutils", "1.0")
from gi.repository import Gst, GstPbutils
Gst.init(None)

PROJECT_ROOT = "/home/user/program/video"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.config import (
    CaptureConfig,
    CaptureMode,
    EngineStatus,
    OutputFormat,
    Region,
)
from src.engine import CaptureEngine
from src.engine.recorder import VideoRecorder, normalize_video_roi
from src.engine.screenshot import ScreenshotEngine, normalize_roi


def section_header(title: str):
    print("\n" + "=" * 70)
    print(f"  TEST: {title}")
    print("=" * 70)


def parse_mp4_box_atoms(filepath: str) -> List[Tuple[str, int, int]]:
    """
    Parses top-level ISO/IEC 14496-12 MP4 / QuickTime box headers.
    Returns a list of tuples: (box_type, offset, box_size).
    """
    atoms: List[Tuple[str, int, int]] = []
    file_size = os.path.getsize(filepath)
    with open(filepath, "rb") as f:
        offset = 0
        while offset < file_size:
            f.seek(offset)
            header = f.read(8)
            if len(header) < 8:
                break
            box_size, box_type_bytes = struct.unpack(">I4s", header)
            box_type = box_type_bytes.decode("latin1", errors="replace")

            if box_size == 1:
                # 64-bit extended size
                ext_header = f.read(8)
                if len(ext_header) < 8:
                    break
                box_size = struct.unpack(">Q", ext_header)[0]
            elif box_size == 0:
                # Extends to end of file
                box_size = file_size - offset

            atoms.append((box_type, offset, box_size))
            if box_size <= 0:
                break
            offset += box_size
    return atoms


# ==============================================================================
# SECTION 1: Screenshot Capture & ROI Normalization Tests
# ==============================================================================

def test_screenshot_fullscreen_and_roi():
    section_header("1. Screenshot Fullscreen & Custom ROI Captures")
    grabber = ScreenshotEngine()
    screen_w, screen_h = grabber.get_screen_size()
    print(f"Detected desktop resolution: {screen_w}x{screen_h}")
    assert screen_w > 0 and screen_h > 0, f"Invalid screen dimensions: {screen_w}x{screen_h}"

    # 1. Fullscreen Capture
    print("Testing Fullscreen Capture...")
    img_full = grabber.capture_image(None)
    assert isinstance(img_full, Image.Image), "Captured object is not a PIL Image"
    assert img_full.size == (screen_w, screen_h), f"Fullscreen size mismatch: {img_full.size} vs ({screen_w}, {screen_h})"
    assert img_full.mode == "RGB", f"Expected RGB mode, got {img_full.mode}"

    # 2. Standard ROI Capture
    roi_w, roi_h = 320, 240
    roi = Region(50, 50, roi_w, roi_h)
    print(f"Testing Standard ROI Capture: {roi}...")
    img_roi = grabber.capture_image(roi)
    assert img_roi.size == (roi_w, roi_h), f"ROI size mismatch: {img_roi.size} vs ({roi_w}, {roi_h})"

    # 3. Odd Dimensions ROI Capture (e.g. 137x243, 1x1)
    odd_roi = Region(20, 20, 137, 243)
    print(f"Testing Odd-Dimension ROI Capture: {odd_roi}...")
    img_odd = grabber.capture_image(odd_roi)
    assert img_odd.size == (137, 243), f"Odd ROI size mismatch: {img_odd.size} vs (137, 243)"

    min_roi = Region(10, 10, 1, 1)
    print(f"Testing Minimum 1x1 ROI Capture: {min_roi}...")
    img_min = grabber.capture_image(min_roi)
    assert img_min.size == (1, 1), f"Min ROI size mismatch: {img_min.size} vs (1, 1)"

    print(">> Screenshot Fullscreen & Custom ROI Captures: PASS")


def test_screenshot_inverted_negative_and_out_of_bounds_roi():
    section_header("2. ROI Normalization: Inverted, Negative & Out-of-Bounds")
    screen_w, screen_h = 1920, 1080

    # 1. Inverted points via Region.from_points
    r_inv1 = Region.from_points(500, 400, 100, 100)
    print(f"Region.from_points(500, 400, 100, 100) -> {r_inv1}")
    assert r_inv1.x == 100 and r_inv1.y == 100
    assert r_inv1.width == 400 and r_inv1.height == 300

    # 2. Negative width/height normalization via normalize_roi
    r_neg = Region(500, 400, -400, -300)
    norm_neg = normalize_roi(r_neg, screen_w, screen_h)
    print(f"normalize_roi(Region(500, 400, -400, -300)) -> {norm_neg}")
    assert norm_neg == (100, 100, 400, 300)

    # 3. Negative starting coordinates
    r_neg_start = Region(-100, -50, 500, 400)
    norm_neg_start = normalize_roi(r_neg_start, screen_w, screen_h)
    print(f"normalize_roi(Region(-100, -50, 500, 400)) -> {norm_neg_start}")
    assert norm_neg_start[0] >= 0 and norm_neg_start[1] >= 0
    assert norm_neg_start[0] + norm_neg_start[2] <= screen_w
    assert norm_neg_start[1] + norm_neg_start[3] <= screen_h

    # 4. Out-of-bounds boundary clamping
    r_oob = Region(1800, 1000, 500, 500)
    norm_oob = normalize_roi(r_oob, screen_w, screen_h)
    print(f"normalize_roi(Region(1800, 1000, 500, 500)) -> {norm_oob}")
    assert norm_oob == (1800, 1000, 120, 80)
    assert norm_oob[0] + norm_oob[2] == 1920
    assert norm_oob[1] + norm_oob[3] == 1080

    # 5. Real capture with inverted/out-of-bounds region
    grabber = ScreenshotEngine()
    real_w, real_h = grabber.get_screen_size()
    real_oob = Region(real_w - 50, real_h - 40, 200, 200)
    print(f"Testing real screen grab with out-of-bounds region {real_oob}...")
    img_oob = grabber.capture_image(real_oob)
    assert img_oob.size == (50, 40), f"Expected clamped (50, 40), got {img_oob.size}"

    print(">> ROI Normalization: Inverted, Negative & Out-of-Bounds: PASS")


# ==============================================================================
# SECTION 2: Image Format & Magic Header Validation (PNG / JPG)
# ==============================================================================

def test_image_formats_magic_headers_and_lossless_quality():
    section_header("3. Image Format Validity, Magic Bytes & Lossless/Quality Validation")
    temp_dir = tempfile.mkdtemp(prefix="img_format_test_")
    try:
        grabber = ScreenshotEngine()
        roi = Region(10, 10, 200, 150)

        # 1. PNG Header & Magic Bytes Verification
        png_path = os.path.join(temp_dir, "test_magic.png")
        saved_png = grabber.save_screenshot(png_path, region=roi, fmt=OutputFormat.PNG)
        assert os.path.exists(saved_png)
        assert os.path.getsize(saved_png) > 100

        with open(saved_png, "rb") as f:
            png_magic = f.read(8)
            print(f"PNG Magic Bytes: {list(png_magic)}")
            # PNG signature: 89 50 4E 47 0D 0A 1A 0A
            assert png_magic == b"\x89PNG\r\n\x1a\n", f"Invalid PNG magic bytes: {png_magic}"

        with Image.open(saved_png) as im_png:
            assert im_png.format == "PNG"
            assert im_png.size == (200, 150)

        # 2. JPG Header & Magic Bytes Verification
        jpg_path = os.path.join(temp_dir, "test_magic.jpg")
        saved_jpg = grabber.save_screenshot(jpg_path, region=roi, fmt=OutputFormat.JPG, quality=90)
        assert os.path.exists(saved_jpg)
        assert os.path.getsize(saved_jpg) > 100

        with open(saved_jpg, "rb") as f:
            jpg_magic = f.read(3)
            print(f"JPG Magic Bytes: {list(jpg_magic)}")
            # JPG signature: FF D8 FF
            assert jpg_magic == b"\xff\xd8\xff", f"Invalid JPG magic bytes: {jpg_magic}"

        with Image.open(saved_jpg) as im_jpg:
            assert im_jpg.format == "JPEG"
            assert im_jpg.size == (200, 150)

        # 3. PNG Lossless Verification
        print("Testing PNG Lossless Pixel Fidelity...")
        img_mem = grabber.capture_image(roi)
        mem_arr = np.array(img_mem)

        lossless_png_path = os.path.join(temp_dir, "lossless.png")
        img_mem.save(lossless_png_path, format="PNG")
        with Image.open(lossless_png_path) as loaded_im:
            loaded_arr = np.array(loaded_im)
            assert np.array_equal(mem_arr, loaded_arr), "PNG pixel values do not match in-memory buffer (Lossless violation!)"

        # 4. JPG Quality Configurable Verification
        print("Testing JPG Quality Compression Scaling (q=10, q=50, q=95)...")
        q10_path = os.path.join(temp_dir, "test_q10.jpg")
        q50_path = os.path.join(temp_dir, "test_q50.jpg")
        q95_path = os.path.join(temp_dir, "test_q95.jpg")

        grabber.save_screenshot(q10_path, region=roi, fmt=OutputFormat.JPG, quality=10)
        grabber.save_screenshot(q50_path, region=roi, fmt=OutputFormat.JPG, quality=50)
        grabber.save_screenshot(q95_path, region=roi, fmt=OutputFormat.JPG, quality=95)

        s10 = os.path.getsize(q10_path)
        s50 = os.path.getsize(q50_path)
        s95 = os.path.getsize(q95_path)

        print(f"  - Quality 10  size: {s10} bytes")
        print(f"  - Quality 50  size: {s50} bytes")
        print(f"  - Quality 95  size: {s95} bytes")

        assert s10 < s50, f"Expected size(q=10) < size(q=50), got {s10} vs {s50}"
        assert s50 < s95, f"Expected size(q=50) < size(q=95), got {s50} vs {s95}"

        # 5. Collision-Free Suffix Generation
        print("Testing Collision-Free Filename Generation in capture_to_file()...")
        paths = []
        for _ in range(5):
            p = grabber.capture_to_file(temp_dir, region=roi, image_format=OutputFormat.PNG)
            paths.append(p)

        assert len(paths) == len(set(paths)), "Duplicate filenames generated by capture_to_file"
        for p in paths:
            assert os.path.exists(p)

        print(">> Image Format Validity, Magic Bytes & Lossless/Quality: PASS")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# SECTION 3: Video Recording & MP4 Faststart / WebM / OpenCV Decodability
# ==============================================================================

def test_mp4_faststart_moov_atom_positioning():
    section_header("4. MP4 Video Recording & Faststart Moov Atom Verification")
    temp_dir = tempfile.mkdtemp(prefix="mp4_faststart_test_")
    try:
        recorder = VideoRecorder()
        out_mp4 = os.path.join(temp_dir, "test_faststart.mp4")

        # Odd dimensions ROI: 321x241 -> normalized to 320x240
        cfg = CaptureConfig(
            video_format=OutputFormat.MP4,
            audio_enabled=False,
            region=Region(10, 10, 321, 241),
            fps=30,
            output_dir=temp_dir,
        )

        print("Starting MP4 recording (321x241 odd ROI -> even normalized)...")
        recorder.start(filepath=out_mp4, config=cfg)
        time.sleep(1.5)
        saved_file = recorder.stop()

        assert os.path.exists(saved_file), "Recorded MP4 file not found"
        filesize = os.path.getsize(saved_file)
        print(f"Recorded MP4 file size: {filesize} bytes")
        assert filesize > 5000, f"MP4 file unexpectedly small: {filesize} bytes"

        # Parse MP4 Box Atoms
        atoms = parse_mp4_box_atoms(saved_file)
        print("Discovered Top-Level MP4 Box Atoms:")
        for b_type, offset, b_size in atoms:
            print(f"  - Box '{b_type}' at offset {offset:08d} (size: {b_size:08d} bytes)")

        box_types = [a[0] for a in atoms]
        assert "ftyp" in box_types, "Missing 'ftyp' box in MP4 container"
        assert "moov" in box_types, "Missing 'moov' box in MP4 container"
        assert "mdat" in box_types, "Missing 'mdat' box in MP4 container"

        moov_offset = next(a[1] for a in atoms if a[0] == "moov")
        mdat_offset = next(a[1] for a in atoms if a[0] == "mdat")

        print(f"moov offset: {moov_offset} | mdat offset: {mdat_offset}")
        assert moov_offset < mdat_offset, (
            f"Faststart violation! 'moov' atom (offset {moov_offset}) is placed AFTER 'mdat' (offset {mdat_offset})."
        )
        print(">> Faststart Moov Atom Verification: PASS (moov is at the front before mdat)")

        # OpenCV Decodability Test for MP4
        print("\nVerifying MP4 Frame-by-Frame Decodability via OpenCV cv2.VideoCapture...")
        cap = cv2.VideoCapture(saved_file)
        assert cap.isOpened(), "cv2.VideoCapture failed to open recorded MP4"

        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        print(f"OpenCV MP4 Stream Properties: resolution={frame_w}x{frame_h}, reported_fps={fps}")

        assert frame_w == 320 and frame_h == 240, f"Expected normalized 320x240, got {frame_w}x{frame_h}"

        frames_read = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            assert frame is not None
            assert frame.shape == (240, 320, 3), f"Unexpected frame shape: {frame.shape}"
            assert frame.dtype == np.uint8
            frames_read += 1

        cap.release()
        print(f"Successfully decoded {frames_read} frames from MP4 stream without errors.")
        assert frames_read >= 20, f"Expected at least 20 decoded frames for 1.5s recording, got {frames_read}"

        print(">> MP4 Video Recording & OpenCV Decodability: PASS")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_webm_video_recording_and_opencv_decodability():
    section_header("5. WebM Video Recording & OpenCV Decodability")
    temp_dir = tempfile.mkdtemp(prefix="webm_test_")
    try:
        recorder = VideoRecorder()
        out_webm = os.path.join(temp_dir, "test_recording.webm")

        cfg = CaptureConfig(
            video_format=OutputFormat.WEBM,
            audio_enabled=False,
            region=Region(20, 20, 321, 241),
            fps=30,
            output_dir=temp_dir,
        )

        print("Starting WebM recording (321x241 odd ROI -> 320x240 even)...")
        recorder.start(filepath=out_webm, config=cfg)
        time.sleep(1.5)
        saved_file = recorder.stop()

        assert os.path.exists(saved_file), "Recorded WebM file not found"
        filesize = os.path.getsize(saved_file)
        print(f"Recorded WebM file size: {filesize} bytes")
        assert filesize > 5000, f"WebM file unexpectedly small: {filesize} bytes"

        # Check EBML Header
        with open(saved_file, "rb") as f:
            ebml_header = f.read(4)
            print(f"WebM EBML Magic Header: {list(ebml_header)}")
            assert ebml_header == b"\x1a\x45\xdf\xa3", f"Invalid EBML magic header for WebM: {ebml_header}"

        # OpenCV Decodability Test for WebM
        print("\nVerifying WebM Frame Decodability via OpenCV cv2.VideoCapture...")
        cap = cv2.VideoCapture(saved_file)
        assert cap.isOpened(), "cv2.VideoCapture failed to open recorded WebM"

        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"OpenCV WebM Stream Properties: resolution={frame_w}x{frame_h}")

        assert frame_w == 320 and frame_h == 240, f"Expected normalized 320x240, got {frame_w}x{frame_h}"

        frames_read = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            assert frame is not None
            assert frame.shape == (240, 320, 3)
            frames_read += 1

        cap.release()
        print(f"Successfully decoded {frames_read} frames from WebM stream.")
        assert frames_read >= 20, f"Expected at least 20 decoded frames for 1.5s recording, got {frames_read}"

        print(">> WebM Video Recording & OpenCV Decodability: PASS")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# SECTION 4: Rapid Pause / Resume / Stop Lifecycles & State Invariants
# ==============================================================================

def test_rapid_pause_resume_stop_lifecycles():
    section_header("6. Rapid Pause / Resume / Stop Lifecycle Stress Tests")
    temp_dir = tempfile.mkdtemp(prefix="lifecycle_stress_")
    try:
        recorder = VideoRecorder()
        cfg = CaptureConfig(
            video_format=OutputFormat.MP4,
            region=Region(0, 0, 320, 240),
            fps=30,
            output_dir=temp_dir,
        )

        # 1. Sub-second short take (start -> 50ms -> stop)
        print("Testing sub-second short-take recording (50ms duration)...")
        short_mp4 = os.path.join(temp_dir, "short_take.mp4")
        recorder.start(filepath=short_mp4, config=cfg)
        time.sleep(0.05)
        res_short = recorder.stop()
        assert os.path.exists(res_short), "Short take MP4 file missing"
        assert os.path.getsize(res_short) > 0, "Short take MP4 file is empty"
        assert recorder.status == EngineStatus.IDLE

        # 2. Immediate Start -> Pause -> Resume -> Stop (< 100ms)
        print("Testing immediate rapid Start -> Pause -> Resume -> Stop...")
        rapid_mp4 = os.path.join(temp_dir, "rapid_toggle.mp4")
        recorder.start(filepath=rapid_mp4, config=cfg)
        recorder.pause()
        assert recorder.status == EngineStatus.PAUSED
        recorder.resume()
        assert recorder.status == EngineStatus.RECORDING
        res_rapid = recorder.stop()
        assert os.path.exists(res_rapid)
        assert recorder.status == EngineStatus.IDLE

        # 3. Multiple rapid Pause/Resume toggles (5x cycles during 2s)
        print("Testing 5x rapid Pause / Resume toggles...")
        multi_mp4 = os.path.join(temp_dir, "multi_pause.mp4")
        recorder.start(filepath=multi_mp4, config=cfg)
        for i in range(5):
            time.sleep(0.15)
            recorder.pause()
            assert recorder.status == EngineStatus.PAUSED
            time.sleep(0.1)
            recorder.resume()
            assert recorder.status == EngineStatus.RECORDING

        res_multi = recorder.stop()
        assert os.path.exists(res_multi)
        assert os.path.getsize(res_multi) > 2000

        # Verify decoded frames from multi-pause recording
        cap = cv2.VideoCapture(res_multi)
        assert cap.isOpened()
        frames_read = 0
        while True:
            ret, f = cap.read()
            if not ret:
                break
            frames_read += 1
        cap.release()
        print(f"Decoded {frames_read} frames from 5x paused recording.")
        assert frames_read >= 15, f"Expected at least 15 frames, got {frames_read}"

        # 4. Stop while in PAUSED state
        print("Testing stop() directly from PAUSED state...")
        paused_stop_mp4 = os.path.join(temp_dir, "paused_stop.mp4")
        recorder.start(filepath=paused_stop_mp4, config=cfg)
        time.sleep(0.5)
        recorder.pause()
        assert recorder.status == EngineStatus.PAUSED
        res_paused_stop = recorder.stop()
        assert os.path.exists(res_paused_stop)
        assert os.path.getsize(res_paused_stop) > 1000
        assert recorder.status == EngineStatus.IDLE

        # Verify decodability of video stopped while paused
        cap_p = cv2.VideoCapture(res_paused_stop)
        assert cap_p.isOpened(), "Failed to open video stopped while paused"
        ret_p, _ = cap_p.read()
        assert ret_p is True, "Failed to read frame from video stopped while paused"
        cap_p.release()

        # 5. 10 Consecutive Start/Stop cycles (Resource leak & stability stress)
        print("Testing 10 consecutive Start / Stop cycles...")
        for c in range(10):
            c_path = os.path.join(temp_dir, f"cycle_{c:02d}.mp4")
            recorder.start(filepath=c_path, config=cfg)
            time.sleep(0.1)
            out_c = recorder.stop()
            assert os.path.exists(out_c)
            assert recorder.status == EngineStatus.IDLE

        print("10 consecutive recording cycles completed cleanly with zero leaked states.")

        # 6. Invalid state transitions
        print("Testing invalid state transition exception handling...")
        try:
            recorder.pause()
            assert False, "Should have raised RuntimeError on pause() when IDLE"
        except RuntimeError:
            pass

        try:
            recorder.resume()
            assert False, "Should have raised RuntimeError on resume() when IDLE"
        except RuntimeError:
            pass

        try:
            recorder.stop()
            assert False, "Should have raised RuntimeError on stop() when IDLE"
        except RuntimeError:
            pass

        print(">> Rapid Pause / Resume / Stop Lifecycle Stress Tests: PASS")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# MAIN RUNNER
# ==============================================================================

def main():
    print("\n" + "#" * 70)
    print("# CHALLENGER 3 EMPIRICAL & ADVERSARIAL VERIFICATION SUITE")
    print("# Milestone 1: Core Engine & Capture Backends (Iteration 2)")
    print("#" * 70)

    tests = [
        ("Screenshot Fullscreen & Custom ROI", test_screenshot_fullscreen_and_roi),
        ("Inverted/Negative/OOB ROI Normalization", test_screenshot_inverted_negative_and_out_of_bounds_roi),
        ("Image Formats, Magic Bytes & Lossless/Quality", test_image_formats_magic_headers_and_lossless_quality),
        ("MP4 Faststart Moov Atom & OpenCV Decodability", test_mp4_faststart_moov_atom_positioning),
        ("WebM Video Recording & OpenCV Decodability", test_webm_video_recording_and_opencv_decodability),
        ("Rapid Pause/Resume/Stop Lifecycle Stress", test_rapid_pause_resume_stop_lifecycles),
    ]

    passed = 0
    failed = 0
    results: List[Tuple[str, str, Optional[str]]] = []

    for name, fn in tests:
        try:
            fn()
            passed += 1
            results.append((name, "PASS", None))
        except Exception as e:
            failed += 1
            tb = traceback.format_exc()
            results.append((name, "FAIL", tb))
            print(f"\n[!] FAILURE IN TEST: {name}")
            print(tb)

    print("\n" + "=" * 70)
    print("CHALLENGER 3 TEST EXECUTION SUMMARY")
    print("=" * 70)
    for name, status, tb in results:
        print(f"  {name:<50} : [{status}]")

    print(f"\nTotal: {len(tests)} | Passed: {passed} | Failed: {failed}")
    if failed == 0:
        print("\nALL CHALLENGER 3 EMPIRICAL TESTS PASSED WITH 100% SUCCESS!")
        sys.exit(0)
    else:
        print(f"\n{failed} TESTS FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    main()
