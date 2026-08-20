import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


STAGED_BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(STAGED_BACKEND))

from camera_capabilities import (  # noqa: E402
    SELECTION_RULE,
    discover_nvidia_csi_capabilities,
)


def write_property(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value.encode("utf-8") + b"\0")


def add_dt_sensor(root: Path, sensor_id: int, sensor_name: str, modes) -> None:
    sensor_relative = f"bus@0/cam_i2cmux/i2c@{sensor_id}/{sensor_name}@10"
    driver = (
        root
        / "tegra-camera-platform"
        / "modules"
        / f"module{sensor_id}"
        / "drivernode0"
    )
    write_property(driver / "pcl_id", "v4l2_sensor")
    write_property(driver / "sysfs-device-tree", f"/sys/firmware/devicetree/base/{sensor_relative}")
    sensor = root / sensor_relative
    write_property(sensor / "compatible", f"vendor,{sensor_name}")
    write_property(sensor / "devnode", f"video{sensor_id}")
    for index, (width, height, minimum, maximum) in enumerate(modes):
        mode = sensor / f"mode{index}"
        write_property(mode / "active_w", str(width))
        write_property(mode / "active_h", str(height))
        write_property(mode / "framerate_factor", "1000000")
        write_property(mode / "min_framerate", str(minimum * 1000000))
        write_property(mode / "max_framerate", str(maximum * 1000000))
        write_property(mode / "mode_type", "bayer")


class CameraCapabilityDiscoveryTests(unittest.TestCase):
    def test_devicetree_uses_exact_sensor_id_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            add_dt_sensor(root, 0, "wrong_sensor", [(640, 480, 5, 15)])
            add_dt_sensor(root, 1, "selected_sensor", [(1920, 1080, 2, 30)])

            catalog = discover_nvidia_csi_capabilities(
                1, enumerator_path=root / "missing", dt_root=root
            )

            self.assertEqual(catalog.provenance, "devicetree")
            self.assertEqual(catalog.name, "selected_sensor")
            self.assertEqual(catalog.device_id, "nvidia-csi:1:video1")
            self.assertEqual((catalog.modes[0].width, catalog.modes[0].height), (1920, 1080))

    def test_libargus_is_preferred_over_devicetree(self):
        payload = {
            "schema_version": 1,
            "sensor_id": 0,
            "model_name": "dynamic-sensor",
            "module_string": "front-module",
            "modes": [
                {
                    "id": "argus:7",
                    "sensor_mode_index": 7,
                    "width": 2048,
                    "height": 1536,
                    "native_width": 2048,
                    "native_height": 1536,
                    "pixel_format": "NV12",
                    "min_fps": 5,
                    "max_fps": 50,
                    "min_fps_rational": {"numerator": 5, "denominator": 1},
                    "max_fps_rational": {"numerator": 50, "denominator": 1},
                }
            ],
        }
        completed = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")
        with tempfile.NamedTemporaryFile() as enumerator:
            os.chmod(enumerator.name, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            with mock.patch("camera_capabilities.subprocess.run", return_value=completed) as run:
                catalog = discover_nvidia_csi_capabilities(
                    0, enumerator_path=enumerator.name, dt_root="/missing"
                )

        self.assertEqual(catalog.provenance, "libargus")
        self.assertEqual(catalog.name, "dynamic-sensor")
        self.assertEqual(catalog.modes[0].sensor_mode_index, 7)
        run.assert_called_once()
        self.assertNotIn("CaptureSession", " ".join(run.call_args.args[0]))

    def test_malformed_argus_falls_back_to_devicetree(self):
        completed = mock.Mock(returncode=0, stdout="not-json", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            add_dt_sensor(root, 0, "dt_sensor", [(1280, 720, 2, 60)])
            executable = root / "enumerator"
            executable.write_text("fixture", encoding="utf-8")
            executable.chmod(0o700)
            with mock.patch("camera_capabilities.subprocess.run", return_value=completed):
                catalog = discover_nvidia_csi_capabilities(
                    0, enumerator_path=executable, dt_root=root
                )
        self.assertEqual(catalog.provenance, "devicetree")

    def test_known_table_is_final_fallback(self):
        catalog = discover_nvidia_csi_capabilities(
            0, enumerator_path="/missing", dt_root="/missing"
        )
        self.assertEqual(catalog.provenance, "known_table")
        self.assertEqual(len(catalog.modes), 5)
        self.assertIn("libargus=", catalog.detail)
        self.assertIn("devicetree=", catalog.detail)

    def test_schema_is_backward_compatible_and_contains_three_states(self):
        catalog = discover_nvidia_csi_capabilities(
            0, enumerator_path="/missing", dt_root="/missing"
        )
        current = {
            "source": 0,
            "width": 1280,
            "height": 720,
            "fps": 40,
            "connected": True,
            "requested": {"fps": 40},
            "negotiated": {"width": 1280, "height": 720, "fps": 40},
            "measured": {"fps": 39.8, "status": "measured"},
        }
        payload = catalog.to_dict(current)

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["selection_rule"], SELECTION_RULE)
        self.assertEqual(payload["device"]["backend"], "nvidia_csi")
        self.assertTrue(payload["device"]["connected"])
        self.assertEqual(payload["min_fps"], 2)
        self.assertEqual(payload["max_fps"], 60)
        for legacy in ("width", "height", "min_fps", "max_fps"):
            self.assertIn(legacy, payload["modes"][0])
        for field in (
            "id",
            "native_width",
            "native_height",
            "pixel_format",
            "fps_values",
            "fps_type",
            "provenance",
            "status",
        ):
            self.assertIn(field, payload["modes"][0])
        self.assertIn("requested", payload["current"])
        self.assertIn("negotiated", payload["current"])
        self.assertIn("measured", payload["current"])

    def test_selection_clamps_and_retains_highest_pixels(self):
        catalog = discover_nvidia_csi_capabilities(
            0, enumerator_path="/missing", dt_root="/missing"
        )
        low_fps, low_mode = catalog.select(1)
        high_fps, high_mode = catalog.select(100)
        mid_fps, mid_mode = catalog.select(25)

        self.assertEqual((low_fps, low_mode.width, low_mode.height), (2, 3280, 2464))
        self.assertEqual((mid_fps, mid_mode.width, mid_mode.height), (25, 3280, 1848))
        self.assertEqual((high_fps, high_mode.width, high_mode.height), (60, 1280, 720))


if __name__ == "__main__":
    unittest.main()
