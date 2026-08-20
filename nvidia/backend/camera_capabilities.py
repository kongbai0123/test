"""Safe, cached NVIDIA CSI capability discovery.

Discovery runs before CameraReader starts its capture thread.  The preferred
helper creates an Argus CameraProvider and reads immutable properties only; it
never creates a CaptureSession.  Device Tree and a conservative IMX219 table
are fallbacks, in that order.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Optional


SCHEMA_VERSION = 1
DEFAULT_MIN_FPS = 2
DEFAULT_MAX_FPS = 60
SELECTION_RULE = "highest_pixel_mode_supporting_requested_fps"

# Kept as the last-resort compatibility table, not the primary capability
# source.  The order is the IMX219 sensor-mode order on the deployed Jetson.
KNOWN_IMX219_SENSOR_MODES = (
    (3280, 2464, 2, 21),
    (3280, 1848, 2, 28),
    (1920, 1080, 2, 30),
    (1640, 1232, 2, 30),
    (1280, 720, 2, 60),
)


def _api_number(value: float):
    rounded = round(value)
    return int(rounded) if abs(value - rounded) < 0.001 else round(value, 6)


def _rational(numerator: int, denominator: int) -> dict:
    value = Fraction(int(numerator), max(1, int(denominator)))
    return {"numerator": value.numerator, "denominator": value.denominator}


@dataclass(frozen=True)
class CameraModeCapability:
    id: str
    sensor_mode_index: int
    width: int
    height: int
    native_width: int
    native_height: int
    pixel_format: str
    min_fps: float
    max_fps: float
    min_fps_rational: dict
    max_fps_rational: dict
    provenance: str
    sensor_pixel_type: Optional[str] = None

    @property
    def pixel_count(self) -> int:
        return self.native_width * self.native_height

    def supports_integer_fps(self, fps: int) -> bool:
        epsilon = 0.001
        return self.min_fps - epsilon <= fps <= self.max_fps + epsilon

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "sensor_mode_index": self.sensor_mode_index,
            # width/height are preserved for existing consumers.
            "width": self.width,
            "height": self.height,
            "native_width": self.native_width,
            "native_height": self.native_height,
            "pixel_format": self.pixel_format,
            "min_fps": _api_number(self.min_fps),
            "max_fps": _api_number(self.max_fps),
            "min_fps_rational": dict(self.min_fps_rational),
            "max_fps_rational": dict(self.max_fps_rational),
            "fps_values": [],
            "fps_type": "range",
            "provenance": self.provenance,
            "status": "advertised",
        }
        if self.sensor_pixel_type:
            result["sensor_pixel_type"] = self.sensor_pixel_type
        return result


@dataclass(frozen=True)
class CameraCapabilityCatalog:
    sensor_id: int
    name: str
    device_id: str
    provenance: str
    modes: tuple[CameraModeCapability, ...]
    detail: Optional[str] = None

    @property
    def min_fps(self) -> int:
        return int(math.ceil(min(mode.min_fps for mode in self.modes) - 0.001))

    @property
    def max_fps(self) -> int:
        return int(math.floor(max(mode.max_fps for mode in self.modes) + 0.001))

    def find_mode(
        self,
        width: int,
        height: int,
        *,
        fps: Optional[int] = None,
        mode_id: Optional[str] = None,
    ) -> Optional[CameraModeCapability]:
        if mode_id is not None:
            exact = next((mode for mode in self.modes if mode.id == mode_id), None)
            if (
                exact is not None
                and (exact.width, exact.height) == (int(width), int(height))
                and (fps is None or exact.supports_integer_fps(int(fps)))
            ):
                return exact
        candidates = [
            mode
            for mode in self.modes
            if (mode.width, mode.height) == (int(width), int(height))
            and (fps is None or mode.supports_integer_fps(int(fps)))
        ]
        return min(candidates, key=lambda mode: mode.sensor_mode_index, default=None)

    def select(self, requested_fps: int) -> tuple[int, CameraModeCapability]:
        requested = int(requested_fps)
        fps = max(self.min_fps, min(self.max_fps, requested))
        candidates = [mode for mode in self.modes if mode.supports_integer_fps(fps)]
        if not candidates:
            # A catalog may contain disjoint ranges. Move down to the closest
            # supported integer FPS rather than inventing an unsupported mode.
            supported = [
                value
                for value in range(self.min_fps, self.max_fps + 1)
                if any(mode.supports_integer_fps(value) for mode in self.modes)
            ]
            if not supported:
                raise RuntimeError("camera capability catalog has no usable integer FPS")
            fps = min(supported, key=lambda value: (abs(value - fps), -value))
            candidates = [mode for mode in self.modes if mode.supports_integer_fps(fps)]
        mode = max(
            candidates,
            key=lambda candidate: (
                candidate.pixel_count,
                candidate.native_width,
                candidate.native_height,
                -candidate.sensor_mode_index,
            ),
        )
        return fps, mode

    def to_dict(self, current: Optional[dict] = None) -> dict:
        current = dict(current or {})
        connected = bool(current.get("connected", False))
        current.setdefault("requested", {})
        current.setdefault("negotiated", {})
        current.setdefault("measured", {})
        result = {
            "schema_version": SCHEMA_VERSION,
            "device": {
                "id": self.device_id,
                "name": self.name,
                "backend": "nvidia_csi",
                "sensor_id": self.sensor_id,
                "connected": connected,
            },
            "provenance": self.provenance,
            # The following fields preserve the original API contract.
            "min_fps": self.min_fps,
            "max_fps": self.max_fps,
            "integer_fps_only": True,
            "selection_rule": SELECTION_RULE,
            "modes": [mode.to_dict() for mode in self.modes],
            "current": current,
        }
        if self.detail:
            result["provenance_detail"] = self.detail
        return result


def _mode_from_mapping(mapping: dict, provenance: str) -> CameraModeCapability:
    width = int(mapping["width"])
    height = int(mapping["height"])
    native_width = int(mapping.get("native_width", width))
    native_height = int(mapping.get("native_height", height))
    minimum = float(mapping["min_fps"])
    maximum = float(mapping["max_fps"])
    index = int(mapping.get("sensor_mode_index", 0))
    if (
        width <= 0
        or height <= 0
        or native_width <= 0
        or native_height <= 0
        or index < 0
        or minimum <= 0
        or maximum < minimum
    ):
        raise ValueError("invalid camera mode")
    return CameraModeCapability(
        id=str(mapping.get("id", f"{provenance}:{index}")),
        sensor_mode_index=index,
        width=width,
        height=height,
        native_width=native_width,
        native_height=native_height,
        pixel_format=str(mapping.get("pixel_format", "NV12")),
        min_fps=minimum,
        max_fps=maximum,
        min_fps_rational=dict(
            mapping.get("min_fps_rational")
            or _rational(round(minimum * 1_000_000), 1_000_000)
        ),
        max_fps_rational=dict(
            mapping.get("max_fps_rational")
            or _rational(round(maximum * 1_000_000), 1_000_000)
        ),
        provenance=provenance,
        sensor_pixel_type=mapping.get("sensor_pixel_type"),
    )


def _read_dt_string(path: Path) -> Optional[str]:
    try:
        return path.read_bytes().rstrip(b"\0").decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _read_dt_positive_int(path: Path) -> int:
    value = _read_dt_string(path)
    if value is None or not value.isdigit() or int(value) <= 0:
        raise ValueError(f"invalid Device Tree integer: {path}")
    return int(value)


def _sensor_node_from_module(dt_root: Path, sensor_id: int) -> Path:
    module = dt_root / "tegra-camera-platform" / "modules" / f"module{sensor_id}"
    if not module.is_dir():
        raise FileNotFoundError(f"Device Tree module{sensor_id} is unavailable")
    for driver_node in sorted(module.glob("drivernode*")):
        if _read_dt_string(driver_node / "pcl_id") != "v4l2_sensor":
            continue
        location = _read_dt_string(driver_node / "sysfs-device-tree")
        if not location:
            location = _read_dt_string(driver_node / "proc-device-tree")
        if not location:
            continue
        # Properties may name /proc/device-tree, /sys/firmware/device-tree/base,
        # or /sys/firmware/devicetree/base. Resolve the portion after /base/
        # against the injected root so offline fixtures work as well.
        marker = "/base/"
        if marker in location:
            candidate = dt_root / location.split(marker, 1)[1]
        elif location.startswith("/proc/device-tree/"):
            candidate = dt_root / location[len("/proc/device-tree/") :]
        else:
            candidate = Path(location)
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"sensor node for module{sensor_id} is unavailable")


def _mode_sort_key(path: Path) -> tuple[int, str]:
    match = re.fullmatch(r"mode(\d+)", path.name)
    return (int(match.group(1)) if match else 1_000_000, path.name)


def _discover_from_devicetree(sensor_id: int, dt_root: Path) -> CameraCapabilityCatalog:
    sensor_node = _sensor_node_from_module(dt_root, sensor_id)
    if (_read_dt_string(sensor_node / "status") or "okay") not in {"okay", "ok"}:
        raise RuntimeError(f"Device Tree sensor for module{sensor_id} is disabled")

    compatible = _read_dt_string(sensor_node / "compatible") or sensor_node.name
    name = compatible.split(",")[-1]
    device_node = _read_dt_string(sensor_node / "devnode")
    modes = []
    for fallback_index, mode_path in enumerate(
        sorted(sensor_node.glob("mode*"), key=_mode_sort_key)
    ):
        match = re.fullmatch(r"mode(\d+)", mode_path.name)
        index = int(match.group(1)) if match else fallback_index
        try:
            width = _read_dt_positive_int(mode_path / "active_w")
            height = _read_dt_positive_int(mode_path / "active_h")
            factor = _read_dt_positive_int(mode_path / "framerate_factor")
            minimum_raw = _read_dt_positive_int(mode_path / "min_framerate")
            maximum_raw = _read_dt_positive_int(mode_path / "max_framerate")
            minimum = minimum_raw / factor
            maximum = maximum_raw / factor
            if maximum < minimum:
                raise ValueError("maximum FPS is less than minimum FPS")
        except (FileNotFoundError, ValueError):
            continue
        modes.append(
            CameraModeCapability(
                id=f"devicetree:{mode_path.name}",
                sensor_mode_index=index,
                width=width,
                height=height,
                native_width=width,
                native_height=height,
                pixel_format="NV12",
                min_fps=minimum,
                max_fps=maximum,
                min_fps_rational=_rational(minimum_raw, factor),
                max_fps_rational=_rational(maximum_raw, factor),
                provenance="devicetree",
                sensor_pixel_type=_read_dt_string(mode_path / "mode_type"),
            )
        )
    if not modes:
        raise RuntimeError(f"Device Tree sensor {sensor_node} has no valid modes")
    return CameraCapabilityCatalog(
        sensor_id=sensor_id,
        name=name,
        device_id=f"nvidia-csi:{sensor_id}:{device_node or sensor_node.name}",
        provenance="devicetree",
        modes=tuple(modes),
    )


def _discover_from_argus(
    sensor_id: int,
    enumerator_path: Path,
    timeout: float,
) -> CameraCapabilityCatalog:
    if not enumerator_path.is_file() or not os.access(enumerator_path, os.X_OK):
        raise FileNotFoundError(f"Argus enumerator is unavailable: {enumerator_path}")
    completed = subprocess.run(
        [str(enumerator_path), "--sensor-id", str(sensor_id)],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip().splitlines()[-1:] or ["unknown error"]
        raise RuntimeError(f"Argus enumerator failed: {message[0]}")
    payload = json.loads(completed.stdout)
    if int(payload.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ValueError("Argus enumerator returned an unsupported schema")
    if int(payload.get("sensor_id", -1)) != sensor_id:
        raise ValueError("Argus enumerator returned a different sensor id")
    modes = tuple(
        _mode_from_mapping(mapping, "libargus") for mapping in payload.get("modes", [])
    )
    if not modes:
        raise ValueError("Argus enumerator returned no valid modes")
    name = str(payload.get("model_name") or f"CSI Camera {sensor_id}")
    module_string = str(payload.get("module_string") or name)
    return CameraCapabilityCatalog(
        sensor_id=sensor_id,
        name=name,
        device_id=f"nvidia-csi:{sensor_id}:{module_string}",
        provenance="libargus",
        modes=modes,
    )


def _known_catalog(sensor_id: int, detail: Optional[str] = None) -> CameraCapabilityCatalog:
    modes = tuple(
        CameraModeCapability(
            id=f"known-imx219:{index}",
            sensor_mode_index=index,
            width=width,
            height=height,
            native_width=width,
            native_height=height,
            pixel_format="NV12",
            min_fps=minimum,
            max_fps=maximum,
            min_fps_rational=_rational(minimum, 1),
            max_fps_rational=_rational(maximum, 1),
            provenance="known_table",
            sensor_pixel_type="bayer",
        )
        for index, (width, height, minimum, maximum) in enumerate(
            KNOWN_IMX219_SENSOR_MODES
        )
    )
    return CameraCapabilityCatalog(
        sensor_id=sensor_id,
        name="IMX219",
        device_id=f"nvidia-csi:{sensor_id}:imx219-fallback",
        provenance="known_table",
        modes=modes,
        detail=detail,
    )


def discover_nvidia_csi_capabilities(
    sensor_id: int,
    *,
    enumerator_path: Optional[os.PathLike] = None,
    dt_root: os.PathLike = "/sys/firmware/devicetree/base",
    argus_timeout: float = 15.0,
) -> CameraCapabilityCatalog:
    """Discover once, without creating a competing CaptureSession."""
    sensor_id = int(sensor_id)
    if sensor_id < 0:
        raise ValueError("sensor id must be non-negative")
    if enumerator_path is None:
        enumerator_path = Path(__file__).parent / "tools" / "argus-mode-enumerator"

    failures = []
    try:
        return _discover_from_argus(sensor_id, Path(enumerator_path), argus_timeout)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        failures.append(f"libargus={error}")
    try:
        return _discover_from_devicetree(sensor_id, Path(dt_root))
    except (OSError, ValueError, RuntimeError) as error:
        failures.append(f"devicetree={error}")
    return _known_catalog(sensor_id, detail="; ".join(failures))


# Legacy exports used by app.py and older tests/clients.
CAMERA_MIN_FPS = DEFAULT_MIN_FPS
CAMERA_MAX_FPS = DEFAULT_MAX_FPS
IMX219_SENSOR_MODES = tuple(
    (width, height, maximum)
    for width, height, _minimum, maximum in KNOWN_IMX219_SENSOR_MODES
)
