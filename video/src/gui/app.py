"""
src/gui/app.py
Unified single-window main application dashboard.
Wiring HeaderBar, Control Panel, Media Gallery, System Tray, Floating Bar, and Capture Engine.
"""

import logging
import json
import math
import os
import sys
import threading
import time
from typing import Any, Mapping, Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from src.config import CaptureConfig, CaptureMode, Region
from src.engine.audio import AudioMixer
from src.engine.camera import CameraStream
from src.engine.preview import LatestFrameProcessor
from src.engine.recorder import VideoRecorder
from src.engine.scheduler import AutoCaptureScheduler
from src.engine.screenshot import ScreenshotEngine
from src.gui.controls import ControlsWidget
from src.gui.header import HeaderWidget
from src.gui.media_panel import MediaPanelWidget
from src.system.floating_bar import FloatingBar
from src.system.hotkeys import HotkeyManager
from src.system.region_picker import RegionPicker
from src.system.tray import TrayService

logger = logging.getLogger("GUI.App")

_CAMERA_RESUME_MAX_RETRIES = 16
_CAMERA_CAPABILITIES_POLL_SECONDS = 1.0
_CAMERA_PREVIEW_INTERVAL_MS = 16


def _camera_capabilities_fingerprint(capabilities: Any) -> str:
    """Fingerprint declared hardware data, excluding per-frame measurements."""
    if not isinstance(capabilities, Mapping):
        return ""
    stable_payload = {
        key: capabilities.get(key)
        for key in ("device", "provenance", "min_fps", "max_fps", "modes")
    }
    try:
        return json.dumps(
            stable_payload,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
    except (TypeError, ValueError):
        return ""


class MainWindow(Gtk.Window):
    """
    Unified Single-Window Main Application Window.
    Strictly zero tabbed navigation / single page layout.
    """

    def __init__(self, output_dir: str = "/home/user/program/video/captures"):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("視訊鏡頭與螢幕錄製擷取系統")
        self.output_dir = os.path.abspath(output_dir)
        self.set_default_size(1450, 900)
        geometry = Gdk.Geometry()
        geometry.min_width = 1280
        geometry.min_height = 760
        self.set_geometry_hints(
            None,
            geometry,
            Gdk.WindowHints.MIN_SIZE,
        )
        self.set_position(Gtk.WindowPosition.CENTER)
        os.makedirs(self.output_dir, exist_ok=True)

        # Core Engines
        self.screenshot_engine = ScreenshotEngine()
        self.video_recorder = VideoRecorder()
        self.audio_mixer = AudioMixer()
        self.camera_stream = CameraStream()
        self.preview_processor = LatestFrameProcessor()
        self.preview_processor.start()
        self.scheduler = AutoCaptureScheduler()
        self.config = CaptureConfig(output_dir=self.output_dir)

        # State
        self.current_region: Optional[Region] = None
        self.is_recording = False
        self._last_camera_status = None
        self._last_camera_settings = None
        self._last_camera_capabilities_fingerprint = None
        self._camera_capabilities_cache = None
        self._next_camera_capabilities_poll = 0.0
        self._camera_settings_busy = False
        self._last_submitted_preview_sequence = -1
        self._last_displayed_preview_sequence = -1

        self._apply_high_contrast_theme()
        self._init_ui()
        self._init_system_services()
        self.header.update_status_badge("IDLE", "green")

    def _apply_high_contrast_theme(self) -> None:
        """Apply WCAG AAA high-contrast dark theme CSS provider with USER priority."""
        css_provider = Gtk.CssProvider()
        css_data = b"""
        * {
            font-family: "Ubuntu", "DejaVu Sans", "Segoe UI", sans-serif;
            text-shadow: none;
        }

        window, window box, window paned, window scrolledwindow, window viewport {
            background-color: #16161E;
            color: #FFFFFF;
        }

        headerbar {
            background-color: #0F0F16;
            background-image: none;
            color: #FFFFFF;
            border-bottom: 2px solid #2B2B3D;
            padding: 6px 12px;
        }

        headerbar .title, headerbar label.title {
            color: #FFFFFF;
            font-weight: bold;
            font-size: 15px;
        }

        headerbar .subtitle, headerbar label.subtitle {
            color: #2ECC71;
            font-weight: bold;
            font-size: 11px;
        }

        headerbar label {
            color: #FFFFFF;
            font-weight: bold;
            font-size: 13px;
        }

        headerbar entry, entry {
            background-color: #242434;
            background-image: none;
            color: #FFFFFF;
            border: 2px solid #4A4A66;
            border-radius: 6px;
            padding: 4px 8px;
            font-weight: bold;
            font-size: 13px;
        }

        headerbar combobox, headerbar combobox button, combobox button {
            background-color: #242434;
            background-image: none;
            color: #FFFFFF;
            border: 2px solid #4A4A66;
            border-radius: 6px;
            padding: 2px 6px;
        }

        headerbar combobox cellview, combobox cellview {
            color: #FFFFFF;
            font-weight: bold;
        }

        menu, popover {
            background-color: #1F1F2C;
            color: #FFFFFF;
            border: 1px solid #4A4A66;
        }

        menuitem label {
            color: #FFFFFF;
            font-weight: bold;
        }

        button, togglebutton {
            background-color: #242434;
            background-image: none;
            color: #FFFFFF;
            border: 2px solid #4A4A66;
            border-radius: 8px;
            padding: 8px 16px;
            font-weight: bold;
            font-size: 14px;
            text-shadow: none;
            box-shadow: none;
        }

        button:hover, togglebutton:hover {
            background-color: #34344A;
            background-image: none;
            border-color: #6C6C94;
            color: #FFFFFF;
        }

        button:checked, togglebutton:checked, button:active, togglebutton:active {
            background-color: #2980B9;
            background-image: none;
            border-color: #3498DB;
            color: #FFFFFF;
        }

        button label, togglebutton label, button *, togglebutton * {
            color: #FFFFFF;
            font-weight: bold;
            font-size: 14px;
            text-shadow: none;
        }

        .badge-idle {
            background-color: #27AE60;
            background-image: none;
            color: #FFFFFF;
            border-radius: 12px;
            padding: 4px 14px;
            font-weight: bold;
            font-size: 13px;
        }

        .badge-recording {
            background-color: #E74C3C;
            background-image: none;
            color: #FFFFFF;
            border-radius: 12px;
            padding: 4px 14px;
            font-weight: bold;
            font-size: 13px;
        }

        .badge-auto {
            background-color: #2980B9;
            background-image: none;
            color: #FFFFFF;
            border-radius: 12px;
            padding: 4px 14px;
            font-weight: bold;
            font-size: 13px;
        }

        iconview {
            background-color: #14141C;
            color: #FFFFFF;
        }

        iconview:selected {
            background-color: #D35400;
            color: #FFFFFF;
        }

        iconview label {
            color: #FFFFFF;
            font-weight: bold;
        }
        """
        try:
            css_provider.load_from_data(css_data)
            screen = Gdk.Screen.get_default()
            if screen:
                Gtk.StyleContext.add_provider_for_screen(
                    screen,
                    css_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_USER,
                )
        except Exception as e:
            logger.warning("Could not load high-contrast CSS theme: %s", e)


    def _init_ui(self) -> None:
        """Construct GUI components and layout."""
        # HeaderBar
        self.header = HeaderWidget(
            on_mode_changed=self._on_mode_changed,
            on_interval_changed=self._on_interval_changed,
        )
        self.set_titlebar(self.header)

        # Main Vertical Container
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Action Controls Bar
        self.controls = ControlsWidget(
            on_capture_screenshot=self._on_capture_screenshot,
            on_toggle_record=self._on_toggle_record,
            on_select_region=self._on_select_region,
            on_toggle_audio=self._on_toggle_audio,
            on_open_folder=self._on_open_captures_folder,
            on_toggle_camera_permission=self._on_toggle_camera_permission,
            on_apply_camera_fps=self._on_apply_camera_fps,
        )
        main_vbox.pack_start(self.controls, False, False, 0)

        # Separator
        main_vbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        # Media Gallery & Preview Panel
        self.media_panel = MediaPanelWidget(
            output_dir=self.output_dir,
            on_open_folder=self._on_open_captures_folder,
        )
        main_vbox.pack_start(self.media_panel, True, True, 0)

        self.add(main_vbox)

        # Connect destroy & key shortcuts
        self.connect("destroy", self._on_quit)
        self.connect("key-press-event", self._on_key_press)

        # Initial camera permission check & load captures
        GLib.idle_add(self._on_toggle_camera_permission)
        GLib.idle_add(self.media_panel.refresh)
        # Poll slightly faster than the supported 60 FPS ceiling. The camera
        # worker still owns blocking I/O and only the newest frame is rendered.
        GLib.timeout_add(_CAMERA_PREVIEW_INTERVAL_MS, self._update_camera_preview)

    def _init_system_services(self) -> None:
        """Initialize System Tray, Floating Bar, Region Picker, and Global Hotkeys."""
        # Floating Control Bar
        self.floating_bar = FloatingBar()

        # Region Selector Overlay
        self.region_picker = RegionPicker(on_selected=self._on_region_selected)

        # System Tray
        self.tray = TrayService(
            on_show_hide=self._toggle_visibility,
            on_mode_toggle=self._toggle_mode_shortcut,
            on_capture=self._on_capture_screenshot,
            on_record=self._on_toggle_record,
            on_quit=self._on_quit,
        )

        # Global Hotkeys
        self.hotkeys = HotkeyManager()
        self.hotkeys.register_hotkey("Ctrl+Alt+A", self._on_capture_screenshot)
        self.hotkeys.register_hotkey("Ctrl+Alt+R", self._on_toggle_record)
        self.hotkeys.start()

    # --- Mode & Interval Event Handlers ---

    def _on_mode_changed(self, mode: CaptureMode) -> None:
        """Handle Manual vs Automatic mode switch."""
        self.config.mode = mode
        logger.info("Capture mode switched to %s", mode)
        if mode == CaptureMode.AUTOMATIC:
            self.header.update_status_badge("AUTO_ACTIVE", "blue")
            self.scheduler.start(
                interval=self.config.interval,
                callback=self._auto_capture_tick,
            )
        else:
            self.header.update_status_badge("IDLE", "green")
            self.scheduler.stop()

    def _on_interval_changed(self, interval: float) -> None:
        """Handle interval textbox adjustment."""
        self.config.interval = interval
        logger.info("Auto interval updated to %.2f seconds", interval)
        if self.config.mode == CaptureMode.AUTOMATIC:
            self.scheduler.update_interval(interval)

    def _auto_capture_tick(self) -> None:
        """Callback executed on each auto-capture interval tick."""
        GLib.idle_add(self._on_capture_screenshot)

    def _on_key_press(self, widget, event) -> bool:
        """Handle global Tab/S/R shortcuts for mode, screenshot, and recording."""
        keyname = Gdk.keyval_name(event.keyval) or ""
        keyname_lower = keyname.lower()

        # Tab (including Shift+Tab / keypad Tab) -> Toggle Manual / Automatic mode.
        # Handle this before the Entry guard so it works while editing the interval.
        tab_keys = (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab, Gdk.KEY_KP_Tab)
        if keyname_lower in ("tab", "iso_left_tab", "kp_tab") or event.keyval in tab_keys:
            self._toggle_mode_shortcut()
            return True

        focused = self.get_focus()
        if isinstance(focused, Gtk.Entry):
            return False

        # Key 's' or 'S' or Space -> Trigger Manual Screenshot
        if keyname_lower in ("s", "space") or event.keyval in (Gdk.KEY_space, Gdk.KEY_s, Gdk.KEY_S):
            self._on_capture_screenshot()
            return True

        # Key 'r' or 'R' -> Trigger Record Toggle
        if keyname_lower == "r" or event.keyval in (Gdk.KEY_r, Gdk.KEY_R):
            self._on_toggle_record()
            return True

        return False

    def _on_open_captures_folder(self) -> None:
        """Open destination captures output folder in Linux file manager."""
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            logger.info("Opening captures output folder: %s", self.output_dir)
            os.system(f"xdg-open '{self.output_dir}' &")
        except Exception as e:
            logger.error("Failed to open captures folder: %s", e)

    def _on_toggle_camera_permission(self, enabled: bool = True) -> None:
        """Handle 1-click Camera Permission Toggle (開 / 關)."""
        if self._camera_settings_busy:
            return
        logger.info("Camera permission toggled: %s", enabled)
        if not enabled:
            self.config.capture_source = "disabled"
            self.camera_stream.stop()
            self.header.update_camera_badge("鏡頭權限：已關閉", is_live=False)
            self.media_panel.update_camera_message("鏡頭已關閉")
            self._last_camera_status = (False, "disabled", "")
            self._last_camera_settings = None
            self._last_camera_capabilities_fingerprint = None
            self._camera_capabilities_cache = None
            self._next_camera_capabilities_poll = 0.0
            self.controls.update_camera_capabilities(None)
            self.controls.reset_camera_runtime_status()
            return

        self.config.capture_source = "camera"
        self.media_panel.show_live_preview()
        self.media_panel.update_camera_message("正在連接攝影機…")
        self.header.update_camera_badge("鏡頭連線中…", is_live=False)
        self._last_camera_status = None
        self._last_camera_settings = None
        self._last_camera_capabilities_fingerprint = None
        self._camera_capabilities_cache = None
        self._next_camera_capabilities_poll = 0.0
        self.controls.update_camera_capabilities(None)
        self.controls.reset_camera_runtime_status()
        self.camera_stream.start()

    def _on_apply_camera_fps(self, requested_fps: int) -> None:
        """Apply linked FPS/resolution through the active source's proper owner."""
        if self.is_recording:
            self.controls.update_current_camera_settings(
                *self.camera_stream.source_settings,
                note="請先停止錄影再切換",
            )
            return
        connected, device, _ = self.camera_stream.status
        if not connected:
            self.controls.update_current_camera_settings(
                *self.camera_stream.source_settings,
                note="攝影機尚未連線",
            )
            return
        if self._camera_settings_busy:
            return

        self._camera_settings_busy = True
        self.controls.set_camera_settings_busy(True)
        source_name = "NVIDIA CSI" if self.camera_stream.uses_nvidia_service else "USB"
        self.media_panel.update_camera_message(
            f"正在套用 {source_name} 的 FPS 與對應像素，攝影機將短暫重連…"
        )
        self.header.update_camera_badge("相機模式切換中…", is_live=False)

        def worker() -> None:
            try:
                if not self.camera_stream.stop():
                    raise RuntimeError("舊的攝影機串流仍在停止中")
                result = self.camera_stream.request_camera_fps(requested_fps)
                GLib.idle_add(self._finish_camera_fps_change, result, None)
            except Exception as exc:
                GLib.idle_add(self._finish_camera_fps_change, None, str(exc))

        threading.Thread(target=worker, name="camera-fps-change", daemon=True).start()

    def _finish_camera_fps_change(self, result, error) -> bool:
        self._camera_settings_busy = False
        self.controls.set_camera_settings_busy(False)
        self._last_camera_status = None
        self._last_camera_settings = None
        self._last_camera_capabilities_fingerprint = None
        self._camera_capabilities_cache = None
        self._next_camera_capabilities_poll = 0.0
        apply_error = str(error) if error else ""
        parsed_result = None
        if not apply_error:
            try:
                if not isinstance(result, Mapping):
                    raise ValueError("相機未回傳設定結果")
                width = int(result["width"])
                height = int(result["height"])
                negotiated_fps = float(result["fps"])
                if (
                    width <= 0
                    or height <= 0
                    or negotiated_fps <= 0
                    or not math.isfinite(negotiated_fps)
                ):
                    raise ValueError("解析度或 FPS 無效")

                measured_fps = 0.0
                measured_status = ""
                measured = result.get("measured")
                if isinstance(measured, Mapping):
                    try:
                        measured_fps = float(measured.get("fps", 0))
                    except (TypeError, ValueError, OverflowError):
                        measured_fps = 0.0
                    if not math.isfinite(measured_fps) or measured_fps <= 0:
                        measured_fps = 0.0
                    measured_status = str(measured.get("status") or "")

                negotiated = result.get("negotiated")
                nested_adjusted = (
                    bool(negotiated.get("adjusted"))
                    if isinstance(negotiated, Mapping)
                    else False
                )

                parsed_result = {
                    "width": width,
                    "height": height,
                    "fps": negotiated_fps,
                    "pixel_format": str(result.get("pixel_format") or ""),
                    "snapped": bool(result.get("snapped")),
                    "clamped": bool(result.get("clamped")),
                    "negotiation_adjusted": bool(result.get("negotiation_adjusted"))
                    or nested_adjusted,
                    "measured_fps": measured_fps,
                    "measured_status": measured_status,
                }
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                apply_error = f"回傳結果無效：{exc}"

        try:
            if apply_error:
                self.controls.update_current_camera_settings(
                    *self.camera_stream.source_settings,
                    note=f"套用失敗：{apply_error}",
                )
                self.media_panel.update_camera_message(f"相機設定失敗：{apply_error}")
                self.header.update_camera_badge("相機設定失敗，正在恢復…", is_live=False)
            else:
                width = parsed_result["width"]
                height = parsed_result["height"]
                negotiated_fps = parsed_result["fps"]
                fps = max(1, int(round(negotiated_fps)))
                self.config.fps = fps
                note = "已套用"
                if parsed_result["snapped"]:
                    note = f"已採用最接近的支援值 {negotiated_fps:g} FPS"
                elif parsed_result["clamped"]:
                    note = f"輸入超限，已採用 {negotiated_fps:g} FPS"
                if parsed_result["negotiation_adjusted"]:
                    format_text = (
                        f" / {parsed_result['pixel_format']}"
                        if parsed_result["pixel_format"]
                        else ""
                    )
                    note += (
                        f"；驅動調整為 {width} × {height} / "
                        f"{negotiated_fps:g} FPS{format_text}"
                    )
                measured_fps = parsed_result["measured_fps"]
                if measured_fps > 0:
                    if parsed_result["measured_status"] == "degraded":
                        note += f"；短測 {measured_fps:.1f} FPS（低於協商值）"
                    else:
                        note += f"；短測 {measured_fps:.1f} FPS"
                    self.controls.update_measured_camera_fps(measured_fps)
                self.controls.update_current_camera_settings(
                    width,
                    height,
                    negotiated_fps,
                    note=note,
                    sync_input=True,
                    pixel_format=parsed_result["pixel_format"],
                )
                self.media_panel.update_camera_message("設定完成，正在重新接收影像…")
                self.header.update_camera_badge("鏡頭重新連線中…", is_live=False)
        finally:
            # Validation owns the USB device while preview is stopped.  Every
            # completion path must hand it back exactly once, including a bad
            # engine/service response.
            self._resume_camera_preview_when_ready()
        return False

    def _resume_camera_preview_when_ready(self, retry_count: int = 0) -> bool:
        """Restart after a previous capture thread has actually stopped."""
        if self.config.capture_source != "camera" or self.is_recording:
            return False
        if not self.camera_stream.is_running:
            self.camera_stream.start()
            return False

        # A healthy/connecting worker is already the desired result.  Only a
        # worker with its stop event set can be the old owner we must wait for.
        stopping = bool(getattr(self.camera_stream, "is_stopping", False))
        stop_event = getattr(self.camera_stream, "_stop_event", None)
        if not stopping and stop_event is not None:
            try:
                stopping = bool(stop_event.is_set())
            except (AttributeError, TypeError):
                stopping = False
        if stopping and retry_count < _CAMERA_RESUME_MAX_RETRIES:
            GLib.timeout_add(
                250,
                self._resume_camera_preview_when_ready,
                retry_count + 1,
            )
        return False

    def _update_camera_preview(self) -> bool:
        """Poll the worker's latest frame; camera I/O never blocks GTK's UI thread."""
        if self.config.capture_source != "camera" or self.is_recording:
            return True
        # Production uses a zero-copy snapshot and performs resize/colour
        # conversion on a dedicated latest-frame worker. Keep the legacy path
        # for small test doubles and third-party CameraStream substitutes.
        snapshot_getter = getattr(self.camera_stream, "get_frame_snapshot", None)
        parallel_preview = snapshot_getter is not None and hasattr(
            self, "preview_processor"
        )
        if parallel_preview:
            snapshot = snapshot_getter(self._last_submitted_preview_sequence)
            frame = snapshot[1] if snapshot is not None else None
        else:
            snapshot = None
            frame = self.camera_stream.get_frame()
        connected, device, error = self.camera_stream.status
        now = time.monotonic()
        if now >= getattr(self, "_next_camera_capabilities_poll", 0.0):
            capabilities = getattr(self.camera_stream, "capabilities", None)
            self._camera_capabilities_cache = capabilities
            self._next_camera_capabilities_poll = now + _CAMERA_CAPABILITIES_POLL_SECONDS
            capabilities_fingerprint = _camera_capabilities_fingerprint(capabilities)
            if capabilities_fingerprint != self._last_camera_capabilities_fingerprint:
                self.controls.update_camera_capabilities(capabilities)
                self._last_camera_capabilities_fingerprint = capabilities_fingerprint
        else:
            capabilities = getattr(self, "_camera_capabilities_cache", None)
        if connected and (frame is not None or parallel_preview):
            status = (True, device, "")
            if status != self._last_camera_status:
                self.header.update_camera_badge(f"實體鏡頭：{device} (LIVE)", is_live=True)
                self._last_camera_status = status
            source_width, source_height, configured_fps = self.camera_stream.source_settings
            current = capabilities.get("current") if isinstance(capabilities, Mapping) else None
            pixel_format = str(current.get("pixel_format") or "") if isinstance(current, Mapping) else ""
            settings = (source_width, source_height, configured_fps, pixel_format)
            if settings != self._last_camera_settings:
                self.controls.update_current_camera_settings(
                    source_width,
                    source_height,
                    configured_fps,
                    sync_input=self._last_camera_settings is None,
                    pixel_format=pixel_format,
                )
                self.config.fps = int(round(configured_fps))
                self._last_camera_settings = settings
            if parallel_preview:
                if snapshot is not None:
                    sequence, snapshot_frame = snapshot
                    if self.preview_processor.submit(
                        sequence,
                        snapshot_frame,
                        measured_fps=self.camera_stream.measured_fps,
                        configured_fps=configured_fps,
                    ):
                        self._last_submitted_preview_sequence = sequence
                prepared = self.preview_processor.get_latest(
                    self._last_displayed_preview_sequence
                )
                if prepared is not None:
                    self.media_panel.update_prepared_live_frame(prepared)
                    self._last_displayed_preview_sequence = prepared.sequence
            else:
                self.media_panel.update_live_frame(
                    frame,
                    measured_fps=self.camera_stream.measured_fps,
                    configured_fps=configured_fps,
                )
            self.controls.update_measured_camera_fps(self.camera_stream.measured_fps)
        else:
            status = (False, device, error)
            if status != self._last_camera_status:
                self.header.update_camera_badge("未偵測到鏡頭", is_live=False)
                self.media_panel.update_camera_message(error or "正在連接攝影機…")
                self.controls.reset_camera_runtime_status()
                self._last_camera_status = status
        return True

    # --- Action Event Handlers ---

    def _on_capture_screenshot(self) -> None:
        """Take an immediate screenshot."""
        try:
            if self.config.capture_source == "disabled":
                self.media_panel.show_live_preview()
                self.media_panel.update_camera_message("請先開啟鏡頭，才能拍攝快照")
                return
            if self.config.capture_source == "camera":
                import cv2
                from PIL import Image
                frame = self.camera_stream.get_frame()
                if frame is None:
                    raise RuntimeError("攝影機尚未連線，無法拍攝")
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb, "RGB")
                filepath = self.screenshot_engine.save_image_to_file(
                    image=image,
                    output_dir=self.output_dir,
                    image_format=self.config.image_format,
                )
            else:
                filepath = self.screenshot_engine.capture_screenshot(
                    region=self.current_region,
                    output_dir=self.output_dir,
                    image_format=self.config.image_format,
                    source=self.config.capture_source,
                )
            logger.info("Screenshot saved: %s", filepath)
            GLib.idle_add(self.media_panel.refresh)
        except Exception as e:
            logger.error("Failed taking screenshot: %s", e)

    def _on_toggle_record(self) -> None:
        """Toggle video recording Start / Stop."""
        if not self.is_recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        """Start video recording."""
        try:
            if self.config.capture_source == "disabled":
                self.media_panel.show_live_preview()
                self.media_panel.update_camera_message("請先開啟鏡頭，才能開始錄影")
                return
            if self.config.capture_source == "camera" and not self.camera_stream.connected:
                self.media_panel.show_live_preview()
                self.media_panel.update_camera_message("攝影機尚未連線，無法開始錄影")
                return
            recording_source = self.camera_stream.recording_source
            if self.config.capture_source == "camera" and recording_source is None:
                raise RuntimeError("無法確認目前攝影機來源，已取消錄影")
            if self.config.capture_source != "camera":
                recording_source = self.config.capture_source
            source_width, source_height, _ = self.camera_stream.source_settings
            capabilities = self.camera_stream.capabilities
            current = capabilities.get("current") if isinstance(capabilities, Mapping) else None
            pixel_format = (
                str(current.get("pixel_format") or "")
                if isinstance(current, Mapping)
                else ""
            )
            # A V4L2 camera generally cannot be owned by preview and recorder at once.
            if not self.camera_stream.stop():
                raise RuntimeError("攝影機預覽尚未停止，已取消錄影以避免裝置衝突")
            self.is_recording = True
            self.controls.set_recording_state(True)
            self.tray.set_recording_state(True)
            self.header.update_status_badge("RECORDING", "red")

            recording_config = CaptureConfig(
                capture_source=recording_source,
                region=self.current_region,
                output_dir=self.output_dir,
                video_format=self.config.video_format,
                audio_enabled=self.config.audio_enabled,
                audio_source=self.config.audio_source,
                fps=self.config.fps,
                camera_width=source_width,
                camera_height=source_height,
                camera_pixel_format=pixel_format,
                nvenc_enabled=self.config.nvenc_enabled,
            )
            self.video_recorder.start_recording(config=recording_config)

            self.floating_bar.show_bar(
                on_pause=self._on_pause_recording,
                on_stop=self._stop_recording,
            )

            # Start timer loop for floating bar
            GLib.timeout_add(1000, self._update_recording_timer)
        except Exception as e:
            logger.error("Error starting recording: %s", e)
            self.is_recording = False
            self.controls.set_recording_state(False)
            self.tray.set_recording_state(False)
            self.header.update_status_badge("IDLE", "green")
            if self.config.capture_source == "camera":
                self._resume_camera_preview_when_ready()

    def _update_recording_timer(self) -> bool:
        """Update floating bar recording timer."""
        if not self.is_recording:
            return False
        elapsed = self.video_recorder.get_elapsed_seconds()
        self.floating_bar.update_timer(elapsed)
        return True

    def _on_pause_recording(self) -> None:
        """Pause or resume video recording."""
        if self.video_recorder.is_paused():
            self.video_recorder.resume()
            self.floating_bar.set_paused(False)
        else:
            self.video_recorder.pause()
            self.floating_bar.set_paused(True)

    def _stop_recording(self) -> None:
        """Stop video recording."""
        if not self.is_recording:
            return
        self.is_recording = False
        self.controls.set_recording_state(False)
        self.tray.set_recording_state(False)
        self.header.update_status_badge("IDLE", "green")
        self.floating_bar.hide_bar()

        try:
            filepath = self.video_recorder.stop_recording()
            logger.info("Video recording stopped & saved: %s", filepath)
            GLib.idle_add(self.media_panel.refresh)
        except Exception as e:
            logger.error("Error stopping recording: %s", e)
        finally:
            if self.config.capture_source == "camera":
                self.media_panel.show_live_preview()
                self.camera_stream.start()

    def _on_select_region(self) -> None:
        """Trigger region selection overlay."""
        self.region_picker.select_region(on_selected=self._on_region_selected)

    def _on_region_selected(self, region: Optional[Region]) -> None:
        """Callback when ROI region is selected."""
        self.current_region = region
        if region:
            self.controls.set_region_label(f"自訂範圍 ({region.width}x{region.height})")
        else:
            self.controls.set_region_label("全螢幕")

    def _on_toggle_audio(self, enabled: bool) -> None:
        """Toggle audio recording."""
        self.config.audio_enabled = enabled

    def _toggle_visibility(self) -> None:
        """Toggle main window show/hide."""
        if self.is_visible():
            self.hide()
        else:
            self.show_all()
            self.present()

    def _toggle_mode_shortcut(self) -> None:
        """Toggle manual vs auto mode from tray."""
        new_mode = CaptureMode.AUTOMATIC if self.config.mode == CaptureMode.MANUAL else CaptureMode.MANUAL
        self.header.mode_combo.set_active_id(new_mode.value)

    def _on_quit(self, *args) -> None:
        """Clean shutdown."""
        logger.info("Shutting down application...")
        if self.scheduler:
            self.scheduler.stop()
        if self.hotkeys:
            self.hotkeys.stop()
        if self.camera_stream:
            self.camera_stream.stop()
        if getattr(self, "preview_processor", None):
            self.preview_processor.stop()
        if self.is_recording:
            self.video_recorder.stop_recording()
        Gtk.main_quit()
        sys.exit(0)
