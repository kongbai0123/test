"""
src/gui/controls.py
Action control panel toolbar widget with Screenshot, Record, Region, and Audio buttons.
"""

import logging
from typing import Any, Callable, Mapping, Optional

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

from src.config import CAMERA_MAX_FPS, CAMERA_MIN_FPS
from src.gui.camera_mode_view import build_camera_mode_ui_state

logger = logging.getLogger("GUI.Controls")


class ControlsWidget(Gtk.Box):
    """
    Main action toolbar containing big primary trigger buttons.
    """

    def __init__(
        self,
        on_capture_screenshot: Optional[Callable[[], None]] = None,
        on_toggle_record: Optional[Callable[[], None]] = None,
        on_select_region: Optional[Callable[[], None]] = None,
        on_toggle_audio: Optional[Callable[[bool], None]] = None,
        on_open_folder: Optional[Callable[[], None]] = None,
        on_toggle_camera_permission: Optional[Callable[[bool], None]] = None,
        on_apply_camera_fps: Optional[Callable[[int], None]] = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.set_border_width(10)

        self.on_capture_screenshot = on_capture_screenshot
        self.on_toggle_record = on_toggle_record
        self.on_select_region = on_select_region
        self.on_toggle_audio = on_toggle_audio
        self.on_open_folder = on_open_folder
        self.on_toggle_camera_permission = on_toggle_camera_permission
        self.on_apply_camera_fps = on_apply_camera_fps

        self.is_recording = False
        self.audio_enabled = False
        self.region_selected = False
        self.camera_enabled = True
        self.camera_settings_busy = False
        self.camera_capabilities: Optional[Mapping[str, Any]] = None
        self._camera_min_fps = float(CAMERA_MIN_FPS)
        self._camera_max_fps = float(CAMERA_MAX_FPS)
        self._last_measured_fps_text = None

        self._init_ui()

    def _init_ui(self) -> None:
        """Construct control buttons with Camera Permission Toggle at the VERY LEFT."""
        self.action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pack_start(self.action_row, False, False, 0)

        # 1. Camera Permission Toggle Button (FAR LEFT)
        self.cam_perm_btn = Gtk.ToggleButton(label="📷 鏡頭權限：開")
        self.cam_perm_btn.set_active(True)
        self.cam_perm_btn.set_tooltip_text("點擊開關視訊鏡頭存取權限 (開 / 關)")
        self.cam_perm_btn.connect("toggled", self._on_camera_toggled)
        self.action_row.pack_start(self.cam_perm_btn, True, True, 0)

        # 2. Take Screenshot Button
        self.cap_btn = Gtk.Button(label="📷 拍攝快照 (按 S 鍵)")
        self.cap_btn.set_tooltip_text("按鍵 S (不限大小寫) 或點擊此按鈕即可進行手動快照截圖")
        self.cap_btn.connect("clicked", lambda b: self.on_capture_screenshot() if self.on_capture_screenshot else None)
        self.action_row.pack_start(self.cap_btn, True, True, 0)

        # 3. Record Video Button
        self.rec_btn = Gtk.Button(label="🔴 開始錄影 (按 R 鍵)")
        self.rec_btn.set_tooltip_text("按鍵 R (不限大小寫) 或點擊此按鈕即可開始/停止錄影")
        self.rec_btn.connect("clicked", lambda b: self.on_toggle_record() if self.on_toggle_record else None)
        self.action_row.pack_start(self.rec_btn, True, True, 0)

        # 4. Select Region (ROI / Fullscreen)
        self.region_btn = Gtk.Button(label="📐 擷取區域：全螢幕")
        self.region_btn.connect("clicked", lambda b: self.on_select_region() if self.on_select_region else None)
        self.action_row.pack_start(self.region_btn, True, True, 0)

        # 5. Audio Toggle Button
        self.audio_btn = Gtk.ToggleButton(label="🔇 聲音錄製：關")
        self.audio_btn.set_active(False)
        self.audio_btn.connect("toggled", self._on_audio_toggled)
        self.action_row.pack_start(self.audio_btn, True, True, 0)

        # 6. Open Captures Folder Button
        self.folder_btn = Gtk.Button(label="📁 開啟媒體資料夾")
        self.folder_btn.set_tooltip_text("開啟儲存影片與截圖檔案的資料夾")
        self.folder_btn.connect("clicked", lambda b: self.on_open_folder() if self.on_open_folder else None)
        self.action_row.pack_start(self.folder_btn, True, True, 0)

        # Linked FPS/resolution row. The service repeats these bounds, so the
        # camera stays protected even if a different local client calls it.
        self.camera_settings_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        fps_label = Gtk.Label(label="相機 FPS：")
        self.camera_settings_row.pack_start(fps_label, False, False, 0)

        self.camera_fps_entry = Gtk.Entry()
        self.camera_fps_entry.set_width_chars(4)
        self.camera_fps_entry.set_max_length(4)
        self.camera_fps_entry.set_text("30")
        self.camera_fps_entry.set_tooltip_text(
            f"可輸入 {CAMERA_MIN_FPS}–{CAMERA_MAX_FPS}；超出時會自動採用上下限"
        )
        self.camera_fps_entry.connect("changed", self._on_camera_fps_preview)
        self.camera_settings_row.pack_start(self.camera_fps_entry, False, False, 0)

        self.camera_fps_bounds_lbl = Gtk.Label(
            label=f"範圍：{CAMERA_MIN_FPS}–{CAMERA_MAX_FPS} FPS"
        )
        self.camera_fps_bounds_lbl.set_xalign(0.0)
        self.camera_settings_row.pack_start(self.camera_fps_bounds_lbl, False, False, 0)

        self.camera_resolution_lbl = Gtk.Label()
        self.camera_resolution_lbl.set_xalign(0.0)
        self.camera_settings_row.pack_start(self.camera_resolution_lbl, False, False, 0)

        self.camera_apply_btn = Gtk.Button(label="套用 FPS／像素")
        self.camera_apply_btn.set_tooltip_text("短暫重連相機，套用 FPS 與自動選定的最高像素")
        self.camera_apply_btn.connect("clicked", self._on_apply_camera_fps_clicked)
        self.camera_settings_row.pack_start(self.camera_apply_btn, False, False, 0)

        self.camera_current_lbl = Gtk.Label(label="協商：等待相機連線…")
        self.camera_current_lbl.set_xalign(0.0)
        self.camera_current_lbl.set_max_width_chars(45)
        self.camera_current_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.camera_settings_row.pack_start(self.camera_current_lbl, False, False, 8)
        self.pack_start(self.camera_settings_row, False, False, 0)

        # Keep advertised, negotiated and measured values visually distinct.
        # This prevents an accepted request from being mistaken for real output.
        self.camera_capability_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=14,
        )
        self.camera_device_lbl = Gtk.Label(label="裝置能力：尚未取得")
        self.camera_device_lbl.set_xalign(0.0)
        self.camera_device_lbl.set_max_width_chars(42)
        self.camera_device_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.camera_capability_row.pack_start(self.camera_device_lbl, False, False, 0)

        self.camera_declared_lbl = Gtk.Label(label="宣告：等待裝置回報")
        self.camera_declared_lbl.set_xalign(0.0)
        self.camera_declared_lbl.set_max_width_chars(65)
        self.camera_declared_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.camera_capability_row.pack_start(self.camera_declared_lbl, True, True, 0)

        self.camera_measured_lbl = Gtk.Label(label="實測：等待影像…")
        self.camera_measured_lbl.set_xalign(0.0)
        self.camera_capability_row.pack_end(self.camera_measured_lbl, False, False, 0)
        self.pack_start(self.camera_capability_row, False, False, 0)
        self._on_camera_fps_preview(self.camera_fps_entry)

    def _on_camera_toggled(self, btn):
        self.camera_enabled = btn.get_active()
        btn.set_label("📷 鏡頭權限：開" if self.camera_enabled else "📷 鏡頭權限：關")
        self._refresh_camera_settings_sensitivity()
        if self.on_toggle_camera_permission:
            self.on_toggle_camera_permission(self.camera_enabled)

    def set_recording_state(self, is_recording: bool) -> None:
        """Update record button state and icon."""
        self.is_recording = is_recording
        if is_recording:
            self.rec_btn.set_label("⏹️ 停止錄影 (按 R 鍵)")
        else:
            self.rec_btn.set_label("🔴 開始錄影 (按 R 鍵)")
        self._refresh_camera_settings_sensitivity()

    def set_region_label(self, label_text: str) -> None:
        """Update region button label."""
        if "Fullscreen" in label_text or "全螢幕" in label_text:
            label_text = "全螢幕"
        self.region_btn.set_label(f"📐 擷取區域：{label_text}")

    def _on_audio_toggled(self, btn):
        self.audio_enabled = btn.get_active()
        btn.set_label("🎙️ 聲音錄製：開" if self.audio_enabled else "🔇 聲音錄製：關")
        if self.on_toggle_audio:
            self.on_toggle_audio(self.audio_enabled)

    def _parse_camera_fps(self) -> Optional[int]:
        text = self.camera_fps_entry.get_text().strip()
        try:
            return int(text)
        except (TypeError, ValueError):
            return None

    def _on_camera_fps_preview(self, entry) -> None:
        requested = self._parse_camera_fps()
        if requested is None:
            self.camera_resolution_lbl.set_text(
                "請輸入整數"
            )
            return
        state = build_camera_mode_ui_state(self.camera_capabilities, requested)
        self._camera_min_fps = state.min_fps
        self._camera_max_fps = state.max_fps
        self.camera_resolution_lbl.set_text(state.preview_text)
        self.camera_resolution_lbl.set_tooltip_text(state.preview_text)
        self.camera_fps_bounds_lbl.set_text(state.bounds_text)
        self.camera_fps_entry.set_tooltip_text(state.input_tooltip)

    def _on_apply_camera_fps_clicked(self, btn) -> None:
        requested = self._parse_camera_fps()
        if requested is None:
            self.camera_resolution_lbl.set_text(
                "請輸入整數 FPS"
            )
            return
        if self.on_apply_camera_fps:
            # Preserve the raw request so the service also exercises its clamp.
            self.on_apply_camera_fps(requested)

    def set_camera_settings_busy(self, busy: bool) -> None:
        self.camera_settings_busy = busy
        self._refresh_camera_settings_sensitivity()
        if busy:
            self.camera_current_lbl.set_text("切換中，攝影機正在重新連線…")
            self._last_measured_fps_text = None
            self.camera_measured_lbl.set_text("實測：等待套用結果…")

    def _refresh_camera_settings_sensitivity(self) -> None:
        settings_enabled = (
            self.camera_enabled and not self.camera_settings_busy and not self.is_recording
        )
        self.camera_fps_entry.set_sensitive(settings_enabled)
        self.camera_apply_btn.set_sensitive(settings_enabled)
        self.cam_perm_btn.set_sensitive(not self.camera_settings_busy and not self.is_recording)
        self.rec_btn.set_sensitive(not self.camera_settings_busy)

    def update_current_camera_settings(
        self,
        width: int,
        height: int,
        fps: float,
        note: str = "",
        sync_input: bool = False,
        pixel_format: str = "",
    ) -> None:
        fps_value = float(fps)
        fps_display = (
            str(int(round(fps_value)))
            if abs(fps_value - round(fps_value)) < 0.01
            else f"{fps_value:.2f}".rstrip("0").rstrip(".")
        )
        suffix = f"（{note}）" if note else ""
        format_suffix = f" / {pixel_format}" if pixel_format else ""
        text = (
            f"協商：{int(width)} × {int(height)} / {fps_display} FPS"
            f"{format_suffix} {suffix}"
        ).rstrip()
        self.camera_current_lbl.set_text(text)
        self.camera_current_lbl.set_tooltip_text(text)
        if sync_input:
            self.camera_fps_entry.set_text(str(int(round(fps_value))))

    def update_camera_capabilities(
        self,
        capabilities: Optional[Mapping[str, Any]],
    ) -> None:
        """Refresh advertised capabilities and the smart FPS preview."""
        self.camera_capabilities = capabilities if isinstance(capabilities, Mapping) else None
        requested = self._parse_camera_fps()
        if requested is None:
            requested = int(round(self._camera_min_fps))
        state = build_camera_mode_ui_state(self.camera_capabilities, requested)
        self._camera_min_fps = state.min_fps
        self._camera_max_fps = state.max_fps
        self.camera_device_lbl.set_text(state.device_text)
        self.camera_device_lbl.set_tooltip_text(state.device_text)
        self.camera_declared_lbl.set_text(state.declared_text)
        self.camera_declared_lbl.set_tooltip_text(state.declared_text)
        self.camera_fps_bounds_lbl.set_text(state.bounds_text)
        self.camera_fps_entry.set_tooltip_text(state.input_tooltip)
        self._on_camera_fps_preview(self.camera_fps_entry)

    def update_measured_camera_fps(self, measured_fps: float) -> None:
        """Show actual received FPS independently from the negotiated value."""
        try:
            measured = float(measured_fps)
        except (TypeError, ValueError):
            measured = 0.0
        text = f"實測：{measured:.1f} FPS" if measured > 0 else "實測：計算中…"
        if text == self._last_measured_fps_text:
            return
        self._last_measured_fps_text = text
        self.camera_measured_lbl.set_text(text)
        self.camera_measured_lbl.set_tooltip_text(text)

    def reset_camera_runtime_status(self) -> None:
        """Clear negotiated/measured values when the source is disconnected."""
        self.camera_current_lbl.set_text("協商：等待相機連線…")
        self._last_measured_fps_text = None
        self.camera_measured_lbl.set_text("實測：等待影像…")
