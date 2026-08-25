"""Camera ownership and NVIDIA stream integration regression tests."""

import os
import json
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from src.config import OutputFormat, select_imx219_settings
from src.engine.camera import (
    CameraStream,
    NVIDIA_CAMERA_DEVICE_NAME,
    NVIDIA_CAMERA_STREAM_URL,
)
from src.engine.recorder import VideoRecorder


class TestCameraStreamSources(unittest.TestCase):
    def test_fps_bounds_select_highest_supported_pixel_mode(self):
        cases = (
            (-10, 2, 3280, 2464, True),
            (2, 2, 3280, 2464, False),
            (21, 21, 3280, 2464, False),
            (22, 22, 3280, 1848, False),
            (29, 29, 1920, 1080, False),
            (31, 31, 1280, 720, False),
            (60, 60, 1280, 720, False),
            (99, 60, 1280, 720, True),
        )
        for requested, fps, width, height, clamped in cases:
            with self.subTest(requested=requested):
                selected = select_imx219_settings(requested)
                self.assertEqual((selected.fps, selected.width, selected.height), (fps, width, height))
                self.assertEqual(selected.was_clamped, clamped)

    def test_request_nvidia_fps_posts_raw_value_and_updates_settings(self):
        stream = CameraStream()
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {"requested_fps": 99, "fps": 60, "width": 1280, "height": 720, "clamped": True}
        ).encode("utf-8")

        with patch("src.engine.camera.urlopen", return_value=response) as open_url:
            result = stream.request_nvidia_fps(99)

        request = open_url.call_args.args[0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"fps": 99})
        self.assertEqual(result["fps"], 60)
        self.assertEqual(stream.source_settings, (1280, 720, 60.0))

    def test_request_nvidia_fps_polls_async_operation_to_completion(self):
        stream = CameraStream()

        def response(payload):
            mocked = MagicMock()
            mocked.__enter__.return_value = mocked
            mocked.read.return_value = json.dumps(payload).encode("utf-8")
            return mocked

        responses = [
            response({"operation_id": "op-1", "status": "pending"}),
            response({"operation_id": "op-1", "status": "running"}),
            response(
                {
                    "operation_id": "op-1",
                    "status": "succeeded",
                    "result": {
                        "requested_fps": 31,
                        "fps": 31,
                        "width": 1280,
                        "height": 720,
                        "clamped": False,
                    },
                }
            ),
        ]
        with patch("src.engine.camera.urlopen", side_effect=responses) as open_url, patch(
            "src.engine.camera.time.sleep"
        ):
            result = stream.request_nvidia_fps(31)

        self.assertEqual(open_url.call_count, 3)
        self.assertEqual(result["fps"], 31)
        self.assertEqual(stream.source_settings, (1280, 720, 31.0))

    def test_start_does_not_replace_a_still_live_stopping_thread(self):
        stream = CameraStream()

        class StuckThread:
            def is_alive(self):
                return True

            def join(self, timeout=None):
                return None

        thread = StuckThread()
        stream._thread = thread
        self.assertFalse(stream.stop())
        stream.start()
        self.assertIs(stream._thread, thread)

    def test_camera_unavailable_status_check_does_not_hold_frame_lock(self):
        stream = CameraStream()
        lock_was_free = []

        def fetch_service_status():
            acquired = stream._lock.acquire(blocking=False)
            lock_was_free.append(acquired)
            if acquired:
                stream._lock.release()
            stream._stop_event.set()
            return None

        with patch.object(stream, "_open_camera", return_value=(None, None)), patch.object(
            stream, "_is_jetson", return_value=True
        ), patch.object(stream, "_fetch_nvidia_status", side_effect=fetch_service_status):
            stream._run()

        self.assertEqual(lock_was_free, [True])

    def test_measured_fps_uses_received_frame_timestamps(self):
        stream = CameraStream(fps=30)
        frame = np.zeros((8, 12, 3), dtype=np.uint8)
        with patch(
            "src.engine.camera.time.monotonic",
            side_effect=[0.00, 0.04, 0.08, 0.12, 0.16],
        ):
            for _ in range(5):
                stream._store_frame(frame)

        self.assertAlmostEqual(stream.measured_fps, 25.0, places=1)

    def test_preview_snapshot_is_zero_copy_and_only_returns_new_frames(self):
        stream = CameraStream()
        frame = np.zeros((8, 12, 3), dtype=np.uint8)
        stream._store_frame(frame)

        sequence, snapshot = stream.get_frame_snapshot()

        self.assertIs(snapshot, frame)
        self.assertIsNone(stream.get_frame_snapshot(after_sequence=sequence))
        next_frame = np.ones((8, 12, 3), dtype=np.uint8)
        stream._store_frame(next_frame)
        next_sequence, next_snapshot = stream.get_frame_snapshot(sequence)
        self.assertGreater(next_sequence, sequence)
        self.assertIs(next_snapshot, next_frame)

    def test_jetson_uses_running_nvidia_service_first(self):
        stream = CameraStream()
        with patch.object(stream, "_is_jetson", return_value=True), patch.object(
            stream, "_nvidia_camera_connected", return_value=True
        ), patch("src.engine.camera.glob.glob", return_value=["/dev/video2"]), patch.object(
            stream, "_is_usb_video_device", return_value=True
        ):
            candidates = list(stream._candidate_devices())

        self.assertEqual(candidates[0][0], NVIDIA_CAMERA_STREAM_URL)
        self.assertEqual(candidates[0][1], cv2.CAP_FFMPEG)
        self.assertEqual(candidates[0][2], NVIDIA_CAMERA_DEVICE_NAME)
        self.assertEqual(candidates[1][0], "/dev/video2")

    def test_jetson_does_not_open_csi_when_service_is_stopped(self):
        stream = CameraStream()
        with patch.object(stream, "_is_jetson", return_value=True), patch.object(
            stream, "_nvidia_camera_connected", return_value=False
        ), patch("src.engine.camera.glob.glob", return_value=[]), patch(
            "src.engine.camera.os.name", "posix"
        ):
            candidates = list(stream._candidate_devices())

        self.assertEqual(candidates, [])

    def test_usb_camera_remains_available_independently(self):
        stream = CameraStream()
        with patch.object(stream, "_is_jetson", return_value=True), patch.object(
            stream, "_nvidia_camera_connected", return_value=False
        ), patch("src.engine.camera.glob.glob", return_value=["/dev/video2"]), patch.object(
            stream, "_is_usb_video_device", return_value=True
        ):
            candidates = list(stream._candidate_devices())

        self.assertEqual(candidates[0][:2], ("/dev/video2", cv2.CAP_V4L2))
        self.assertIn("USB 攝影機", candidates[0][2])

    def test_offline_nvidia_service_falls_back_to_usb(self):
        stream = CameraStream()
        with patch.object(stream, "_is_jetson", return_value=True), patch.object(
            stream, "_nvidia_camera_connected", return_value=False
        ), patch("src.engine.camera.glob.glob", return_value=["/dev/video2"]), patch.object(
            stream, "_is_usb_video_device", return_value=True
        ):
            candidates = list(stream._candidate_devices())

        self.assertEqual([candidate[0] for candidate in candidates], ["/dev/video2"])

    def test_jetson_excludes_csi_video_node_from_usb_fallback(self):
        stream = CameraStream()

        def is_usb(path):
            return path == "/dev/video2"

        with patch.object(stream, "_is_jetson", return_value=True), patch.object(
            stream, "_nvidia_camera_connected", return_value=False
        ), patch(
            "src.engine.camera.glob.glob", return_value=["/dev/video0", "/dev/video2"]
        ), patch.object(stream, "_is_usb_video_device", side_effect=is_usb):
            candidates = list(stream._candidate_devices())

        self.assertEqual([candidate[0] for candidate in candidates], ["/dev/video2"])

    def test_recording_source_tracks_exact_active_device(self):
        stream = CameraStream()
        with stream._lock:
            stream._connected = True
            stream._active_source_kind = "usb_v4l2"
            stream._active_device_path = "/dev/video2"
        self.assertEqual(stream.recording_source, "v4l2:/dev/video2")

        with stream._lock:
            stream._active_source_kind = "nvidia_stream"
            stream._active_device_path = None
        self.assertEqual(stream.recording_source, "nvidia_stream")

    def test_nvidia_offline_frame_is_rejected_before_usb_fallback(self):
        stream = CameraStream()
        frame = np.zeros((8, 12, 3), dtype=np.uint8)
        nvidia_cap = MagicMock()
        nvidia_cap.isOpened.return_value = True
        nvidia_cap.read.return_value = (True, frame)
        usb_cap = MagicMock()
        usb_cap.isOpened.return_value = True
        usb_cap.read.return_value = (True, frame)
        usb_cap.get.return_value = 30.0
        candidates = (
            (NVIDIA_CAMERA_STREAM_URL, cv2.CAP_FFMPEG, NVIDIA_CAMERA_DEVICE_NAME),
            ("/dev/video2", cv2.CAP_V4L2, "USB 攝影機：測試 (/dev/video2)"),
        )

        with patch.object(stream, "_candidate_devices", return_value=iter(candidates)), patch.object(
            stream, "_fetch_nvidia_status", return_value={"connected": False}
        ), patch("src.engine.camera.cv2.VideoCapture", side_effect=[nvidia_cap, usb_cap]):
            opened_cap, device_name = stream._open_camera()

        self.assertIs(opened_cap, usb_cap)
        self.assertIn("USB 攝影機", device_name)
        nvidia_cap.release.assert_called()
        self.assertEqual(stream.recording_source, None)  # Connected is published by _run.
        with stream._lock:
            self.assertEqual(stream._active_device_path, "/dev/video2")

    def test_running_nvidia_stream_rechecks_physical_connection(self):
        stream = CameraStream()
        frame = np.zeros((8, 12, 3), dtype=np.uint8)
        cap = MagicMock()
        cap.read.return_value = (True, frame)
        open_calls = 0

        def open_camera():
            nonlocal open_calls
            open_calls += 1
            if open_calls == 1:
                return cap, NVIDIA_CAMERA_DEVICE_NAME
            stream._stop_event.set()
            return None, None

        clock = [0.0]

        def monotonic():
            clock[0] += 1.1
            return clock[0]

        with patch.object(stream, "_open_camera", side_effect=open_camera), patch.object(
            stream, "_is_jetson", return_value=True
        ), patch.object(
            stream, "_fetch_nvidia_status", return_value={"connected": False}
        ), patch("src.engine.camera.time.monotonic", side_effect=monotonic):
            stream._run()

        self.assertGreaterEqual(open_calls, 2)
        cap.release.assert_called()

    def test_transient_status_timeout_does_not_drop_valid_nvidia_stream(self):
        stream = CameraStream()
        frame = np.zeros((8, 12, 3), dtype=np.uint8)
        cap = MagicMock()
        reads = 0

        def read_frame():
            nonlocal reads
            reads += 1
            if reads == 2:
                stream._stop_event.set()
            return True, frame

        clock = [0.0]

        def monotonic():
            clock[0] += 1.1
            return clock[0]

        cap.read.side_effect = read_frame
        with patch.object(
            stream, "_open_camera", return_value=(cap, NVIDIA_CAMERA_DEVICE_NAME)
        ), patch.object(stream, "_fetch_nvidia_status", return_value=None), patch(
            "src.engine.camera.time.monotonic", side_effect=monotonic
        ):
            stream._run()

        self.assertEqual(reads, 2)


class TestNvidiaRecordingSource(unittest.TestCase):
    def test_nvidia_stream_pipeline_uses_http_and_not_csi(self):
        pipeline = VideoRecorder()._build_pipeline_string(
            output_path=os.path.join("/tmp", "camera-test.mp4"),
            x=0,
            y=0,
            w=1280,
            h=720,
            fps=30,
            format_type=OutputFormat.MP4,
            audio_enabled=False,
            audio_source="default",
            nvenc_enabled=False,
            capture_source="nvidia_stream",
        )

        self.assertIn(NVIDIA_CAMERA_STREAM_URL, pipeline)
        self.assertIn("multipartdemux", pipeline)
        self.assertNotIn("nvarguscamerasrc", pipeline)

    def test_usb_recording_uses_exact_v4l2_device(self):
        pipeline = VideoRecorder()._build_pipeline_string(
            output_path=os.path.join("/tmp", "usb-camera-test.mp4"),
            x=0,
            y=0,
            w=1280,
            h=720,
            fps=30,
            format_type=OutputFormat.MP4,
            audio_enabled=False,
            audio_source="default",
            nvenc_enabled=False,
            capture_source="v4l2:/dev/video2",
        )

        self.assertIn('v4l2src device="/dev/video2"', pipeline)
        self.assertIn("decodebin", pipeline)
        self.assertIn("videorate", pipeline)
        self.assertNotIn("nvarguscamerasrc", pipeline)

    def test_usb_recording_reapplies_selected_mjpeg_mode(self):
        pipeline = VideoRecorder()._build_pipeline_string(
            output_path=os.path.join("/tmp", "usb-camera-test.mp4"),
            x=0,
            y=0,
            w=1280,
            h=720,
            fps=60,
            format_type=OutputFormat.MP4,
            audio_enabled=False,
            audio_source="default",
            nvenc_enabled=False,
            capture_source="v4l2:/dev/video2",
            camera_width=1280,
            camera_height=720,
            camera_pixel_format="MJPG",
        )

        self.assertIn("image/jpeg,width=1280,height=720,framerate=60/1", pipeline)
        self.assertIn("jpegdec ! videorate", pipeline)
        self.assertIn("video/x-raw,framerate=60/1", pipeline)

    def test_usb_recording_maps_v4l2_yuyv_to_gstreamer_yuy2(self):
        pipeline = VideoRecorder()._build_pipeline_string(
            output_path=os.path.join("/tmp", "usb-camera-test.webm"),
            x=0,
            y=0,
            w=640,
            h=480,
            fps=30,
            format_type=OutputFormat.WEBM,
            audio_enabled=False,
            audio_source="default",
            nvenc_enabled=False,
            capture_source="v4l2:/dev/video4",
            camera_width=640,
            camera_height=480,
            camera_pixel_format="YUYV",
        )

        self.assertIn(
            "video/x-raw,format=YUY2,width=640,height=480,framerate=30/1",
            pipeline,
        )
        self.assertIn("! videorate", pipeline)

    def test_usb_recording_rejects_untrusted_device_path(self):
        with self.assertRaises(ValueError):
            VideoRecorder()._build_pipeline_string(
                output_path=os.path.join("/tmp", "unsafe.mp4"),
                x=0,
                y=0,
                w=1280,
                h=720,
                fps=30,
                format_type=OutputFormat.MP4,
                audio_enabled=False,
                audio_source="default",
                nvenc_enabled=False,
                capture_source="v4l2:/dev/video2 ! fakesink",
            )


if __name__ == "__main__":
    unittest.main()
