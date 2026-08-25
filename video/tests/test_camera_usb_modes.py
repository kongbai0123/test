"""USB mode application, validation and lifecycle-race regression tests."""

import copy
import threading
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from src.engine.camera import CameraStream


def _usb_capabilities():
    return {
        "schema_version": 1,
        "device": {
            "id": "usb:test",
            "name": "USB Test Camera",
            "backend": "usb_v4l2",
            "path": "/dev/video2",
            "connected": False,
        },
        "provenance": "v4l2_ioctl",
        "min_fps": 30,
        "max_fps": 30,
        "integer_fps_only": True,
        "selection_rule": "highest_pixel_mode_supporting_requested_fps",
        "modes": [
            {
                "id": "mjpg-full-hd",
                "width": 1920,
                "height": 1080,
                "pixel_format": "MJPG",
                "compressed": True,
                "min_fps": 30,
                "max_fps": 30,
                "fps_values": [{"numerator": 30, "denominator": 1}],
                "fps_type": "discrete",
                "provenance": "v4l2_ioctl",
                "status": "declared",
            }
        ],
        "current": {
            "width": 640,
            "height": 480,
            "fps": 30,
            "pixel_format": "MJPG",
            "status": "last_negotiated",
        },
    }


class FakeCapture:
    def __init__(self, frame, properties, read_hook=None):
        self.frame = frame
        self.properties = properties
        self.read_hook = read_hook
        self.released = False
        self.set_calls = []

    def isOpened(self):
        return True

    def set(self, property_id, value):
        self.set_calls.append((property_id, value))
        return True

    def read(self):
        if self.read_hook is not None:
            return self.read_hook()
        return True, self.frame

    def get(self, property_id):
        return self.properties.get(property_id, 0.0)

    def release(self):
        self.released = True


class TestUsbModeApplication(unittest.TestCase):
    def _stream(self):
        stream = CameraStream()
        with stream._lock:
            stream._capabilities = copy.deepcopy(_usb_capabilities())
        return stream

    def test_driver_adjustment_keeps_selected_and_negotiated_models_consistent(self):
        stream = self._stream()
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        cap = FakeCapture(
            frame,
            {
                cv2.CAP_PROP_FRAME_WIDTH: 1280,
                cv2.CAP_PROP_FRAME_HEIGHT: 720,
                cv2.CAP_PROP_FPS: 25,
                cv2.CAP_PROP_FOURCC: cv2.VideoWriter_fourcc(*"YUYV"),
            },
        )

        with patch.object(stream, "_is_jetson", return_value=False), patch(
            "src.engine.camera.cv2.VideoCapture", return_value=cap
        ):
            result = stream.request_usb_fps(30, validation_seconds=0)

        self.assertTrue(cap.released)
        self.assertTrue(result["negotiation_adjusted"])
        self.assertEqual(result["selected"]["mode_id"], "mjpg-full-hd")
        self.assertEqual(
            (result["selected"]["width"], result["selected"]["height"]),
            (1920, 1080),
        )
        self.assertEqual((result["width"], result["height"], result["fps"]), (1280, 720, 25))
        self.assertEqual(result["pixel_format"], "YUYV")
        self.assertEqual(result["fps_rational"], {"numerator": 25, "denominator": 1})
        self.assertTrue(result["negotiated"]["adjusted"])
        self.assertEqual(result["negotiated"]["received_width"], 1280)
        with stream._lock:
            current = copy.deepcopy(stream._capabilities["current"])
        self.assertEqual(current["fps_rational"], {"numerator": 25, "denominator": 1})
        self.assertEqual(current["requested"]["selection"]["mode_id"], "mjpg-full-hd")

    def test_successful_short_validation_updates_selected_negotiated_and_measured(self):
        stream = self._stream()
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        cap = FakeCapture(
            frame,
            {
                cv2.CAP_PROP_FRAME_WIDTH: 1920,
                cv2.CAP_PROP_FRAME_HEIGHT: 1080,
                cv2.CAP_PROP_FPS: 30,
                cv2.CAP_PROP_FOURCC: cv2.VideoWriter_fourcc(*"MJPG"),
            },
        )

        with patch.object(stream, "_is_jetson", return_value=False), patch(
            "src.engine.camera.cv2.VideoCapture", return_value=cap
        ), patch(
            "src.engine.camera.time.monotonic",
            side_effect=[0.0, 0.034, 0.068, 0.102],
        ):
            result = stream.request_usb_fps(30, validation_seconds=0.1)

        self.assertFalse(result["negotiation_adjusted"])
        self.assertEqual(result["selected"]["fps"], 30.0)
        self.assertEqual(result["negotiated"]["fps"], 30.0)
        self.assertEqual(result["measured"]["sample_frames"], 3)
        self.assertAlmostEqual(result["measured"]["fps"], 29.412, places=3)
        self.assertEqual(result["validation_status"], "validated")
        with stream._lock:
            current = copy.deepcopy(stream._capabilities["current"])
        self.assertEqual(current["requested"]["selection"], result["selected"])
        self.assertEqual(current["measured"], result["measured"])

    def test_failed_validation_does_not_commit_preferences(self):
        stream = self._stream()
        before_capabilities = stream.capabilities
        cap = FakeCapture(
            None,
            {},
            read_hook=lambda: (False, None),
        )

        with patch.object(stream, "_is_jetson", return_value=False), patch(
            "src.engine.camera.cv2.VideoCapture", return_value=cap
        ):
            with self.assertRaisesRegex(RuntimeError, "沒有輸出影像"):
                stream.request_usb_fps(30, validation_seconds=0)

        self.assertTrue(cap.released)
        self.assertEqual((stream.width, stream.height, stream.fps), (1280, 720, 30))
        self.assertEqual(stream.capabilities, before_capabilities)

    def test_validation_holds_lifecycle_lock_against_preview_start(self):
        stream = self._stream()
        validation_entered = threading.Event()
        allow_validation = threading.Event()
        start_completed = threading.Event()
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        def read_frame():
            validation_entered.set()
            allow_validation.wait(timeout=2.0)
            return True, frame

        cap = FakeCapture(
            frame,
            {
                cv2.CAP_PROP_FRAME_WIDTH: 1920,
                cv2.CAP_PROP_FRAME_HEIGHT: 1080,
                cv2.CAP_PROP_FPS: 30,
                cv2.CAP_PROP_FOURCC: cv2.VideoWriter_fourcc(*"MJPG"),
            },
            read_hook=read_frame,
        )
        errors = []

        def apply_mode():
            try:
                stream.request_usb_fps(30, validation_seconds=0)
            except Exception as error:  # pragma: no cover - assertion below reports it
                errors.append(error)

        def start_preview():
            stream.start()
            start_completed.set()

        with patch.object(stream, "_is_jetson", return_value=False), patch.object(
            stream, "_run", return_value=None
        ), patch("src.engine.camera.cv2.VideoCapture", return_value=cap):
            apply_thread = threading.Thread(target=apply_mode)
            apply_thread.start()
            self.assertTrue(validation_entered.wait(timeout=1.0))
            start_thread = threading.Thread(target=start_preview)
            start_thread.start()
            time.sleep(0.05)
            self.assertFalse(start_completed.is_set())
            allow_validation.set()
            apply_thread.join(timeout=2.0)
            start_thread.join(timeout=2.0)

        self.assertEqual(errors, [])
        self.assertTrue(start_completed.is_set())


if __name__ == "__main__":
    unittest.main()
