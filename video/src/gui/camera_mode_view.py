"""Pure presentation helpers for camera capability and FPS mode information.

The hardware-specific selection algorithm lives in ``src.engine``.  Keeping
the text model here lets the GTK controls stay small and makes the declared /
negotiated / measured presentation testable without a display server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from src.config import CAMERA_MAX_FPS, CAMERA_MIN_FPS, select_imx219_settings


def _value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _positive_number(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if parsed > 0 else float(default)


def _format_fps(value: float) -> str:
    rounded = round(float(value))
    if abs(float(value) - rounded) < 0.01:
        return str(int(rounded))
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _provenance_text(value: Any) -> str:
    raw = str(value or "").strip()
    labels = {
        "nvidia_service": "NVIDIA 相機服務",
        "libargus": "Libargus 感光元件",
        "v4l2_ioctl": "V4L2 硬體列舉",
        "v4l2-enumerated": "V4L2 硬體列舉",
        "fallback": "備援資料（未驗證）",
    }
    label = labels.get(raw)
    if not label:
        return raw or "硬體回報"
    return f"{label} ({raw})" if raw not in ("fallback",) else label


def _engine_selection(capabilities: Mapping[str, Any], requested_fps: int) -> Any:
    """Import the engine selector lazily so this module has no camera I/O."""
    try:
        from src.engine.camera_capabilities import select_mode_for_fps
    except (ImportError, AttributeError):
        return None
    try:
        return select_mode_for_fps(capabilities, requested_fps)
    except (TypeError, ValueError, KeyError):
        # Malformed or incomplete hardware data must never break the toolbar.
        return None


@dataclass(frozen=True)
class CameraModeUiState:
    """All static text and bounds required by the camera settings toolbar."""

    requested_fps: int
    selected_fps: float
    width: int
    height: int
    pixel_format: str
    min_fps: float
    max_fps: float
    dynamic: bool
    device_text: str
    declared_text: str
    bounds_text: str
    preview_text: str
    input_tooltip: str


def build_camera_mode_ui_state(
    capabilities: Optional[Mapping[str, Any]],
    requested_fps: int,
) -> CameraModeUiState:
    """Build a safe UI model, falling back to the existing IMX219 table."""
    requested = int(requested_fps)
    payload = capabilities if isinstance(capabilities, Mapping) else {}
    modes = payload.get("modes")
    has_dynamic_data = isinstance(modes, (list, tuple)) and bool(modes)
    selection = _engine_selection(payload, requested) if has_dynamic_data else None

    if selection is None:
        fallback = select_imx219_settings(requested)
        selected_fps = float(fallback.fps)
        width = int(fallback.width)
        height = int(fallback.height)
        pixel_format = ""
        min_fps = float(CAMERA_MIN_FPS)
        max_fps = float(CAMERA_MAX_FPS)
        dynamic = False
    else:
        selected_mode = _value(selection, "mode", selection)
        selected_fps = _positive_number(
            _value(
                selection,
                "fps",
                _value(selection, "selected_fps", _value(selected_mode, "fps", requested)),
            ),
            requested,
        )
        width = int(_positive_number(
            _value(selection, "width", _value(selected_mode, "width")),
            0,
        ))
        height = int(_positive_number(
            _value(selection, "height", _value(selected_mode, "height")),
            0,
        ))
        pixel_format = str(
            _value(
                selection,
                "pixel_format",
                _value(selected_mode, "pixel_format", ""),
            )
            or ""
        )
        min_fps = _positive_number(payload.get("min_fps"), CAMERA_MIN_FPS)
        max_fps = _positive_number(payload.get("max_fps"), CAMERA_MAX_FPS)
        if min_fps > max_fps or width <= 0 or height <= 0:
            return build_camera_mode_ui_state(None, requested)
        dynamic = True

    selected_text = _format_fps(selected_fps)
    adjustment = ""
    if requested < min_fps or requested > max_fps:
        adjustment = f"（超限，將採用 {selected_text}）"
    elif abs(float(requested) - selected_fps) >= 0.01:
        adjustment = f"（最接近支援值 {selected_text}）"
    format_suffix = f" / {pixel_format}" if pixel_format else ""
    preview_text = (
        f"→ {width} × {height} / {selected_text} FPS{format_suffix} {adjustment}"
    ).rstrip()

    bounds_text = f"範圍：{_format_fps(min_fps)}–{_format_fps(max_fps)} FPS"
    input_tooltip = f"可輸入整數；裝置目前{bounds_text}，超出時會採用上下限"

    if dynamic:
        device = payload.get("device") if isinstance(payload.get("device"), Mapping) else {}
        device_name = str(device.get("name") or device.get("id") or "已偵測攝影機")
        raw_provenance = str(payload.get("provenance") or "硬體回報")
        provenance = _provenance_text(raw_provenance)
        unverified = bool(_value(selection, "fallback", False)) or raw_provenance == "fallback"
        valid_modes = [
            mode for mode in modes
            if isinstance(mode, Mapping)
            and _positive_number(mode.get("width"), 0) > 0
            and _positive_number(mode.get("height"), 0) > 0
        ]
        largest = max(
            valid_modes,
            key=lambda mode: float(mode.get("width", 0)) * float(mode.get("height", 0)),
            default=None,
        )
        largest_text = "解析度未知"
        if largest is not None:
            largest_text = f"最高 {int(float(largest['width']))} × {int(float(largest['height']))}"
        device_text = f"裝置：{device_name}｜來源：{provenance}"
        if unverified:
            declared_text = (
                f"宣告：尚未取得完整硬體清單｜暫用 {len(valid_modes)} 種未驗證模式｜"
                f"{largest_text}｜{bounds_text}"
            )
        else:
            declared_text = f"宣告：{len(valid_modes)} 種模式｜{largest_text}｜{bounds_text}"
    else:
        device_text = "裝置能力：尚未取得"
        declared_text = (
            f"宣告：等待裝置回報｜暫用內建 IMX219 模式表｜{bounds_text}"
        )

    return CameraModeUiState(
        requested_fps=requested,
        selected_fps=selected_fps,
        width=width,
        height=height,
        pixel_format=pixel_format,
        min_fps=min_fps,
        max_fps=max_fps,
        dynamic=dynamic,
        device_text=device_text,
        declared_text=declared_text,
        bounds_text=bounds_text,
        preview_text=preview_text,
        input_tooltip=input_tooltip,
    )
