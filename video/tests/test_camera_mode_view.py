"""Display-independent tests for the smart camera settings presentation."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.gui.camera_mode_view import build_camera_mode_ui_state
from src.gui.app import (
    _CAMERA_RESUME_MAX_RETRIES,
    _camera_capabilities_fingerprint,
    MainWindow,
)


class TestCameraModeUiState(unittest.TestCase):
    def test_missing_capabilities_use_existing_static_mapping(self):
        state = build_camera_mode_ui_state(None, 45)

        self.assertFalse(state.dynamic)
        self.assertEqual((state.width, state.height, state.selected_fps), (1280, 720, 45.0))
        self.assertEqual((state.min_fps, state.max_fps), (2.0, 60.0))
        self.assertIn("暫用內建 IMX219", state.declared_text)

    def test_dynamic_capabilities_drive_bounds_preview_and_declared_text(self):
        capabilities = {
            "device": {"id": "usb-2", "name": "UVC HD Camera", "backend": "v4l2"},
            "provenance": "v4l2-enumerated",
            "min_fps": 15,
            "max_fps": 60,
            "integer_fps_only": False,
            "modes": [
                {
                    "id": "mjpeg-fullhd",
                    "width": 1920,
                    "height": 1080,
                    "pixel_format": "MJPG",
                    "min_fps": 15,
                    "max_fps": 30,
                    "fps_values": [15, 30],
                },
                {
                    "id": "mjpeg-hd",
                    "width": 1280,
                    "height": 720,
                    "pixel_format": "MJPG",
                    "min_fps": 30,
                    "max_fps": 60,
                    "fps_values": [30, 60],
                },
            ],
        }
        selected = {
            "requested_fps": 60,
            "fps": 60,
            "width": 1280,
            "height": 720,
            "pixel_format": "MJPG",
            "mode_id": "mjpeg-hd",
            "clamped": False,
            "snapped": False,
        }

        with patch("src.gui.camera_mode_view._engine_selection", return_value=selected):
            state = build_camera_mode_ui_state(capabilities, 60)

        self.assertTrue(state.dynamic)
        self.assertEqual((state.min_fps, state.max_fps), (15.0, 60.0))
        self.assertIn("1280 × 720 / 60 FPS / MJPG", state.preview_text)
        self.assertIn("UVC HD Camera", state.device_text)
        self.assertIn("v4l2-enumerated", state.device_text)
        self.assertIn("2 種模式", state.declared_text)
        self.assertIn("最高 1920 × 1080", state.declared_text)

    def test_real_engine_selector_is_the_single_mode_selection_source(self):
        capabilities = {
            "device": {"name": "UVC HD Camera"},
            "provenance": "v4l2_ioctl",
            "min_fps": 15,
            "max_fps": 60,
            "modes": [
                {
                    "id": "fullhd",
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
                },
                {
                    "id": "hd",
                    "width": 1280,
                    "height": 720,
                    "pixel_format": "MJPG",
                    "min_fps": 30,
                    "max_fps": 60,
                    "fps_values": [
                        {"numerator": 30, "denominator": 1},
                        {"numerator": 60, "denominator": 1},
                    ],
                    "fps_type": "discrete",
                },
            ],
        }

        state = build_camera_mode_ui_state(capabilities, 60)

        self.assertTrue(state.dynamic)
        self.assertEqual((state.width, state.height, state.selected_fps), (1280, 720, 60.0))

    def test_discrete_fps_snap_is_visible_to_user(self):
        capabilities = {
            "device": {"name": "USB Camera"},
            "min_fps": 15,
            "max_fps": 30,
            "modes": [{"id": "a", "width": 1920, "height": 1080}],
        }
        selected = {
            "fps": 30,
            "width": 1920,
            "height": 1080,
            "pixel_format": "MJPG",
        }

        with patch("src.gui.camera_mode_view._engine_selection", return_value=selected):
            state = build_camera_mode_ui_state(capabilities, 25)

        self.assertIn("最接近支援值 30", state.preview_text)

    def test_zero_and_negative_preview_keep_device_capabilities_and_clamp_low(self):
        capabilities = {
            "device": {"name": "USB Camera"},
            "provenance": "v4l2_ioctl",
            "min_fps": 15,
            "max_fps": 30,
            "modes": [
                {
                    "id": "full-hd",
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
                }
            ],
        }

        for requested in (-10, 0):
            with self.subTest(requested=requested):
                state = build_camera_mode_ui_state(capabilities, requested)
                self.assertTrue(state.dynamic)
                self.assertEqual((state.width, state.height), (1920, 1080))
                self.assertEqual(state.selected_fps, 15)
                self.assertIn("超限，將採用 15", state.preview_text)

    def test_malformed_selection_falls_back_without_crashing(self):
        capabilities = {
            "min_fps": 60,
            "max_fps": 15,
            "modes": [{"id": "broken", "width": "?", "height": None}],
        }
        with patch(
            "src.gui.camera_mode_view._engine_selection",
            return_value={"fps": 30, "width": 0, "height": 0},
        ):
            state = build_camera_mode_ui_state(capabilities, 30)

        self.assertFalse(state.dynamic)
        self.assertEqual((state.width, state.height), (1920, 1080))


class TestCameraModeAppContract(unittest.TestCase):
    def test_capability_fingerprint_ignores_per_frame_current_measurements(self):
        base = {
            "device": {"id": "cam", "name": "Camera"},
            "provenance": "v4l2_ioctl",
            "min_fps": 15,
            "max_fps": 30,
            "modes": [{"id": "a", "width": 1280, "height": 720}],
            "current": {"fps": 30, "measured_fps": 28.1},
        }
        changed_measurement = {
            **base,
            "current": {"fps": 30, "measured_fps": 29.7},
        }

        self.assertEqual(
            _camera_capabilities_fingerprint(base),
            _camera_capabilities_fingerprint(changed_measurement),
        )

    def test_capability_fingerprint_changes_when_declared_modes_change(self):
        original = {"device": {"id": "cam"}, "modes": [{"id": "720p"}]}
        updated = {"device": {"id": "cam"}, "modes": [{"id": "1080p"}]}

        self.assertNotEqual(
            _camera_capabilities_fingerprint(original),
            _camera_capabilities_fingerprint(updated),
        )

    def test_resume_does_not_reschedule_an_already_running_preview(self):
        starts = []
        target = SimpleNamespace(
            config=SimpleNamespace(capture_source="camera"),
            is_recording=False,
            camera_stream=SimpleNamespace(
                is_running=True,
                connected=True,
                _stop_event=SimpleNamespace(is_set=lambda: False),
                start=lambda: starts.append(True),
            ),
        )

        with patch("src.gui.app.GLib.timeout_add") as timeout_add:
            MainWindow._resume_camera_preview_when_ready(target)

        self.assertEqual(starts, [])
        timeout_add.assert_not_called()

    def test_resume_retries_only_while_old_worker_is_stopping(self):
        target = SimpleNamespace(
            config=SimpleNamespace(capture_source="camera"),
            is_recording=False,
            camera_stream=SimpleNamespace(
                is_running=True,
                connected=False,
                _stop_event=SimpleNamespace(is_set=lambda: True),
                start=lambda: None,
            ),
            _resume_camera_preview_when_ready=lambda *args: None,
        )

        with patch("src.gui.app.GLib.timeout_add") as timeout_add:
            MainWindow._resume_camera_preview_when_ready(target, retry_count=3)

        timeout_add.assert_called_once_with(
            250,
            target._resume_camera_preview_when_ready,
            4,
        )

    def test_resume_retry_limit_prevents_permanent_timer(self):
        target = SimpleNamespace(
            config=SimpleNamespace(capture_source="camera"),
            is_recording=False,
            camera_stream=SimpleNamespace(
                is_running=True,
                _stop_event=SimpleNamespace(is_set=lambda: True),
                start=lambda: None,
            ),
        )

        with patch("src.gui.app.GLib.timeout_add") as timeout_add:
            MainWindow._resume_camera_preview_when_ready(
                target,
                retry_count=_CAMERA_RESUME_MAX_RETRIES,
            )

        timeout_add.assert_not_called()

    def test_resume_starts_once_worker_has_stopped(self):
        starts = []
        target = SimpleNamespace(
            config=SimpleNamespace(capture_source="camera"),
            is_recording=False,
            camera_stream=SimpleNamespace(
                is_running=False,
                start=lambda: starts.append(True),
            ),
        )

        MainWindow._resume_camera_preview_when_ready(target)

        self.assertEqual(starts, [True])

    def test_preview_forwards_capabilities_negotiated_and_measured_values(self):
        capability_updates = []
        negotiated_updates = []
        measured_updates = []
        capabilities = {
            "device": {"id": "usb-2", "name": "UVC Camera", "backend": "v4l2"},
            "min_fps": 15,
            "max_fps": 30,
            "modes": [{"id": "a", "width": 1920, "height": 1080}],
        }
        target = SimpleNamespace(
            config=SimpleNamespace(capture_source="camera", fps=0),
            is_recording=False,
            camera_stream=SimpleNamespace(
                get_frame=lambda: object(),
                status=(True, "USB 攝影機", ""),
                capabilities=capabilities,
                source_settings=(1920, 1080, 30.0),
                measured_fps=28.7,
            ),
            controls=SimpleNamespace(
                update_camera_capabilities=capability_updates.append,
                update_current_camera_settings=lambda *args, **kwargs: negotiated_updates.append(
                    (args, kwargs)
                ),
                update_measured_camera_fps=measured_updates.append,
                reset_camera_runtime_status=lambda: None,
            ),
            header=SimpleNamespace(update_camera_badge=lambda *args, **kwargs: None),
            media_panel=SimpleNamespace(
                update_live_frame=lambda *args, **kwargs: None,
                update_camera_message=lambda *args, **kwargs: None,
            ),
            _last_camera_status=None,
            _last_camera_settings=None,
            _last_camera_capabilities_fingerprint=None,
        )

        keep_polling = MainWindow._update_camera_preview(target)

        self.assertTrue(keep_polling)
        self.assertEqual(capability_updates, [capabilities])
        self.assertEqual(negotiated_updates[0][0], (1920, 1080, 30.0))
        self.assertEqual(measured_updates, [28.7])
        self.assertEqual(target.config.fps, 30)

    def test_preview_throttles_capability_snapshots_but_keeps_measured_fps_live(self):
        class CountingCamera:
            def __init__(self):
                self.capability_reads = 0
                self.status = (True, "USB 攝影機", "")
                self.source_settings = (1280, 720, 30.0)
                self.measured_fps = 29.4

            def get_frame(self):
                return object()

            @property
            def capabilities(self):
                self.capability_reads += 1
                return {
                    "device": {"id": "usb", "name": "Camera"},
                    "min_fps": 15,
                    "max_fps": 30,
                    "modes": [{"id": "720p", "width": 1280, "height": 720}],
                    "current": {"pixel_format": "MJPG", "measured_fps": self.measured_fps},
                }

        camera = CountingCamera()
        measured_updates = []
        target = SimpleNamespace(
            config=SimpleNamespace(capture_source="camera", fps=0),
            is_recording=False,
            camera_stream=camera,
            controls=SimpleNamespace(
                update_camera_capabilities=lambda value: None,
                update_current_camera_settings=lambda *args, **kwargs: None,
                update_measured_camera_fps=measured_updates.append,
                reset_camera_runtime_status=lambda: None,
            ),
            header=SimpleNamespace(update_camera_badge=lambda *args, **kwargs: None),
            media_panel=SimpleNamespace(
                update_live_frame=lambda *args, **kwargs: None,
                update_camera_message=lambda *args, **kwargs: None,
            ),
            _last_camera_status=None,
            _last_camera_settings=None,
            _last_camera_capabilities_fingerprint=None,
            _camera_capabilities_cache=None,
            _next_camera_capabilities_poll=0.0,
        )

        with patch("src.gui.app.time.monotonic", side_effect=[10.0, 10.1]):
            MainWindow._update_camera_preview(target)
            camera.measured_fps = 29.8
            MainWindow._update_camera_preview(target)

        self.assertEqual(camera.capability_reads, 1)
        self.assertEqual(measured_updates, [29.4, 29.8])

    def test_usb_apply_uses_common_contract_after_preview_releases_device(self):
        events = []
        completions = []
        messages = []

        class ImmediateThread:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                self.target()

        target = SimpleNamespace(
            is_recording=False,
            _camera_settings_busy=False,
            camera_stream=SimpleNamespace(
                status=(True, "USB 攝影機", ""),
                uses_nvidia_service=False,
                source_settings=(1280, 720, 30.0),
                stop=lambda: events.append("stop") or True,
                request_camera_fps=lambda fps: events.append(("request", fps)) or {
                    "width": 1280,
                    "height": 720,
                    "fps": 60,
                },
            ),
            controls=SimpleNamespace(
                update_current_camera_settings=lambda *args, **kwargs: None,
                set_camera_settings_busy=lambda busy: events.append(("busy", busy)),
            ),
            media_panel=SimpleNamespace(update_camera_message=messages.append),
            header=SimpleNamespace(update_camera_badge=lambda *args, **kwargs: None),
            _finish_camera_fps_change=lambda result, error: completions.append((result, error)),
        )

        with patch("src.gui.app.threading.Thread", ImmediateThread), patch(
            "src.gui.app.GLib.idle_add",
            side_effect=lambda callback, *args: callback(*args),
        ):
            MainWindow._on_apply_camera_fps(target, 60)

        self.assertEqual(events[-2:], ["stop", ("request", 60)])
        self.assertEqual(completions[0][1], None)
        self.assertEqual(completions[0][0]["fps"], 60)
        self.assertIn("USB", messages[0])

    def test_apply_stop_failure_never_opens_a_second_camera_owner(self):
        requests = []
        completions = []

        class ImmediateThread:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                self.target()

        target = SimpleNamespace(
            is_recording=False,
            _camera_settings_busy=False,
            camera_stream=SimpleNamespace(
                status=(True, "USB 攝影機", ""),
                uses_nvidia_service=False,
                source_settings=(1280, 720, 30.0),
                stop=lambda: False,
                request_camera_fps=lambda fps: requests.append(fps),
            ),
            controls=SimpleNamespace(
                update_current_camera_settings=lambda *args, **kwargs: None,
                set_camera_settings_busy=lambda busy: None,
            ),
            media_panel=SimpleNamespace(update_camera_message=lambda message: None),
            header=SimpleNamespace(update_camera_badge=lambda *args, **kwargs: None),
            _finish_camera_fps_change=lambda result, error: completions.append((result, error)),
        )

        with patch("src.gui.app.threading.Thread", ImmediateThread), patch(
            "src.gui.app.GLib.idle_add",
            side_effect=lambda callback, *args: callback(*args),
        ):
            MainWindow._on_apply_camera_fps(target, 60)

        self.assertEqual(requests, [])
        self.assertIsNone(completions[0][0])
        self.assertIn("仍在停止", completions[0][1])

    def test_finish_apply_displays_negotiated_format_and_short_measurement(self):
        current_updates = []
        measured_updates = []
        resumes = []
        messages = []
        target = SimpleNamespace(
            _camera_settings_busy=True,
            _last_camera_status=(True, "USB", ""),
            _last_camera_settings=(1, 1, 1),
            _last_camera_capabilities_fingerprint="old",
            _camera_capabilities_cache={"old": True},
            _next_camera_capabilities_poll=99.0,
            camera_stream=SimpleNamespace(source_settings=(640, 480, 30.0)),
            config=SimpleNamespace(fps=30),
            controls=SimpleNamespace(
                set_camera_settings_busy=lambda busy: None,
                update_current_camera_settings=lambda *args, **kwargs: current_updates.append(
                    (args, kwargs)
                ),
                update_measured_camera_fps=measured_updates.append,
            ),
            media_panel=SimpleNamespace(update_camera_message=messages.append),
            header=SimpleNamespace(update_camera_badge=lambda *args, **kwargs: None),
            _resume_camera_preview_when_ready=lambda: resumes.append(True),
        )

        result = {
            "width": 1920,
            "height": 1080,
            "fps": 29.97,
            "pixel_format": "MJPG",
            "snapped": True,
            "negotiation_adjusted": True,
            "measured": {"fps": "26.4", "status": "degraded"},
        }
        keep = MainWindow._finish_camera_fps_change(target, result, None)

        self.assertFalse(keep)
        self.assertEqual(target.config.fps, 30)
        self.assertEqual(measured_updates, [26.4])
        self.assertEqual(current_updates[0][0], (1920, 1080, 29.97))
        self.assertEqual(current_updates[0][1]["pixel_format"], "MJPG")
        self.assertIn("驅動調整為 1920 × 1080 / 29.97 FPS / MJPG", current_updates[0][1]["note"])
        self.assertIn("低於協商值", current_updates[0][1]["note"])
        self.assertEqual(resumes, [True])
        self.assertIn("設定完成", messages[0])

    def test_finish_apply_handles_malformed_result_and_still_resumes(self):
        current_updates = []
        messages = []
        resumes = []
        target = SimpleNamespace(
            _camera_settings_busy=True,
            _last_camera_status=None,
            _last_camera_settings=None,
            _last_camera_capabilities_fingerprint=None,
            _camera_capabilities_cache=None,
            _next_camera_capabilities_poll=0.0,
            camera_stream=SimpleNamespace(source_settings=(1280, 720, 30.0)),
            config=SimpleNamespace(fps=30),
            controls=SimpleNamespace(
                set_camera_settings_busy=lambda busy: None,
                update_current_camera_settings=lambda *args, **kwargs: current_updates.append(
                    (args, kwargs)
                ),
                update_measured_camera_fps=lambda fps: None,
            ),
            media_panel=SimpleNamespace(update_camera_message=messages.append),
            header=SimpleNamespace(update_camera_badge=lambda *args, **kwargs: None),
            _resume_camera_preview_when_ready=lambda: resumes.append(True),
        )

        keep = MainWindow._finish_camera_fps_change(
            target,
            {"width": 1920, "fps": "not-a-number"},
            None,
        )

        self.assertFalse(keep)
        self.assertIn("回傳結果無效", current_updates[0][1]["note"])
        self.assertIn("相機設定失敗", messages[0])
        self.assertEqual(resumes, [True])


if __name__ == "__main__":
    unittest.main()
