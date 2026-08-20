import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import yaml


STAGED_BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(STAGED_BACKEND))

import camera  # noqa: E402
system_monitor = types.ModuleType("system_monitor")
system_monitor.get_system_status = lambda **_kwargs: {}
sys.modules.setdefault("system_monitor", system_monitor)
import app  # noqa: E402
from camera_capabilities import (  # noqa: E402
    CameraCapabilityCatalog,
    CameraModeCapability,
    discover_nvidia_csi_capabilities,
)


class CameraReaderCapabilityIntegrationTests(unittest.TestCase):
    @staticmethod
    def duplicate_resolution_catalog():
        def mode(mode_id, index, maximum):
            return CameraModeCapability(
                id=mode_id,
                sensor_mode_index=index,
                width=1280,
                height=720,
                native_width=1280,
                native_height=720,
                pixel_format="NV12",
                min_fps=2,
                max_fps=maximum,
                min_fps_rational={"numerator": 2, "denominator": 1},
                max_fps_rational={"numerator": maximum, "denominator": 1},
                provenance="libargus",
            )

        return CameraCapabilityCatalog(
            sensor_id=0,
            name="duplicate-mode-sensor",
            device_id="nvidia-csi:0:duplicate-mode-sensor",
            provenance="libargus",
            modes=(mode("argus:0", 0, 30), mode("argus:1", 1, 60)),
        )

    def make_reader(self, fps=30):
        catalog = discover_nvidia_csi_capabilities(
            0, enumerator_path="/missing", dt_root="/missing"
        )
        temporary = tempfile.TemporaryDirectory()
        config_path = Path(temporary.name) / "camera.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "camera": {
                        "source": 0,
                        "width": 1280,
                        "height": 720,
                        "fps": fps,
                    }
                }
            ),
            encoding="utf-8",
        )
        discover = mock.patch(
            "camera.discover_nvidia_csi_capabilities", return_value=catalog
        )
        discover_mock = discover.start()
        self.addCleanup(discover.stop)
        self.addCleanup(temporary.cleanup)
        return camera.CameraReader(str(config_path)), discover_mock

    def test_discovers_once_during_construction_and_caches_endpoint(self):
        reader, discover = self.make_reader()
        self.assertEqual(discover.call_count, 1)

        first = reader.get_capabilities()
        second = reader.get_capabilities()

        self.assertEqual(discover.call_count, 1)
        self.assertEqual(first["provenance"], "known_table")
        self.assertEqual(first, second)

    def test_dynamic_selection_and_pipeline_pin_sensor_mode(self):
        reader, _discover = self.make_reader()

        selection = reader._select_settings(25)
        pipeline = reader._build_jetson_pipeline(0, selection)

        self.assertEqual((selection.width, selection.height), (3280, 1848))
        self.assertEqual(selection.sensor_mode_index, 1)
        self.assertIn("sensor-id=0 sensor-mode=1", pipeline)
        self.assertIn("framerate=(fraction)25/1", pipeline)

    def test_duplicate_resolution_tracks_exact_high_fps_sensor_mode(self):
        catalog = self.duplicate_resolution_catalog()
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "camera.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "camera": {
                            "source": 0,
                            "width": 1280,
                            "height": 720,
                            "fps": 60,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "camera.discover_nvidia_csi_capabilities", return_value=catalog
            ):
                reader = camera.CameraReader(str(config_path))

        selection = reader._current_selection()
        status = reader.get_status()
        pipeline = reader._build_jetson_pipeline(0, selection)

        self.assertEqual(selection.mode_id, "argus:1")
        self.assertEqual(selection.sensor_mode_index, 1)
        self.assertEqual(status["mode_id"], "argus:1")
        self.assertEqual(status["mode_max_fps"], 60)
        self.assertIn("sensor-mode=1", pipeline)

    def test_status_preserves_legacy_fields_and_adds_three_states(self):
        reader, _discover = self.make_reader(40)
        status = reader.get_status()

        for field in ("source", "width", "height", "fps", "measured_fps"):
            self.assertIn(field, status)
        self.assertEqual(status["min_fps"], 2)
        self.assertEqual(status["max_fps"], 60)
        self.assertEqual(status["requested"]["fps"], 40)
        self.assertEqual(status["negotiated"]["fps"], 40)
        self.assertEqual(status["negotiated"]["status"], "offline")
        self.assertEqual(status["measured"]["status"], "offline")

    def test_missing_config_uses_a_mode_from_discovered_catalog(self):
        catalog = discover_nvidia_csi_capabilities(
            0, enumerator_path="/missing", dt_root="/missing"
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "camera.discover_nvidia_csi_capabilities", return_value=catalog
        ):
            reader = camera.CameraReader(str(Path(directory) / "missing.yaml"))

        self.assertIsNotNone(catalog.find_mode(reader.width, reader.height))
        self.assertEqual((reader.width, reader.height, reader.fps), (1920, 1080, 30))

    def test_submit_fps_uses_catalog_without_opening_camera_on_request_thread(self):
        reader, _discover = self.make_reader()
        reader.running = True
        reader.thread = mock.Mock()
        reader.thread.is_alive.return_value = True

        operation = reader.submit_fps(60)
        pending = reader._pending_operation

        self.assertEqual(operation["status"], "pending")
        self.assertIsNotNone(pending)
        self.assertEqual((pending.selection.width, pending.selection.height), (1280, 720))
        self.assertEqual(pending.selection.sensor_mode_index, 4)
        self.assertIsNone(reader.cap)
        reader._fail_pending_operation("test cleanup")

    def test_capabilities_endpoint_uses_reader_cache(self):
        reader, discover = self.make_reader()
        previous = app.camera_reader
        app.camera_reader = reader
        self.addCleanup(setattr, app, "camera_reader", previous)

        payload = app.camera_capabilities()

        self.assertEqual(discover.call_count, 1)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["current"]["requested"]["fps"], 30)


if __name__ == "__main__":
    unittest.main()
