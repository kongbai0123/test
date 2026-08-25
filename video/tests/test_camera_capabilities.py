"""Focused tests for the unified camera capability contract."""

import copy
import errno
import unittest
from fractions import Fraction
from unittest.mock import MagicMock, patch

from src.engine.camera import CameraStream
from src.engine import camera_capabilities as capabilities_module
from src.engine.camera_capabilities import (
    VIDIOC_ENUM_FMT,
    VIDIOC_ENUM_FRAMEINTERVALS,
    VIDIOC_ENUM_FRAMESIZES,
    VIDIOC_QUERYCAP,
    enumerate_v4l2_capabilities,
    normalize_nvidia_capabilities,
    select_mode_for_fps,
)


def _os_error(number=errno.EINVAL):
    return OSError(number, "mock ioctl boundary")


def _write_c_string(target, value):
    encoded = value.encode("ascii")
    for index, byte in enumerate(encoded):
        target[index] = byte


class TestV4L2CapabilityEnumeration(unittest.TestCase):
    def test_linux_ioctl_numbers_match_videodev2_contract(self):
        self.assertEqual(VIDIOC_QUERYCAP, 0x80685600)
        self.assertEqual(VIDIOC_ENUM_FMT, 0xC0405602)
        self.assertEqual(VIDIOC_ENUM_FRAMESIZES, 0xC02C564A)
        self.assertEqual(VIDIOC_ENUM_FRAMEINTERVALS, 0xC034564B)

    def test_discrete_formats_sizes_and_rational_fps_are_preserved(self):
        def ioctl_side_effect(fd, request, value):
            self.assertEqual(fd, 17)
            if request == VIDIOC_QUERYCAP:
                _write_c_string(value.driver, "uvcvideo")
                _write_c_string(value.card, "USB Test Camera")
                _write_c_string(value.bus_info, "usb-1-2")
                value.capabilities = capabilities_module.V4L2_CAP_VIDEO_CAPTURE
                return
            if request == VIDIOC_ENUM_FMT:
                if value.index:
                    raise _os_error()
                value.pixelformat = int.from_bytes(b"MJPG", "little")
                value.flags = capabilities_module.V4L2_FMT_FLAG_COMPRESSED
                _write_c_string(value.description, "Motion-JPEG")
                return
            if request == VIDIOC_ENUM_FRAMESIZES:
                sizes = ((1920, 1080), (1280, 720))
                if value.index >= len(sizes):
                    raise _os_error()
                value.type = capabilities_module.V4L2_FRMSIZE_TYPE_DISCRETE
                value.discrete.width, value.discrete.height = sizes[value.index]
                return
            if request == VIDIOC_ENUM_FRAMEINTERVALS:
                fps_by_size = {
                    (1920, 1080): (Fraction(15), Fraction(30000, 1001)),
                    (1280, 720): (Fraction(30), Fraction(60)),
                }
                values = fps_by_size[(value.width, value.height)]
                if value.index >= len(values):
                    raise _os_error()
                fps = values[value.index]
                value.type = capabilities_module.V4L2_FRMIVAL_TYPE_DISCRETE
                value.discrete.numerator = fps.denominator
                value.discrete.denominator = fps.numerator
                return
            self.fail(f"unexpected ioctl request {request:#x}")

        with patch.object(
            capabilities_module, "is_usb_video_device", return_value=True
        ), patch.object(capabilities_module.os, "open", return_value=17), patch.object(
            capabilities_module.os, "close"
        ) as close_device, patch.object(
            capabilities_module, "_ioctl_struct", side_effect=ioctl_side_effect
        ):
            result = enumerate_v4l2_capabilities("/dev/video2")

        close_device.assert_called_once_with(17)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["device"]["backend"], "usb_v4l2")
        self.assertEqual(result["device"]["name"], "USB Test Camera")
        self.assertEqual(result["provenance"], "v4l2_ioctl")
        self.assertEqual(len(result["modes"]), 2)
        full_hd = result["modes"][0]
        self.assertEqual((full_hd["width"], full_hd["height"]), (1920, 1080))
        self.assertEqual(full_hd["pixel_format"], "MJPG")
        self.assertTrue(full_hd["compressed"])
        self.assertEqual(full_hd["fps_type"], "discrete")
        self.assertIn(
            {"numerator": 30000, "denominator": 1001},
            full_hd["fps_values"],
        )
        self.assertFalse(result["integer_fps_only"])

    def test_stepwise_size_and_fps_ranges_retain_interval_precision(self):
        def ioctl_side_effect(fd, request, value):
            if request == VIDIOC_QUERYCAP:
                _write_c_string(value.driver, "uvcvideo")
                _write_c_string(value.card, "Range Camera")
                value.capabilities = capabilities_module.V4L2_CAP_VIDEO_CAPTURE
                return
            if request == VIDIOC_ENUM_FMT:
                if value.index:
                    raise _os_error()
                value.pixelformat = int.from_bytes(b"YUYV", "little")
                return
            if request == VIDIOC_ENUM_FRAMESIZES:
                if value.index:
                    raise _os_error()
                value.type = capabilities_module.V4L2_FRMSIZE_TYPE_STEPWISE
                value.stepwise.min_width = 320
                value.stepwise.max_width = 1920
                value.stepwise.step_width = 16
                value.stepwise.min_height = 240
                value.stepwise.max_height = 1080
                value.stepwise.step_height = 8
                return
            if request == VIDIOC_ENUM_FRAMEINTERVALS:
                if value.index:
                    raise _os_error()
                value.type = capabilities_module.V4L2_FRMIVAL_TYPE_STEPWISE
                value.stepwise.min.numerator = 1
                value.stepwise.min.denominator = 60
                value.stepwise.max.numerator = 1
                value.stepwise.max.denominator = 5
                value.stepwise.step.numerator = 1
                value.stepwise.step.denominator = 120
                return
            self.fail(f"unexpected ioctl request {request:#x}")

        with patch.object(
            capabilities_module, "is_usb_video_device", return_value=True
        ), patch.object(capabilities_module.os, "open", return_value=18), patch.object(
            capabilities_module.os, "close"
        ), patch.object(
            capabilities_module, "_ioctl_struct", side_effect=ioctl_side_effect
        ):
            result = enumerate_v4l2_capabilities("/dev/video4")

        mode = result["modes"][0]
        self.assertEqual(mode["size_type"], "stepwise")
        self.assertEqual(
            mode["size_range"],
            {
                "min_width": 320,
                "max_width": 1920,
                "step_width": 16,
                "min_height": 240,
                "max_height": 1080,
                "step_height": 8,
            },
        )
        self.assertEqual(mode["fps_type"], "range")
        self.assertEqual((mode["min_fps"], mode["max_fps"]), (5, 60))
        self.assertEqual(mode["fps_range"]["kind"], "stepwise")
        self.assertEqual(
            mode["fps_range"]["frame_interval"]["step"],
            {"numerator": 1, "denominator": 120},
        )

    def test_continuous_range_is_distinct_from_stepwise(self):
        def ioctl_side_effect(fd, request, value):
            if request == VIDIOC_QUERYCAP:
                value.capabilities = capabilities_module.V4L2_CAP_VIDEO_CAPTURE
                return
            if request == VIDIOC_ENUM_FMT:
                if value.index:
                    raise _os_error()
                value.pixelformat = int.from_bytes(b"YUYV", "little")
                return
            if request == VIDIOC_ENUM_FRAMESIZES:
                if value.index:
                    raise _os_error()
                value.type = capabilities_module.V4L2_FRMSIZE_TYPE_CONTINUOUS
                value.stepwise.min_width = 160
                value.stepwise.max_width = 640
                value.stepwise.min_height = 120
                value.stepwise.max_height = 480
                return
            if request == VIDIOC_ENUM_FRAMEINTERVALS:
                if value.index:
                    raise _os_error()
                value.type = capabilities_module.V4L2_FRMIVAL_TYPE_CONTINUOUS
                value.stepwise.min.numerator = 1
                value.stepwise.min.denominator = 30
                value.stepwise.max.numerator = 1
                value.stepwise.max.denominator = 10
                return
            self.fail(f"unexpected ioctl request {request:#x}")

        with patch.object(
            capabilities_module, "is_usb_video_device", return_value=True
        ), patch.object(capabilities_module.os, "open", return_value=19), patch.object(
            capabilities_module.os, "close"
        ), patch.object(
            capabilities_module, "_ioctl_struct", side_effect=ioctl_side_effect
        ):
            result = enumerate_v4l2_capabilities("/dev/video6")

        mode = result["modes"][0]
        self.assertEqual(mode["size_type"], "continuous")
        self.assertEqual(mode["fps_range"]["kind"], "continuous")
        self.assertEqual((mode["min_fps"], mode["max_fps"]), (10, 30))

    def test_ioctl_open_failure_returns_explicit_unverified_fallback(self):
        with patch.object(
            capabilities_module, "is_usb_video_device", return_value=True
        ), patch.object(
            capabilities_module.os,
            "open",
            side_effect=PermissionError(errno.EACCES, "denied"),
        ), patch.object(capabilities_module.os.path, "exists", return_value=True):
            result = enumerate_v4l2_capabilities(
                "/dev/video2", fallback_width=800, fallback_height=600, fallback_fps=25
            )

        self.assertEqual(result["provenance"], "fallback")
        self.assertEqual(result["device"]["status"], "unverified")
        self.assertEqual(result["modes"][0]["status"], "unverified")
        self.assertEqual(result["modes"][0]["fps_type"], "unknown")
        self.assertEqual(result["errors"], ["open_failed:13"])

    def test_non_usb_node_is_excluded_before_open(self):
        with patch.object(
            capabilities_module, "is_usb_video_device", return_value=False
        ), patch.object(capabilities_module.os, "open") as open_device:
            result = enumerate_v4l2_capabilities("/dev/video0")

        open_device.assert_not_called()
        self.assertEqual(result["device"]["status"], "excluded_non_usb")
        self.assertEqual(result["modes"], [])


class TestCapabilityNormalizationAndSelection(unittest.TestCase):
    def test_new_nvidia_schema_preserves_hardware_provenance_and_native_fields(self):
        payload = {
            "schema_version": 2,
            "device": {
                "id": "csi:imx219:0",
                "name": "IMX219",
                "backend": "libargus",
                "sensor_id": 0,
            },
            "provenance": "libargus",
            "integer_fps_only": False,
            "modes": [
                {
                    "id": "sensor-mode-0",
                    "sensor_mode_index": 0,
                    "native_width": 3280,
                    "native_height": 2464,
                    "width": 3280,
                    "height": 2464,
                    "min_fps": {"numerator": 2, "denominator": 1},
                    "max_fps": {"numerator": 210, "denominator": 10},
                    "pixel_format": "NV12",
                    "provenance": "libargus",
                }
            ],
            "current": {"width": 1280, "height": 720, "fps": 21},
        }

        result = normalize_nvidia_capabilities(payload, connected=True)

        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["provenance"], "libargus")
        self.assertEqual(result["device"]["id"], "csi:imx219:0")
        self.assertEqual(result["device"]["sensor_id"], 0)
        mode = result["modes"][0]
        self.assertEqual(mode["sensor_mode_index"], 0)
        self.assertEqual((mode["native_width"], mode["native_height"]), (3280, 2464))
        self.assertEqual(mode["max_fps"], 21)
        self.assertEqual(
            mode["max_fps_rational"], {"numerator": 21, "denominator": 1}
        )

    def test_discrete_selector_uses_nearest_lower_tie_then_max_pixels(self):
        capabilities = {
            "provenance": "v4l2_ioctl",
            "modes": [
                {
                    "id": "full-hd",
                    "width": 1920,
                    "height": 1080,
                    "pixel_format": "MJPG",
                    "compressed": True,
                    "min_fps": 15,
                    "max_fps": 30,
                    "fps_values": [
                        {"numerator": 15, "denominator": 1},
                        {"numerator": 30, "denominator": 1},
                    ],
                    "fps_type": "discrete",
                    "provenance": "v4l2_ioctl",
                    "status": "declared",
                },
                {
                    "id": "hd",
                    "width": 1280,
                    "height": 720,
                    "pixel_format": "MJPG",
                    "compressed": True,
                    "min_fps": 30,
                    "max_fps": 60,
                    "fps_values": [
                        {"numerator": 30, "denominator": 1},
                        {"numerator": 60, "denominator": 1},
                    ],
                    "fps_type": "discrete",
                    "provenance": "v4l2_ioctl",
                    "status": "declared",
                },
            ],
        }

        selection = select_mode_for_fps(capabilities, 45)

        self.assertEqual(selection["fps"], 30)
        self.assertEqual(selection["mode_id"], "full-hd")
        self.assertTrue(selection["clamped"])
        self.assertTrue(selection["snapped"])

    def test_zero_and_negative_requests_clamp_to_discrete_minimum(self):
        capabilities = {
            "modes": [
                {
                    "id": "bounded",
                    "width": 1920,
                    "height": 1080,
                    "pixel_format": "MJPG",
                    "min_fps": 15,
                    "max_fps": 30,
                    "fps_values": [
                        {"numerator": 15, "denominator": 1},
                        {"numerator": 30, "denominator": 1},
                    ],
                    "fps_type": "discrete",
                    "provenance": "v4l2_ioctl",
                    "status": "declared",
                }
            ]
        }

        for requested in (-10, 0):
            with self.subTest(requested=requested):
                selection = select_mode_for_fps(capabilities, requested)
                self.assertEqual(selection["requested_fps"], requested)
                self.assertEqual(selection["fps"], 15)
                self.assertTrue(selection["clamped"])
                self.assertTrue(selection["snapped"])

    def test_selector_prefers_mjpeg_at_equal_pixels_and_fps(self):
        base_mode = {
            "width": 1280,
            "height": 720,
            "min_fps": 30,
            "max_fps": 30,
            "fps_values": [{"numerator": 30, "denominator": 1}],
            "fps_type": "discrete",
            "provenance": "v4l2_ioctl",
            "status": "declared",
        }
        yuyv = dict(base_mode, id="raw", pixel_format="YUYV", compressed=False)
        mjpg = dict(base_mode, id="compressed", pixel_format="MJPG", compressed=True)

        selection = select_mode_for_fps({"modes": [yuyv, mjpg]}, 30)

        self.assertEqual(selection["mode_id"], "compressed")
        self.assertEqual(selection["pixel_format"], "MJPG")

    def test_range_selector_clamps_then_chooses_highest_supported_pixels(self):
        capabilities = {
            "provenance": "libargus",
            "modes": [
                {
                    "id": "large",
                    "width": 3280,
                    "height": 2464,
                    "pixel_format": "NV12",
                    "min_fps": 2,
                    "max_fps": 21,
                    "fps_values": [],
                    "fps_type": "range",
                    "provenance": "libargus",
                    "status": "declared",
                },
                {
                    "id": "fast",
                    "width": 1280,
                    "height": 720,
                    "pixel_format": "NV12",
                    "min_fps": 2,
                    "max_fps": 60,
                    "fps_values": [],
                    "fps_type": "range",
                    "provenance": "libargus",
                    "status": "declared",
                },
            ],
        }

        at_20 = select_mode_for_fps(capabilities, 20)
        at_45 = select_mode_for_fps(capabilities, 45)
        at_100 = select_mode_for_fps(capabilities, 100)

        self.assertEqual(at_20["mode_id"], "large")
        self.assertEqual(at_45["mode_id"], "fast")
        self.assertEqual(at_45["fps"], 45)
        self.assertEqual(at_100["fps"], 60)
        self.assertTrue(at_100["clamped"])
        self.assertFalse(at_100["snapped"])

    def test_stepwise_interval_selector_snaps_to_reciprocal_legal_fps(self):
        capabilities = {
            "provenance": "v4l2_ioctl",
            "modes": [
                {
                    "id": "stepwise",
                    "width": 1280,
                    "height": 720,
                    "pixel_format": "YUYV",
                    "min_fps": 5,
                    "max_fps": 60,
                    "fps_values": [],
                    "fps_type": "range",
                    "fps_range": {
                        "kind": "stepwise",
                        "min": {"numerator": 5, "denominator": 1},
                        "max": {"numerator": 60, "denominator": 1},
                        "frame_interval": {
                            "min": {"numerator": 1, "denominator": 60},
                            "max": {"numerator": 1, "denominator": 5},
                            "step": {"numerator": 1, "denominator": 120},
                        },
                    },
                    "provenance": "v4l2_ioctl",
                    "status": "declared",
                }
            ],
        }

        tie = select_mode_for_fps(capabilities, 50)
        closer_to_fast = select_mode_for_fps(capabilities, 55)

        # Legal frame intervals are 2/120, 3/120, ... seconds.  Therefore
        # 50 FPS is not legal; 40 and 60 are equally distant and lower wins.
        self.assertEqual(tie["fps"], 40)
        self.assertTrue(tie["clamped"])
        self.assertTrue(tie["snapped"])
        self.assertEqual(closer_to_fast["fps"], 60)
        self.assertEqual(select_mode_for_fps(capabilities, 0)["fps"], 5)
        self.assertEqual(select_mode_for_fps(capabilities, -10)["fps"], 5)

    def test_camera_stream_capability_snapshot_is_thread_safe_and_adds_measurement(self):
        stream = CameraStream()
        declared = normalize_nvidia_capabilities(
            {
                "min_fps": 2,
                "max_fps": 60,
                "modes": [
                    {"width": 1280, "height": 720, "min_fps": 2, "max_fps": 60}
                ],
                "current": {"width": 1280, "height": 720, "fps": 30},
            },
            connected=True,
        )
        with stream._lock:
            stream._capabilities = copy.deepcopy(declared)
            stream._connected = True
            stream._measured_fps = 29.8754

        first = stream.capabilities
        first["modes"].clear()
        second = stream.capabilities

        self.assertEqual(len(second["modes"]), 1)
        self.assertTrue(second["device"]["connected"])
        self.assertEqual(second["current"]["measured_fps"], 29.875)
        self.assertEqual(second["current"]["status"], "receiving")


if __name__ == "__main__":
    unittest.main()
