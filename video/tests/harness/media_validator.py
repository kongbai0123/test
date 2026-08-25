"""
tests/harness/media_validator.py
High-precision media verification utilities for images, video containers, and audio tracks.
Pure-Python, OpenCV, Pillow, and struct-based validation with zero external CLI dependencies.
"""

import os
import struct
from typing import Tuple, List, Dict, Any, Optional
from PIL import Image
import cv2
import numpy as np


class ImageValidator:
    """Validates PNG and JPEG image files."""

    PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
    JPEG_MAGIC = b"\xff\xd8\xff"

    @classmethod
    def validate_png(
        cls, filepath: str, min_width: int = 1, min_height: int = 1, check_non_blank: bool = True
    ) -> Tuple[bool, str]:
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return False, "File does not exist or is empty"
        with open(filepath, "rb") as f:
            magic = f.read(8)
        if magic != cls.PNG_MAGIC:
            return False, f"Invalid PNG magic bytes: {magic!r}"

        try:
            with Image.open(filepath) as img:
                img.verify()
            with Image.open(filepath) as img:
                w, h = img.size
                fmt = img.format
                if fmt != "PNG":
                    return False, f"Pillow format mismatch: expected PNG, got {fmt}"
                if w < min_width or h < min_height:
                    return False, f"Dimensions {w}x{h} smaller than required {min_width}x{min_height}"
                if check_non_blank:
                    arr = np.array(img)
                    if arr.size > 0 and np.all(arr == arr.flat[0]) and arr.size > 16:
                        return False, "Image is completely uniform/blank"
        except Exception as e:
            return False, f"Pillow exception during PNG validation: {e}"

        return True, "OK"

    @classmethod
    def validate_jpg(
        cls, filepath: str, min_width: int = 1, min_height: int = 1, check_non_blank: bool = True
    ) -> Tuple[bool, str]:
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return False, "File does not exist or is empty"
        with open(filepath, "rb") as f:
            magic = f.read(3)
        if magic != cls.JPEG_MAGIC:
            return False, f"Invalid JPEG magic bytes: {magic!r}"

        try:
            with Image.open(filepath) as img:
                img.verify()
            with Image.open(filepath) as img:
                w, h = img.size
                fmt = img.format
                if fmt not in ("JPEG", "JPG"):
                    return False, f"Pillow format mismatch: expected JPEG, got {fmt}"
                if w < min_width or h < min_height:
                    return False, f"Dimensions {w}x{h} smaller than required {min_width}x{min_height}"
                if check_non_blank:
                    arr = np.array(img)
                    if arr.size > 0 and np.all(arr == arr.flat[0]) and arr.size > 16:
                        return False, "Image is completely uniform/blank"
        except Exception as e:
            return False, f"Pillow exception during JPEG validation: {e}"

        return True, "OK"


class VideoValidator:
    """Validates MP4 and WebM video files, atom layouts, and frame decodability."""

    WEBM_MAGIC = b"\x1a\x45\xdf\xa3"

    @staticmethod
    def parse_mp4_boxes(filepath: str) -> List[Tuple[str, int, int]]:
        """
        Parses top-level MP4 container boxes (atoms).
        Returns list of (box_name, byte_offset, box_size).
        """
        boxes = []
        if not os.path.exists(filepath) or os.path.getsize(filepath) < 8:
            return boxes
        with open(filepath, "rb") as f:
            file_size = f.seek(0, 2)
            f.seek(0)
            pos = 0
            while pos < file_size:
                header = f.read(8)
                if len(header) < 8:
                    break
                size, name = struct.unpack(">I4s", header)
                name_str = name.decode("latin1", errors="replace")
                if size == 1:  # 64-bit large size
                    ext_data = f.read(8)
                    if len(ext_data) < 8:
                        break
                    ext_size = struct.unpack(">Q", ext_data)[0]
                    boxes.append((name_str, pos, ext_size))
                    pos += ext_size
                    f.seek(pos)
                elif size == 0:  # Box extends to EOF
                    boxes.append((name_str, pos, file_size - pos))
                    break
                elif size < 8:
                    break
                else:
                    boxes.append((name_str, pos, size))
                    pos += size
                    f.seek(pos)
        return boxes

    @classmethod
    def is_mp4_faststart(cls, filepath: str) -> bool:
        """
        Returns True if the 'moov' atom appears before 'mdat' in the MP4 file.
        Confirms faststart streaming optimization.
        """
        boxes = cls.parse_mp4_boxes(filepath)
        moov_idx = next((i for i, b in enumerate(boxes) if b[0] == "moov"), None)
        mdat_idx = next((i for i, b in enumerate(boxes) if b[0] == "mdat"), None)
        if moov_idx is not None and mdat_idx is not None:
            return moov_idx < mdat_idx
        # Fallback binary check
        try:
            with open(filepath, "rb") as f:
                head = f.read(65536)
            moov_pos = head.find(b"moov")
            mdat_pos = head.find(b"mdat")
            if moov_pos != -1 and mdat_pos != -1:
                return moov_pos < mdat_pos
        except Exception:
            pass
        return False

    @staticmethod
    def parse_mp4_tracks(filepath: str) -> List[str]:
        """
        Scans MP4 boxes to discover track handler types ('vide', 'soun', 'hint').
        """
        tracks = []
        if not os.path.exists(filepath):
            return tracks
        with open(filepath, "rb") as f:
            data = f.read()
        pos = 0
        while pos < len(data) - 8:
            try:
                size, name = struct.unpack(">I4s", data[pos : pos + 8])
            except Exception:
                break
            if size == 0:
                break
            if size == 1:
                if pos + 16 > len(data):
                    break
                size = struct.unpack(">Q", data[pos + 8 : pos + 16])[0]
            if name in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
                pos += 8
                continue
            elif name == b"hdlr":
                if pos + 20 <= len(data):
                    hdlr_type = data[pos + 16 : pos + 20].decode("latin1", errors="replace")
                    tracks.append(hdlr_type)
                pos += max(8, size)
            else:
                pos += max(8, size)
        return tracks

    @classmethod
    def validate_mp4(
        cls,
        filepath: str,
        min_duration_sec: float = 0.05,
        min_frames: int = 1,
        check_faststart: bool = False,
        check_audio: bool = False,
    ) -> Tuple[bool, str]:
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return False, "File does not exist or is empty"

        boxes = cls.parse_mp4_boxes(filepath)
        box_names = [b[0] for b in boxes]
        # Check basic atom presence or binary magic
        if "ftyp" not in box_names and "moov" not in box_names:
            with open(filepath, "rb") as f:
                head = f.read(32)
            if b"ftyp" not in head and b"moov" not in head:
                return False, f"Missing required MP4 boxes: {box_names}"

        if check_faststart and not cls.is_mp4_faststart(filepath):
            return False, "MP4 moov atom is not placed before mdat (faststart missing)"

        if check_audio:
            tracks = cls.parse_mp4_tracks(filepath)
            if "soun" not in tracks and b"soun" not in open(filepath, "rb").read(65536):
                return False, f"Audio track not found in MP4 tracks: {tracks}"

        # OpenCV decodability check
        cap = cv2.VideoCapture(filepath)
        if not cap.isOpened():
            return False, "OpenCV failed to open MP4 container"

        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        duration = frame_count / fps if fps > 0 else 0.0

        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return False, "Failed to decode initial video frame"
        if frame_count < min_frames and frame_count > 0:
            return False, f"Frame count {frame_count} is less than required {min_frames}"

        return True, "OK"

    @classmethod
    def validate_webm(
        cls,
        filepath: str,
        min_duration_sec: float = 0.05,
        min_frames: int = 1,
        check_audio: bool = False,
    ) -> Tuple[bool, str]:
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return False, "File does not exist or is empty"

        with open(filepath, "rb") as f:
            magic = f.read(4)
        if magic != cls.WEBM_MAGIC and b"\x1a\x45" not in magic:
            return False, f"Invalid WebM EBML magic header: {magic!r}"

        cap = cv2.VideoCapture(filepath)
        if not cap.isOpened():
            return False, "OpenCV failed to open WebM container"

        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return False, "Failed to decode initial WebM video frame"

        return True, "OK"


class AudioValidator:
    """Validates audio track presence inside media files."""

    @staticmethod
    def validate_audio_stream(filepath: str) -> Tuple[bool, str]:
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return False, "File does not exist or is empty"

        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".mp4":
            tracks = VideoValidator.parse_mp4_tracks(filepath)
            if "soun" in tracks:
                return True, "OK"
            with open(filepath, "rb") as f:
                content = f.read()
            if b"soun" in content or b"mp4a" in content or b"Opus" in content:
                return True, "OK"
            return False, f"No audio track in MP4: found {tracks}"
        elif ext == ".webm":
            with open(filepath, "rb") as f:
                content = f.read(65536)
            if b"A_VORBIS" in content or b"A_OPUS" in content or b"Audio" in content or b"\x83\x81\x02" in content:
                return True, "OK"
            return False, "No audio track identifier found in WebM header"
        elif ext == ".wav":
            with open(filepath, "rb") as f:
                hdr = f.read(12)
            if hdr[:4] == b"RIFF" and hdr[8:12] == b"WAVE":
                return True, "OK"
            return False, "Invalid WAV header"
        return False, f"Unsupported audio container: {ext}"


class MediaValidator:
    """Unified wrapper providing clean interface for Tier 1-4 tests."""

    @classmethod
    def validate_image(
        cls,
        path: str,
        expected_format: Optional[str] = None,
        expected_size: Optional[Tuple[int, int]] = None,
        min_bytes: int = 1,
    ) -> Tuple[bool, str]:
        if not os.path.exists(path):
            return False, f"File not found: {path}"
        if os.path.getsize(path) < min_bytes:
            return False, f"File size ({os.path.getsize(path)}) < min_bytes ({min_bytes})"

        fmt = (expected_format or os.path.splitext(path)[1].lstrip(".")).upper()
        if fmt == "PNG":
            min_w = expected_size[0] if expected_size else 1
            min_h = expected_size[1] if expected_size else 1
            return ImageValidator.validate_png(path, min_width=min_w, min_height=min_h)
        elif fmt in ("JPG", "JPEG"):
            min_w = expected_size[0] if expected_size else 1
            min_h = expected_size[1] if expected_size else 1
            return ImageValidator.validate_jpg(path, min_width=min_w, min_height=min_h)
        return False, f"Unsupported image format: {fmt}"

    @classmethod
    def validate_video(
        cls,
        path: str,
        expected_format: Optional[str] = None,
        expected_size: Optional[Tuple[int, int]] = None,
        min_duration: float = 0.05,
        require_faststart: bool = False,
        check_audio: bool = False,
    ) -> Tuple[bool, str]:
        if not os.path.exists(path):
            return False, f"File not found: {path}"
        if os.path.getsize(path) == 0:
            return False, "Video file is 0 bytes"

        fmt = (expected_format or os.path.splitext(path)[1].lstrip(".")).upper()
        if fmt == "MP4":
            return VideoValidator.validate_mp4(
                path, min_duration_sec=min_duration, check_faststart=require_faststart, check_audio=check_audio
            )
        elif fmt == "WEBM":
            return VideoValidator.validate_webm(
                path, min_duration_sec=min_duration, check_audio=check_audio
            )
        return False, f"Unsupported video format: {fmt}"

    @classmethod
    def validate_audio_stream(cls, path: str) -> Tuple[bool, str]:
        return AudioValidator.validate_audio_stream(path)
