"""Camera capability discovery and mode selection.

The public contract is a JSON-compatible dictionary.  Both the NVIDIA owner
service and USB/V4L2 devices are normalized to this shape::

    {
        "device": {"id", "name", "backend", "path"?, "connected"},
        "provenance": "nvidia_service" | "v4l2_ioctl" | "fallback",
        "min_fps": number | None,
        "max_fps": number | None,
        "integer_fps_only": bool,
        "selection_rule": "highest_pixel_mode_supporting_requested_fps",
        "modes": [{
            "id", "width", "height", "pixel_format",
            "min_fps", "max_fps",
            "fps_values": [{"numerator", "denominator"}],
            "fps_type": "discrete" | "range" | "unknown",
            "provenance", "status",
        }],
        "current": {...} | None,
    }

FPS rationals describe frames per second, not V4L2 frame intervals.  For a
stepwise/continuous V4L2 interval, the exact interval range is additionally
retained under ``fps_range.frame_interval`` so no precision is discarded.
"""

from __future__ import annotations

import copy
import ctypes
import errno
import fcntl
import os
from fractions import Fraction
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union


Number = Union[int, float]

CAPABILITY_SELECTION_RULE = "highest_pixel_mode_supporting_requested_fps"
V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE = 9
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_VIDEO_CAPTURE_MPLANE = 0x00001000
V4L2_CAP_DEVICE_CAPS = 0x80000000
V4L2_FMT_FLAG_COMPRESSED = 0x0001
V4L2_FRMSIZE_TYPE_DISCRETE = 1
V4L2_FRMSIZE_TYPE_CONTINUOUS = 2
V4L2_FRMSIZE_TYPE_STEPWISE = 3
V4L2_FRMIVAL_TYPE_DISCRETE = 1
V4L2_FRMIVAL_TYPE_CONTINUOUS = 2
V4L2_FRMIVAL_TYPE_STEPWISE = 3

_MAX_ENUM_ITEMS = 256


class _V4L2Capability(ctypes.Structure):
    _fields_ = [
        ("driver", ctypes.c_ubyte * 16),
        ("card", ctypes.c_ubyte * 32),
        ("bus_info", ctypes.c_ubyte * 32),
        ("version", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("device_caps", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    ]


class _V4L2FmtDesc(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("description", ctypes.c_ubyte * 32),
        ("pixelformat", ctypes.c_uint32),
        ("mbus_code", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    ]


class _V4L2FrameSizeDiscrete(ctypes.Structure):
    _fields_ = [("width", ctypes.c_uint32), ("height", ctypes.c_uint32)]


class _V4L2FrameSizeStepwise(ctypes.Structure):
    _fields_ = [
        ("min_width", ctypes.c_uint32),
        ("max_width", ctypes.c_uint32),
        ("step_width", ctypes.c_uint32),
        ("min_height", ctypes.c_uint32),
        ("max_height", ctypes.c_uint32),
        ("step_height", ctypes.c_uint32),
    ]


class _V4L2FrameSizeUnion(ctypes.Union):
    _fields_ = [
        ("discrete", _V4L2FrameSizeDiscrete),
        ("stepwise", _V4L2FrameSizeStepwise),
    ]


class _V4L2FrameSizeEnum(ctypes.Structure):
    _anonymous_ = ("size",)
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("pixel_format", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("size", _V4L2FrameSizeUnion),
        ("reserved", ctypes.c_uint32 * 2),
    ]


class _V4L2Fract(ctypes.Structure):
    _fields_ = [("numerator", ctypes.c_uint32), ("denominator", ctypes.c_uint32)]


class _V4L2FrameIntervalStepwise(ctypes.Structure):
    _fields_ = [
        ("min", _V4L2Fract),
        ("max", _V4L2Fract),
        ("step", _V4L2Fract),
    ]


class _V4L2FrameIntervalUnion(ctypes.Union):
    _fields_ = [
        ("discrete", _V4L2Fract),
        ("stepwise", _V4L2FrameIntervalStepwise),
    ]


class _V4L2FrameIntervalEnum(ctypes.Structure):
    _anonymous_ = ("interval",)
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("pixel_format", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("interval", _V4L2FrameIntervalUnion),
        ("reserved", ctypes.c_uint32 * 2),
    ]


def _ioc(direction: int, ioctl_type: str, number: int, size: int) -> int:
    """Build a Linux generic ioctl number (valid on Jetson arm64 and x86_64)."""
    return (
        (direction << 30)
        | (ord(ioctl_type) << 8)
        | number
        | (size << 16)
    )


def _iowr(ioctl_type: str, number: int, structure: type[ctypes.Structure]) -> int:
    return _ioc(3, ioctl_type, number, ctypes.sizeof(structure))


def _ior(ioctl_type: str, number: int, structure: type[ctypes.Structure]) -> int:
    return _ioc(2, ioctl_type, number, ctypes.sizeof(structure))


VIDIOC_QUERYCAP = _ior("V", 0, _V4L2Capability)
VIDIOC_ENUM_FMT = _iowr("V", 2, _V4L2FmtDesc)
VIDIOC_ENUM_FRAMESIZES = _iowr("V", 74, _V4L2FrameSizeEnum)
VIDIOC_ENUM_FRAMEINTERVALS = _iowr("V", 75, _V4L2FrameIntervalEnum)


def _ioctl_struct(fd: int, request: int, value: ctypes.Structure) -> None:
    """Execute an ioctl while keeping ctypes layout details private."""
    size = ctypes.sizeof(value)
    buffer = bytearray(ctypes.string_at(ctypes.addressof(value), size))
    fcntl.ioctl(fd, request, buffer, True)
    ctypes.memmove(ctypes.addressof(value), bytes(buffer), size)


def _decode_c_string(value: Iterable[int]) -> str:
    return bytes(value).split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()


def _fraction(value: Any) -> Optional[Fraction]:
    if isinstance(value, Fraction):
        return value if value > 0 else None
    if isinstance(value, Mapping):
        try:
            result = Fraction(int(value["numerator"]), int(value["denominator"]))
            return result if result > 0 else None
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None
    try:
        result = Fraction(str(value))
        return result if result > 0 else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _requested_fraction(value: Any) -> Fraction:
    """Parse a user target while retaining zero/negative values for clamping."""
    try:
        return Fraction(str(value))
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError("requested_fps must be a number") from error


def _fraction_from_v4l2(value: _V4L2Fract) -> Optional[Fraction]:
    """Convert a V4L2 seconds-per-frame fraction to frames per second."""
    if not value.numerator or not value.denominator:
        return None
    return Fraction(int(value.denominator), int(value.numerator))


def _frame_interval_fraction(value: _V4L2Fract) -> Optional[Fraction]:
    if not value.numerator or not value.denominator:
        return None
    return Fraction(int(value.numerator), int(value.denominator))


def _rational(value: Fraction) -> Dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _number(value: Optional[Fraction]) -> Optional[Number]:
    if value is None:
        return None
    if value.denominator == 1:
        return value.numerator
    return round(float(value), 6)


def _fourcc(value: int) -> str:
    raw = int(value).to_bytes(4, byteorder="little", signed=False)
    if all(32 <= byte <= 126 for byte in raw):
        return raw.decode("ascii")
    return f"0x{value:08x}"


def fourcc_from_value(value: Any) -> Optional[str]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return _fourcc(number) if number > 0 else None


def is_usb_video_device(path: str) -> bool:
    """Return true only for a positively identified USB/UVC video node.

    This test deliberately fails closed.  On Jetson, an unidentified node must
    never be treated as a USB fallback because it may be the service-owned CSI
    ``/dev/video0`` node.
    """
    node = os.path.basename(path)
    if not node.startswith("video") or not node[5:].isdigit():
        return False
    sys_device = os.path.join("/sys/class/video4linux", node, "device")
    try:
        resolved_device = os.path.realpath(sys_device)
        driver = os.path.basename(os.path.realpath(os.path.join(sys_device, "driver")))
    except OSError:
        return False
    path_parts = os.path.normpath(resolved_device).split(os.sep)
    return driver == "uvcvideo" or any(part.startswith("usb") for part in path_parts)


def video_device_name(path: str) -> str:
    node = os.path.basename(path)
    name_path = os.path.join("/sys/class/video4linux", node, "name")
    try:
        with open(name_path, "r", encoding="utf-8") as name_file:
            return name_file.read().strip() or node
    except OSError:
        return node


def _device_id(path: str, bus_info: str = "") -> str:
    node = os.path.basename(path)
    if bus_info:
        return f"v4l2:{bus_info}:{node}"
    sys_device = os.path.join("/sys/class/video4linux", node, "device")
    resolved = os.path.realpath(sys_device)
    return f"v4l2:{resolved or path}"


def empty_capabilities(
    *,
    device_id: str = "none",
    name: str = "未偵測到攝影機",
    backend: str = "none",
    path: Optional[str] = None,
    connected: bool = False,
    provenance: str = "unavailable",
    status: str = "unavailable",
) -> Dict[str, Any]:
    device: Dict[str, Any] = {
        "id": device_id,
        "name": name,
        "backend": backend,
        "connected": bool(connected),
        "status": status,
    }
    if path is not None:
        device["path"] = path
    return {
        "schema_version": 1,
        "device": device,
        "provenance": provenance,
        "min_fps": None,
        "max_fps": None,
        "integer_fps_only": False,
        "selection_rule": CAPABILITY_SELECTION_RULE,
        "modes": [],
        "current": None,
    }


def _fallback_capabilities(
    path: str,
    width: int,
    height: int,
    fps: Number,
    reason: str,
    *,
    connected: bool,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    fps_fraction = _fraction(fps)
    modes: List[Dict[str, Any]] = []
    if width > 0 and height > 0 and fps_fraction is not None:
        modes.append(
            {
                "id": f"v4l2:{path}:fallback:{width}x{height}",
                "width": int(width),
                "height": int(height),
                "pixel_format": "UNKNOWN",
                "size_type": "unknown",
                "min_fps": _number(fps_fraction),
                "max_fps": _number(fps_fraction),
                "min_fps_rational": _rational(fps_fraction),
                "max_fps_rational": _rational(fps_fraction),
                "fps_values": [_rational(fps_fraction)],
                "fps_type": "unknown",
                "provenance": "fallback",
                "status": "unverified",
            }
        )
    result = empty_capabilities(
        device_id=_device_id(path),
        name=name or video_device_name(path),
        backend="usb_v4l2",
        path=path,
        connected=connected,
        provenance="fallback",
        status="unverified",
    )
    result.update(
        {
            "min_fps": _number(fps_fraction) if modes else None,
            "max_fps": _number(fps_fraction) if modes else None,
            "integer_fps_only": bool(fps_fraction and fps_fraction.denominator == 1),
            "modes": modes,
            "current": {
                "width": int(width),
                "height": int(height),
                "fps": _number(fps_fraction),
                "pixel_format": "UNKNOWN",
                "status": "requested_fallback",
            }
            if modes
            else None,
            "errors": [reason],
        }
    )
    return result


def _query_v4l2_device(fd: int) -> Dict[str, Any]:
    capability = _V4L2Capability()
    _ioctl_struct(fd, VIDIOC_QUERYCAP, capability)
    effective_caps = (
        capability.device_caps
        if capability.capabilities & V4L2_CAP_DEVICE_CAPS
        else capability.capabilities
    )
    return {
        "driver": _decode_c_string(capability.driver),
        "card": _decode_c_string(capability.card),
        "bus_info": _decode_c_string(capability.bus_info),
        "capabilities": int(effective_caps),
    }


def _interval_capability(
    fd: int,
    pixel_format: int,
    width: int,
    height: int,
    fallback_fps: Number,
) -> Dict[str, Any]:
    discrete_values: List[Fraction] = []
    range_result: Optional[Dict[str, Any]] = None
    unsupported = False

    for index in range(_MAX_ENUM_ITEMS):
        interval = _V4L2FrameIntervalEnum()
        interval.index = index
        interval.pixel_format = pixel_format
        interval.width = width
        interval.height = height
        try:
            _ioctl_struct(fd, VIDIOC_ENUM_FRAMEINTERVALS, interval)
        except OSError as error:
            if index == 0 and error.errno not in (errno.EINVAL, errno.ENOTTY):
                unsupported = True
            break

        if interval.type == V4L2_FRMIVAL_TYPE_DISCRETE:
            fps_value = _fraction_from_v4l2(interval.discrete)
            if fps_value is not None and fps_value not in discrete_values:
                discrete_values.append(fps_value)
            continue

        if interval.type in (V4L2_FRMIVAL_TYPE_CONTINUOUS, V4L2_FRMIVAL_TYPE_STEPWISE):
            minimum_interval = _frame_interval_fraction(interval.stepwise.min)
            maximum_interval = _frame_interval_fraction(interval.stepwise.max)
            step_interval = _frame_interval_fraction(interval.stepwise.step)
            if minimum_interval and maximum_interval:
                min_fps = Fraction(1, 1) / maximum_interval
                max_fps = Fraction(1, 1) / minimum_interval
                range_result = {
                    "min_fps": _number(min_fps),
                    "max_fps": _number(max_fps),
                    "fps_values": [],
                    "fps_type": "range",
                    "fps_range": {
                        "kind": "continuous"
                        if interval.type == V4L2_FRMIVAL_TYPE_CONTINUOUS
                        else "stepwise",
                        "min": _rational(min_fps),
                        "max": _rational(max_fps),
                        "frame_interval": {
                            "min": _rational(minimum_interval),
                            "max": _rational(maximum_interval),
                            "step": _rational(step_interval) if step_interval else None,
                        },
                    },
                }
            break

        break

    if discrete_values:
        values = sorted(discrete_values)
        return {
            "min_fps": _number(values[0]),
            "max_fps": _number(values[-1]),
            "fps_values": [_rational(value) for value in values],
            "fps_type": "discrete",
        }
    if range_result is not None:
        return range_result

    fallback = _fraction(fallback_fps)
    return {
        "min_fps": _number(fallback),
        "max_fps": _number(fallback),
        "fps_values": [_rational(fallback)] if fallback else [],
        "fps_type": "unknown",
        "interval_status": "ioctl_error" if unsupported else "not_enumerated",
    }


def _mode(
    *,
    path: str,
    pixel_format: int,
    pixel_format_name: str,
    width: int,
    height: int,
    size_type: str,
    compressed: bool,
    intervals: Dict[str, Any],
    size_range: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "id": (
            f"v4l2:{path}:{pixel_format_name}:{width}x{height}:"
            f"{size_type}"
        ),
        "width": int(width),
        "height": int(height),
        "pixel_format": pixel_format_name,
        "pixel_format_code": int(pixel_format),
        "compressed": bool(compressed),
        "size_type": size_type,
        "min_fps": intervals.get("min_fps"),
        "max_fps": intervals.get("max_fps"),
        "fps_values": intervals.get("fps_values", []),
        "fps_type": intervals.get("fps_type", "unknown"),
        "provenance": "v4l2_ioctl",
        "status": "declared"
        if intervals.get("fps_type") != "unknown"
        else "partially_declared",
    }
    minimum = _fraction(result["min_fps"])
    maximum = _fraction(result["max_fps"])
    if minimum is not None:
        result["min_fps_rational"] = _rational(minimum)
    if maximum is not None:
        result["max_fps_rational"] = _rational(maximum)
    if size_range:
        result["size_range"] = size_range
    if "fps_range" in intervals:
        result["fps_range"] = intervals["fps_range"]
    if "interval_status" in intervals:
        result["interval_status"] = intervals["interval_status"]
    return result


def _enumerate_frame_sizes(
    fd: int,
    path: str,
    pixel_format: int,
    pixel_format_name: str,
    compressed: bool,
    fallback_width: int,
    fallback_height: int,
    fallback_fps: Number,
) -> List[Dict[str, Any]]:
    modes: List[Dict[str, Any]] = []
    for index in range(_MAX_ENUM_ITEMS):
        frame_size = _V4L2FrameSizeEnum()
        frame_size.index = index
        frame_size.pixel_format = pixel_format
        try:
            _ioctl_struct(fd, VIDIOC_ENUM_FRAMESIZES, frame_size)
        except OSError:
            break

        if frame_size.type == V4L2_FRMSIZE_TYPE_DISCRETE:
            width = int(frame_size.discrete.width)
            height = int(frame_size.discrete.height)
            if width <= 0 or height <= 0:
                continue
            intervals = _interval_capability(
                fd, pixel_format, width, height, fallback_fps
            )
            modes.append(
                _mode(
                    path=path,
                    pixel_format=pixel_format,
                    pixel_format_name=pixel_format_name,
                    width=width,
                    height=height,
                    size_type="discrete",
                    compressed=compressed,
                    intervals=intervals,
                )
            )
            continue

        if frame_size.type in (
            V4L2_FRMSIZE_TYPE_CONTINUOUS,
            V4L2_FRMSIZE_TYPE_STEPWISE,
        ):
            size = frame_size.stepwise
            width = int(size.max_width)
            height = int(size.max_height)
            if width <= 0 or height <= 0:
                break
            kind = (
                "continuous"
                if frame_size.type == V4L2_FRMSIZE_TYPE_CONTINUOUS
                else "stepwise"
            )
            intervals = _interval_capability(
                fd, pixel_format, width, height, fallback_fps
            )
            modes.append(
                _mode(
                    path=path,
                    pixel_format=pixel_format,
                    pixel_format_name=pixel_format_name,
                    width=width,
                    height=height,
                    size_type=kind,
                    compressed=compressed,
                    intervals=intervals,
                    size_range={
                        "min_width": int(size.min_width),
                        "max_width": width,
                        "step_width": int(size.step_width),
                        "min_height": int(size.min_height),
                        "max_height": height,
                        "step_height": int(size.step_height),
                    },
                )
            )
            break

        break

    if not modes and fallback_width > 0 and fallback_height > 0:
        intervals = _interval_capability(
            fd, pixel_format, fallback_width, fallback_height, fallback_fps
        )
        modes.append(
            _mode(
                path=path,
                pixel_format=pixel_format,
                pixel_format_name=pixel_format_name,
                width=fallback_width,
                height=fallback_height,
                size_type="unknown",
                compressed=compressed,
                intervals=intervals,
            )
        )
        modes[-1]["status"] = "partially_declared"
    return modes


def _bounds_from_modes(
    modes: Iterable[Mapping[str, Any]],
) -> Tuple[Optional[Fraction], Optional[Fraction]]:
    minimums = [
        value
        for mode in modes
        if (value := _fraction(mode.get("min_fps"))) is not None
    ]
    maximums = [
        value
        for mode in modes
        if (value := _fraction(mode.get("max_fps"))) is not None
    ]
    return (min(minimums) if minimums else None, max(maximums) if maximums else None)


def enumerate_v4l2_capabilities(
    path: str,
    *,
    fallback_width: int = 1280,
    fallback_height: int = 720,
    fallback_fps: Number = 30,
    require_usb: bool = True,
) -> Dict[str, Any]:
    """Enumerate a USB camera without starting a video stream.

    ``require_usb`` defaults to true to make the safe Jetson behavior the
    default.  Non-USB nodes are rejected before ``open(2)``.  Any open/ioctl
    failure produces an explicitly unverified fallback model instead of an
    exception or a false hardware claim.
    """
    if require_usb and not is_usb_video_device(path):
        return empty_capabilities(
            device_id=_device_id(path),
            name=video_device_name(path),
            backend="v4l2",
            path=path,
            connected=False,
            provenance="unavailable",
            status="excluded_non_usb",
        )

    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as error:
        return _fallback_capabilities(
            path,
            fallback_width,
            fallback_height,
            fallback_fps,
            f"open_failed:{error.errno}",
            connected=os.path.exists(path),
        )

    errors: List[str] = []
    try:
        try:
            device_info = _query_v4l2_device(fd)
        except OSError as error:
            device_info = {
                "driver": "",
                "card": video_device_name(path),
                "bus_info": "",
                "capabilities": 0,
            }
            errors.append(f"querycap_failed:{error.errno}")

        effective_caps = int(device_info.get("capabilities", 0))
        capture_types: List[int] = []
        if effective_caps & V4L2_CAP_VIDEO_CAPTURE:
            capture_types.append(V4L2_BUF_TYPE_VIDEO_CAPTURE)
        if effective_caps & V4L2_CAP_VIDEO_CAPTURE_MPLANE:
            capture_types.append(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE)
        # Some old drivers implement format ioctls but do not correctly fill
        # QUERYCAP.  Trying both capture types is a safe, read-only fallback.
        if not capture_types:
            capture_types = [
                V4L2_BUF_TYPE_VIDEO_CAPTURE,
                V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
            ]

        modes: List[Dict[str, Any]] = []
        seen_formats = set()
        for buffer_type in capture_types:
            for index in range(_MAX_ENUM_ITEMS):
                description = _V4L2FmtDesc()
                description.index = index
                description.type = buffer_type
                try:
                    _ioctl_struct(fd, VIDIOC_ENUM_FMT, description)
                except OSError as error:
                    if index == 0 and error.errno not in (errno.EINVAL, errno.ENOTTY):
                        errors.append(f"enum_fmt_failed:{error.errno}")
                    break
                # A few drivers expose the same FOURCC through both capture
                # buffer types.  It is one user-visible format, not two modes.
                format_key = int(description.pixelformat)
                if format_key in seen_formats:
                    continue
                seen_formats.add(format_key)
                pixel_format = int(description.pixelformat)
                pixel_format_name = _fourcc(pixel_format)
                format_modes = _enumerate_frame_sizes(
                    fd=fd,
                    path=path,
                    pixel_format=pixel_format,
                    pixel_format_name=pixel_format_name,
                    compressed=bool(description.flags & V4L2_FMT_FLAG_COMPRESSED),
                    fallback_width=fallback_width,
                    fallback_height=fallback_height,
                    fallback_fps=fallback_fps,
                )
                format_description = _decode_c_string(description.description)
                for mode in format_modes:
                    mode["format_description"] = format_description
                    mode["buffer_type"] = (
                        "video_capture_mplane"
                        if buffer_type == V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
                        else "video_capture"
                    )
                modes.extend(format_modes)

        if not modes:
            reason = errors[0] if errors else "no_enumerated_capture_modes"
            return _fallback_capabilities(
                path,
                fallback_width,
                fallback_height,
                fallback_fps,
                reason,
                connected=True,
                name=device_info.get("card") or video_device_name(path),
            )

        minimum, maximum = _bounds_from_modes(modes)
        integer_fps_only = True
        for mode in modes:
            if mode.get("fps_type") != "discrete":
                integer_fps_only = False
                break
            values = [_fraction(value) for value in mode.get("fps_values", [])]
            if any(value is None or value.denominator != 1 for value in values):
                integer_fps_only = False
                break

        current_fps = _fraction(fallback_fps)
        result: Dict[str, Any] = {
            "schema_version": 1,
            "device": {
                "id": _device_id(path, device_info.get("bus_info", "")),
                "name": device_info.get("card") or video_device_name(path),
                "backend": "usb_v4l2",
                "path": path,
                "connected": True,
                "status": "declared",
                "driver": device_info.get("driver", ""),
                "bus_info": device_info.get("bus_info", ""),
            },
            "provenance": "v4l2_ioctl",
            "min_fps": _number(minimum),
            "max_fps": _number(maximum),
            "integer_fps_only": integer_fps_only,
            "selection_rule": CAPABILITY_SELECTION_RULE,
            "modes": modes,
            "current": {
                "width": int(fallback_width),
                "height": int(fallback_height),
                "fps": _number(current_fps),
                "pixel_format": "UNKNOWN",
                "status": "requested",
            },
        }
        if errors:
            result["errors"] = errors
        return result
    finally:
        os.close(fd)


def normalize_nvidia_capabilities(
    payload: Mapping[str, Any],
    *,
    connected: bool,
    device_name: str = "NVIDIA 相機服務",
) -> Dict[str, Any]:
    """Normalize the sole-owner service response without opening CSI."""
    payload_modes = payload.get("modes")
    top_provenance = str(payload.get("provenance") or "nvidia_service")
    modes: List[Dict[str, Any]] = []
    if isinstance(payload_modes, list):
        for index, raw_mode in enumerate(payload_modes):
            if not isinstance(raw_mode, Mapping):
                continue
            try:
                width = int(raw_mode["width"])
                height = int(raw_mode["height"])
            except (KeyError, TypeError, ValueError):
                continue
            if width <= 0 or height <= 0:
                continue
            min_fps = _fraction(raw_mode.get("min_fps", payload.get("min_fps")))
            max_fps = _fraction(raw_mode.get("max_fps", payload.get("max_fps")))
            if not min_fps or not max_fps:
                continue
            if max_fps < min_fps:
                min_fps, max_fps = max_fps, min_fps
            normalized_mode = copy.deepcopy(dict(raw_mode))
            normalized_mode.update(
                {
                    "id": str(
                        raw_mode.get("id")
                        or f"nvidia-csi:cam0:NV12:{width}x{height}:{index}"
                    ),
                    "width": width,
                    "height": height,
                    "pixel_format": str(raw_mode.get("pixel_format") or "NV12"),
                    "size_type": "discrete",
                    "min_fps": _number(min_fps),
                    "max_fps": _number(max_fps),
                    "min_fps_rational": _rational(min_fps),
                    "max_fps_rational": _rational(max_fps),
                    "fps_values": copy.deepcopy(raw_mode.get("fps_values") or []),
                    "fps_type": str(raw_mode.get("fps_type") or "range"),
                    "fps_range": {
                        "kind": "integer_range"
                        if payload.get("integer_fps_only", False)
                        else "continuous",
                        "min": _rational(min_fps),
                        "max": _rational(max_fps),
                    },
                    "provenance": str(raw_mode.get("provenance") or top_provenance),
                    "status": str(raw_mode.get("status") or "declared"),
                }
            )
            normalized_mode.setdefault("native_width", width)
            normalized_mode.setdefault("native_height", height)
            modes.append(normalized_mode)

    current = payload.get("current")
    normalized_current: Optional[Dict[str, Any]] = None
    if isinstance(current, Mapping):
        normalized_current = copy.deepcopy(dict(current))
        normalized_current.setdefault("pixel_format", "NV12")
        normalized_current.setdefault("status", "negotiated")

    minimum, maximum = _bounds_from_modes(modes)
    payload_min = _fraction(payload.get("min_fps"))
    payload_max = _fraction(payload.get("max_fps"))
    raw_device = payload.get("device")
    device = copy.deepcopy(dict(raw_device)) if isinstance(raw_device, Mapping) else {}
    device.setdefault("id", "nvidia-csi:cam0")
    device.setdefault("name", device_name)
    device.setdefault("backend", "nvidia_csi")
    device["connected"] = bool(connected)
    device.setdefault("status", "declared" if modes else "unavailable")
    return {
        "schema_version": int(payload.get("schema_version", 1)),
        "device": device,
        "provenance": top_provenance,
        "min_fps": _number(payload_min or minimum),
        "max_fps": _number(payload_max or maximum),
        "integer_fps_only": bool(payload.get("integer_fps_only", False)),
        "selection_rule": str(payload.get("selection_rule") or CAPABILITY_SELECTION_RULE),
        "modes": modes,
        "current": normalized_current,
    }


def _mode_fps_values(mode: Mapping[str, Any]) -> List[Fraction]:
    values: List[Fraction] = []
    for raw_value in mode.get("fps_values", []) or []:
        value = _fraction(raw_value)
        if value is not None and value not in values:
            values.append(value)
    return sorted(values)


def _mode_bounds(mode: Mapping[str, Any]) -> Tuple[Optional[Fraction], Optional[Fraction]]:
    minimum = _fraction(mode.get("min_fps"))
    maximum = _fraction(mode.get("max_fps"))
    if minimum and maximum and maximum < minimum:
        return maximum, minimum
    return minimum, maximum


def _stepwise_frame_intervals(
    mode: Mapping[str, Any],
) -> Optional[Tuple[Fraction, Fraction, Fraction]]:
    fps_range = mode.get("fps_range")
    if not isinstance(fps_range, Mapping) or fps_range.get("kind") != "stepwise":
        return None
    interval = fps_range.get("frame_interval")
    if not isinstance(interval, Mapping):
        return None
    minimum = _fraction(interval.get("min"))
    maximum = _fraction(interval.get("max"))
    step = _fraction(interval.get("step"))
    if minimum is None or maximum is None or step is None:
        return None
    if maximum < minimum:
        minimum, maximum = maximum, minimum
    return minimum, maximum, step


def _nearest_stepwise_fps(
    mode: Mapping[str, Any], requested: Fraction
) -> Optional[Fraction]:
    intervals = _stepwise_frame_intervals(mode)
    if intervals is None:
        return None
    minimum_interval, maximum_interval, step_interval = intervals
    step_count = int((maximum_interval - minimum_interval) // step_interval)
    # A zero/negative input is a valid below-minimum request and must clamp to
    # the slowest legal step rather than divide by zero or reject the input.
    requested_interval = (
        maximum_interval if requested <= 0 else Fraction(1, 1) / requested
    )
    approximate_index = (requested_interval - minimum_interval) / step_interval
    floor_index = approximate_index.numerator // approximate_index.denominator
    candidate_indexes = {
        0,
        step_count,
        max(0, min(step_count, floor_index)),
        max(0, min(step_count, floor_index + 1)),
    }
    candidates = [
        Fraction(1, 1) / (minimum_interval + index * step_interval)
        for index in candidate_indexes
    ]
    return min(candidates, key=lambda value: (abs(value - requested), value))


def _candidate_fps_for_mode(
    mode: Mapping[str, Any], requested: Fraction
) -> List[Fraction]:
    values = _mode_fps_values(mode)
    if values and mode.get("fps_type") != "range":
        return values
    stepwise = _nearest_stepwise_fps(mode, requested)
    if stepwise is not None:
        return [stepwise]
    minimum, maximum = _mode_bounds(mode)
    if minimum is None or maximum is None:
        return []
    return [max(minimum, min(maximum, requested))]


def _supports_fps(mode: Mapping[str, Any], fps: Fraction) -> bool:
    values = _mode_fps_values(mode)
    fps_type = mode.get("fps_type")
    if fps_type == "discrete" or (values and fps_type != "range"):
        return fps in values
    minimum, maximum = _mode_bounds(mode)
    if not bool(minimum is not None and maximum is not None and minimum <= fps <= maximum):
        return False
    intervals = _stepwise_frame_intervals(mode)
    if intervals is None:
        return True
    minimum_interval, maximum_interval, step_interval = intervals
    candidate_interval = Fraction(1, 1) / fps
    if not minimum_interval <= candidate_interval <= maximum_interval:
        return False
    steps = (candidate_interval - minimum_interval) / step_interval
    return steps.denominator == 1


def select_mode_for_fps(
    capabilities: Mapping[str, Any], requested_fps: Number
) -> Optional[Dict[str, Any]]:
    """Select the nearest legal FPS, then the highest-pixel supporting mode.

    Discrete values use nearest-neighbour snapping with the lower value winning
    exact ties.  Range modes clamp at their boundaries.  Once an FPS is chosen,
    resolution is the highest pixel count among modes that can sustain it.
    """
    requested = _requested_fraction(requested_fps)
    raw_modes = capabilities.get("modes")
    if not isinstance(raw_modes, list):
        return None
    modes = [mode for mode in raw_modes if isinstance(mode, Mapping)]
    if not modes:
        return None

    candidates = set()
    for mode in modes:
        candidates.update(_candidate_fps_for_mode(mode, requested))

    if not candidates:
        return None
    selected_fps = min(candidates, key=lambda value: (abs(value - requested), value))
    eligible = [mode for mode in modes if _supports_fps(mode, selected_fps)]
    if not eligible:
        return None
    selected_mode = max(
        eligible,
        key=lambda mode: (
            int(mode.get("width", 0)) * int(mode.get("height", 0)),
            int(mode.get("width", 0)),
            int(mode.get("height", 0)),
            # At equal resolution prefer compressed USB transport to avoid
            # wasting bus bandwidth; MJPEG is the most common UVC option.
            2
            if str(mode.get("pixel_format", "")).upper() in ("MJPG", "JPEG")
            else 1
            if mode.get("compressed")
            else 0,
        ),
    )
    try:
        width = int(selected_mode["width"])
        height = int(selected_mode["height"])
    except (KeyError, TypeError, ValueError):
        return None
    minimum, maximum = _mode_bounds(selected_mode)
    snapped = selected_fps != requested and (
        bool(_mode_fps_values(selected_mode))
        or _stepwise_frame_intervals(selected_mode) is not None
    )
    provenance = str(selected_mode.get("provenance") or capabilities.get("provenance") or "")
    return {
        "requested_fps": _number(requested),
        "fps": _number(selected_fps),
        "fps_rational": _rational(selected_fps),
        "width": width,
        "height": height,
        "pixel_format": str(selected_mode.get("pixel_format") or "UNKNOWN"),
        "mode_id": str(selected_mode.get("id") or ""),
        "min_fps": _number(minimum),
        "max_fps": _number(maximum),
        "fps_type": str(selected_mode.get("fps_type") or "unknown"),
        "clamped": selected_fps != requested,
        "snapped": snapped,
        "fallback": provenance == "fallback"
        or selected_mode.get("status") == "unverified",
        "provenance": provenance,
        "status": str(selected_mode.get("status") or "unknown"),
    }


__all__ = [
    "CAPABILITY_SELECTION_RULE",
    "VIDIOC_QUERYCAP",
    "VIDIOC_ENUM_FMT",
    "VIDIOC_ENUM_FRAMESIZES",
    "VIDIOC_ENUM_FRAMEINTERVALS",
    "empty_capabilities",
    "enumerate_v4l2_capabilities",
    "fourcc_from_value",
    "is_usb_video_device",
    "normalize_nvidia_capabilities",
    "select_mode_for_fps",
    "video_device_name",
]
