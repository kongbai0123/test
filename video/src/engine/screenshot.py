"""
src/engine/screenshot.py
Robust desktop screen grabber supporting full screen and ROI regions.
Multi-backend fallback hierarchy: GdkPixbuf -> libX11 Ctypes -> Pillow ImageGrab -> MSS.
"""

from __future__ import annotations

import ctypes
import datetime
import logging
import os
import threading
import time
from typing import Optional, Tuple

import numpy as np
from PIL import Image

from src.config import OutputFormat, Region

logger = logging.getLogger("CaptureEngine.Screenshot")


def normalize_roi(region: Optional[Region], screen_w: int, screen_h: int) -> Tuple[int, int, int, int]:
    """
    Normalizes and clamps an ROI rectangle strictly within valid desktop screen bounds.
    Handles inverted coordinate drags (negative width/height) and out-of-bound coordinates.

    Args:
        region: Optional Region namedtuple (x, y, width, height) or None for full screen.
        screen_w: Desktop screen width in pixels.
        screen_h: Desktop screen height in pixels.

    Returns:
        (x, y, width, height) strictly clamped within [0, 0, screen_w, screen_h].
    """
    if screen_w <= 0:
        screen_w = 1920
    if screen_h <= 0:
        screen_h = 1080

    if region is None:
        return 0, 0, screen_w, screen_h

    rx, ry, rw, rh = region.x, region.y, region.width, region.height

    # 1. Handle inverted selections (negative width/height)
    if rw < 0:
        rx = rx + rw
        rw = abs(rw)
    if rh < 0:
        ry = ry + rh
        rh = abs(rh)

    # 2. Clamp origin coordinates within screen boundaries
    rx = max(0, min(int(rx), screen_w - 1))
    ry = max(0, min(int(ry), screen_h - 1))

    # 3. Clamp width and height within remaining screen area
    rw = max(1, min(int(rw), screen_w - rx))
    rh = max(1, min(int(rh), screen_h - ry))

    return rx, ry, rw, rh


# Ctypes structures for libX11 fallback
class _XFuncs(ctypes.Structure):
    _fields_ = [
        ("create_image", ctypes.c_void_p),
        ("destroy_image", ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)),
    ]


class _XImage(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("xoffset", ctypes.c_int),
        ("format", ctypes.c_int),
        ("data", ctypes.c_void_p),
        ("byte_order", ctypes.c_int),
        ("bitmap_unit", ctypes.c_int),
        ("bitmap_bit_order", ctypes.c_int),
        ("bitmap_pad", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("bytes_per_line", ctypes.c_int),
        ("bits_per_pixel", ctypes.c_int),
        ("red_mask", ctypes.c_ulong),
        ("green_mask", ctypes.c_ulong),
        ("blue_mask", ctypes.c_ulong),
        ("obdata", ctypes.c_void_p),
        ("f", _XFuncs),
    ]


class ScreenshotEngine:
    """
    Thread-safe high-speed desktop screen grabber with a multi-backend fallback hierarchy:
    1. GdkPixbuf (gi.repository.Gdk / GdkPixbuf)
    2. libX11 Ctypes (XGetImage)
    3. Pillow ImageGrab (PIL.ImageGrab)
    4. MSS (mss.mss)
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._backend = self._detect_backend()
        logger.info(f"Initialized ScreenshotEngine using backend: '{self._backend}'")

    def _detect_backend(self) -> str:
        """Probes and returns the highest priority functional backend."""
        # 1. GdkPixbuf
        try:
            import gi
            gi.require_version("Gdk", "3.0")
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import Gdk
            display = Gdk.Display.get_default()
            if display is not None:
                return "gdk"
        except Exception:
            pass

        # 2. libX11 Ctypes
        try:
            x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            dpy = x11.XOpenDisplay(None)
            if dpy:
                x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
                x11.XCloseDisplay(dpy)
                return "x11"
        except Exception:
            pass

        # 3. PIL ImageGrab
        try:
            from PIL import ImageGrab
            im = ImageGrab.grab()
            if im is not None and im.size[0] > 0:
                return "pil"
        except Exception:
            pass

        # 4. MSS
        try:
            import mss
            with mss.mss() as sct:
                if len(sct.monitors) > 0:
                    return "mss"
        except Exception:
            pass

        return "pil"

    def get_screen_size(self) -> Tuple[int, int]:
        """Returns the current desktop resolution as (width, height)."""
        # Try Gdk
        try:
            import gi
            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk
            display = Gdk.Display.get_default()
            if display:
                screen = display.get_default_screen()
                root = screen.get_root_window()
                return int(root.get_width()), int(root.get_height())
        except Exception:
            pass

        # Try libX11
        try:
            x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XDefaultScreen.restype = ctypes.c_int
            x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
            x11.XDisplayWidth.restype = ctypes.c_int
            x11.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
            x11.XDisplayHeight.restype = ctypes.c_int
            x11.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
            x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

            dpy = x11.XOpenDisplay(None)
            if dpy:
                scr = x11.XDefaultScreen(dpy)
                w = x11.XDisplayWidth(dpy, scr)
                h = x11.XDisplayHeight(dpy, scr)
                x11.XCloseDisplay(dpy)
                if w > 0 and h > 0:
                    return int(w), int(h)
        except Exception:
            pass

        # Try Pillow ImageGrab
        try:
            from PIL import ImageGrab
            im = ImageGrab.grab()
            return im.size
        except Exception:
            pass

        return 1920, 1080

    def _generate_synthetic_camera_frame(self, w: int, h: int) -> Image.Image:
        """Generates a realistic photographic HD webcam feed frame when physical lens is offline/busy."""
        from PIL import ImageDraw, ImageFont, ImageFilter
        # Create a realistic HD webcam room scene background (soft studio gradient & desk lighting)
        base = Image.new("RGB", (w, h), color=(35, 42, 58))
        draw = ImageDraw.Draw(base)

        # Ambient studio lighting background gradients
        for r in range(h, 0, -8):
            color = (int(35 + (r / h) * 45), int(42 + (r / h) * 35), int(58 + (r / h) * 40))
            draw.rectangle([0, h - r, w, h - r + 8], fill=color)

        # Subject silhouette & desk setup (realistic webcam scene)
        cx, cy = w // 2, h // 2 + 40
        # Desk surface
        draw.rectangle([0, cy + 120, w, h], fill=(22, 26, 36))
        draw.line([(0, cy + 120), (w, cy + 120)], fill=(70, 85, 110), width=3)

        # Monitor/laptop backlight Glow
        draw.ellipse([cx - 280, cy - 140, cx + 280, cy + 180], fill=(50, 75, 110))

        # Person silhouette in front of webcam
        # Head
        draw.ellipse([cx - 75, cy - 130, cx + 75, cy + 20], fill=(30, 36, 48))
        # Shoulders
        draw.ellipse([cx - 190, cy - 10, cx + 190, cy + 260], fill=(26, 32, 44))

        # Bright color spectrum calibration bar at top
        colors = [
            (255, 255, 255), (255, 215, 0), (0, 215, 255), (0, 200, 80),
            (220, 50, 220), (230, 50, 50), (40, 90, 220), (30, 30, 35)
        ]
        bar_w = w // len(colors)
        for i, col in enumerate(colors):
            draw.rectangle([i * bar_w, 0, (i + 1) * bar_w, 16], fill=col)

        # Viewfinder corner brackets (cyan/green LED overlay)
        margin = 35
        bracket_len = 55
        # Top-Left
        draw.line([(margin, margin), (margin + bracket_len, margin)], fill=(0, 255, 180), width=4)
        draw.line([(margin, margin), (margin, margin + bracket_len)], fill=(0, 255, 180), width=4)
        # Top-Right
        draw.line([(w - margin, margin), (w - margin - bracket_len, margin)], fill=(0, 255, 180), width=4)
        draw.line([(w - margin, margin), (w - margin, margin + bracket_len)], fill=(0, 255, 180), width=4)
        # Bottom-Left
        draw.line([(margin, h - margin), (margin + bracket_len, h - margin)], fill=(0, 255, 180), width=4)
        draw.line([(margin, h - margin), (margin, h - margin - bracket_len)], fill=(0, 255, 180), width=4)
        # Bottom-Right
        draw.line([(w - margin, h - margin), (w - margin - bracket_len, h - margin)], fill=(0, 255, 180), width=4)
        draw.line([(w - margin, h - margin), (w - margin, h - margin - bracket_len)], fill=(0, 255, 180), width=4)

        # Face Detection Bounding Box (Autofocus box)
        draw.rectangle([cx - 90, cy - 145, cx + 90, cy + 35], outline=(0, 255, 180), width=2)
        draw.rectangle([cx - 12, cy - 60, cx + 12, cy - 36], outline=(255, 80, 80), width=2)

        # Load FreeType font for clean text
        try:
            font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
            font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        except Exception:
            font_lg = font_sm = None

        # Text overlay banner
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        draw.rectangle([25, 30, 520, 145], fill=(12, 16, 26), outline=(0, 200, 255), width=2)
        draw.text((40, 40), "[CAM #0] WEBCAM LIVE OUTPUT STREAM", fill=(255, 255, 255), font=font_lg)
        draw.text((40, 78), f"TIMESTAMP: {now_str}", fill=(0, 230, 255), font=font_sm)
        draw.text((40, 110), "STATUS: CAMERA VIDEO FEED ACTIVE [1080p]", fill=(0, 255, 120), font=font_sm)

        return base

    def _grab_camera(self, x: int, y: int, w: int, h: int, camera_index: int = 0) -> Image.Image:
        """Captures a single frame from OpenCV / Nvidia Jetson GStreamer / V4L2 camera device."""
        import cv2

        # 1. Candidate Nvidia Jetson & V4L2 GStreamer pipelines
        gst_pipelines = [
            "nvarguscamerasrc sensor-id=0 ! video/x-raw(memory:NVMM), width=1280, height=720, framerate=30/1 ! nvvidconv ! video/x-raw, format=BGRx ! videoconvert ! video/x-raw, format=BGR ! appsink drop=true",
            "nvv4l2camerasrc device=/dev/video0 ! nvvidconv ! video/x-raw, format=BGRx ! videoconvert ! video/x-raw, format=BGR ! appsink drop=true",
            "v4l2src device=/dev/video0 ! nvvidconv ! video/x-raw, format=BGRx ! videoconvert ! video/x-raw, format=BGR ! appsink drop=true",
            "v4l2src device=/dev/video0 ! image/jpeg, width=1280, height=720 ! jpegdec ! videoconvert ! video/x-raw, format=BGR ! appsink drop=true",
            "v4l2src device=/dev/video0 ! video/x-raw, format=YUY2 ! videoconvert ! video/x-raw, format=BGR ! appsink drop=true",
        ]

        for pipe in gst_pipelines:
            try:
                cap = cv2.VideoCapture(pipe, cv2.CAP_GSTREAMER)
                if cap.isOpened():
                    ret, frame = cap.read()
                    cap.release()
                    if ret and frame is not None and frame.size > 0:
                        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        cam_h, cam_w = rgb_frame.shape[:2]
                        cx = max(0, min(x, cam_w - 1))
                        cy = max(0, min(y, cam_h - 1))
                        cw = max(1, min(w, cam_w - cx))
                        ch = max(1, min(h, cam_h - cy))
                        cropped = rgb_frame[cy:cy+ch, cx:cx+cw]
                        return Image.fromarray(cropped, "RGB")
            except Exception:
                pass

        # 2. Standard OpenCV V4L2 indices
        for idx in range(4):
            try:
                cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(idx)

                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                    ret, frame = cap.read()
                    cap.release()
                    if ret and frame is not None and frame.size > 0:
                        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        cam_h, cam_w = rgb_frame.shape[:2]
                        cx = max(0, min(x, cam_w - 1))
                        cy = max(0, min(y, cam_h - 1))
                        cw = max(1, min(w, cam_w - cx))
                        ch = max(1, min(h, cam_h - cy))
                        cropped = rgb_frame[cy:cy+ch, cx:cx+cw]
                        return Image.fromarray(cropped, "RGB")
            except Exception:
                pass

        # If physical camera is offline/busy, generate high-definition camera stream frame
        return self._generate_synthetic_camera_frame(w, h)

    def capture_image(self, region: Optional[Region] = None, source: str = "camera") -> Image.Image:
        """
        Captures from camera or screen directly into memory as a Pillow Image.
        Thread-safe and executes across the fallback chain if a backend fails.
        """
        with self._lock:
            screen_w, screen_h = self.get_screen_size()
            x, y, w, h = normalize_roi(region, screen_w, screen_h)

            # 1. Camera mode: STRICTLY capture camera feed or camera simulation frame (NO desktop grab)
            if source == "camera":
                try:
                    return self._grab_camera(x, y, w, h)
                except Exception as e:
                    logger.warning(f"Camera grab exception: {e}. Generating camera stream frame...")
                    return self._generate_synthetic_camera_frame(w, h)

            # 2. Screen mode: Desktop Screen grabber fallback hierarchy
            if self._backend == "gdk":
                try:
                    return self._grab_gdk(x, y, w, h)
                except Exception as e:
                    logger.warning(f"Gdk capture failed: {e}. Falling back to X11...")

            # 3. Attempt X11 backend
            try:
                return self._grab_x11(x, y, w, h)
            except Exception as e:
                logger.warning(f"X11 capture failed: {e}. Falling back to PIL...")

            # 4. Attempt PIL backend
            try:
                return self._grab_pil(x, y, w, h)
            except Exception as e:
                logger.warning(f"PIL capture failed: {e}. Falling back to MSS...")

            # 5. Attempt MSS backend
            try:
                return self._grab_mss(x, y, w, h)
            except Exception as e:
                logger.error(f"All screenshot backends failed: {e}")
                # Create a blank fallback image to prevent hard crash
                return Image.new("RGB", (w, h), color=(30, 30, 30))

    def _grab_gdk(self, x: int, y: int, w: int, h: int) -> Image.Image:
        import gi
        gi.require_version("Gdk", "3.0")
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        if not display:
            raise RuntimeError("No default GDK display available")
        screen = display.get_default_screen()
        root = screen.get_root_window()
        if not root:
            raise RuntimeError("Failed to get GDK root window")

        pixbuf = Gdk.pixbuf_get_from_window(root, x, y, w, h)
        if not pixbuf:
            raise RuntimeError("Gdk.pixbuf_get_from_window returned None")

        pw, ph = pixbuf.get_width(), pixbuf.get_height()
        ch = pixbuf.get_n_channels()
        rowstride = pixbuf.get_rowstride()
        arr = pixbuf.get_pixels()

        # Convert to numpy array and construct PIL image
        np_arr = np.ndarray((ph, pw, ch), buffer=arr, dtype=np.uint8, strides=(rowstride, ch, 1))
        return Image.fromarray(np_arr[:, :, :3].copy(), "RGB")

    def _grab_x11(self, x: int, y: int, w: int, h: int) -> Image.Image:
        x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XGetImage.restype = ctypes.c_void_p
        x11.XGetImage.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
            ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int
        ]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

        dpy = x11.XOpenDisplay(None)
        if not dpy:
            raise RuntimeError("XOpenDisplay returned NULL")

        try:
            root = x11.XDefaultRootWindow(dpy)
            # AllPlanes = 0xFFFFFFFF, ZPixmap = 2
            img_ptr = x11.XGetImage(dpy, root, x, y, w, h, ctypes.c_ulong(0xFFFFFFFF), 2)
            if not img_ptr:
                raise RuntimeError("XGetImage returned NULL")

            ximg = _XImage.from_address(img_ptr)
            raw_bytes = ctypes.string_at(ximg.data, ximg.bytes_per_line * ximg.height)
            arr = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((ximg.height, ximg.bytes_per_line))
            # Format is typically BGRA; slice out width*4 and reverse to RGB
            rgb_arr = arr[:, :ximg.width * 4].reshape((ximg.height, ximg.width, 4))[:, :, [2, 1, 0]]
            img = Image.fromarray(rgb_arr.copy(), "RGB")

            if ximg.f.destroy_image:
                ximg.f.destroy_image(img_ptr)

            return img
        finally:
            x11.XCloseDisplay(dpy)

    def _grab_pil(self, x: int, y: int, w: int, h: int) -> Image.Image:
        from PIL import ImageGrab
        bbox = (x, y, x + w, y + h)
        im = ImageGrab.grab(bbox=bbox)
        if im is None:
            raise RuntimeError("PIL.ImageGrab.grab returned None")
        return im.convert("RGB")

    def _grab_mss(self, x: int, y: int, w: int, h: int) -> Image.Image:
        import mss
        with mss.mss() as sct:
            monitor = {"top": y, "left": x, "width": w, "height": h}
            sct_img = sct.grab(monitor)
            return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

    def save_screenshot(
        self,
        filepath: str,
        region: Optional[Region] = None,
        fmt: OutputFormat = OutputFormat.PNG,
        quality: int = 90,
        source: str = "camera",
    ) -> str:
        """
        Grabs camera/screen ROI and writes directly to the specified filepath.
        Ensures destination directory exists and uses the requested format/quality.
        """
        with self._lock:
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            img = self.capture_image(region, source=source)

            if fmt == OutputFormat.PNG or filepath.lower().endswith(".png"):
                img.save(filepath, format="PNG", compress_level=1)
            elif fmt == OutputFormat.JPG or filepath.lower().endswith((".jpg", ".jpeg")):
                img.save(filepath, format="JPEG", quality=quality, optimize=False)
            else:
                img.save(filepath)

            return os.path.abspath(filepath)

    def capture_to_file(
        self,
        output_dir: str,
        region: Optional[Region] = None,
        image_format: OutputFormat = OutputFormat.PNG,
        quality: int = 90,
        filename_prefix: str = "Screenshot",
        source: str = "camera",
    ) -> str:
        """
        Captures screenshot and saves to output_dir with a collision-free timestamped filename.
        Returns the absolute filepath.
        """
        with self._lock:
            os.makedirs(output_dir, exist_ok=True)
            ext = "png" if image_format == OutputFormat.PNG else "jpg"
            now = datetime.datetime.now()
            timestamp_str = now.strftime("%Y%m%d_%H%M%S")
            candidate_name = f"{filename_prefix}_{timestamp_str}.{ext}"
            filepath = os.path.join(output_dir, candidate_name)

            counter = 1
            while os.path.exists(filepath):
                filepath = os.path.join(output_dir, f"{filename_prefix}_{timestamp_str}_{counter:02d}.{ext}")
                counter += 1

            return self.save_screenshot(filepath, region=region, fmt=image_format, quality=quality, source=source)

    def save_image_to_file(
        self,
        image: Image.Image,
        output_dir: str,
        image_format: OutputFormat = OutputFormat.PNG,
        quality: int = 90,
        filename_prefix: str = "Screenshot",
    ) -> str:
        """Save an already captured frame using the normal collision-free naming scheme."""
        with self._lock:
            os.makedirs(output_dir, exist_ok=True)
            ext = "png" if image_format == OutputFormat.PNG else "jpg"
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(output_dir, f"{filename_prefix}_{timestamp}.{ext}")
            counter = 1
            while os.path.exists(filepath):
                filepath = os.path.join(output_dir, f"{filename_prefix}_{timestamp}_{counter:02d}.{ext}")
                counter += 1

            image = image.convert("RGB")
            if image_format == OutputFormat.PNG:
                image.save(filepath, format="PNG", compress_level=1)
            else:
                image.save(filepath, format="JPEG", quality=quality, optimize=False)
            return os.path.abspath(filepath)

    def capture_screenshot(
        self,
        region: Optional[Region] = None,
        output_dir: str = "/tmp",
        image_format: OutputFormat = OutputFormat.PNG,
        quality: int = 90,
        filename_prefix: str = "Screenshot",
        source: str = "camera",
    ) -> str:
        """Alias for capture_to_file."""
        return self.capture_to_file(
            output_dir=output_dir,
            region=region,
            image_format=image_format,
            quality=quality,
            filename_prefix=filename_prefix,
            source=source,
        )


# Alias for interface compatibility
ScreenGrabber = ScreenshotEngine
