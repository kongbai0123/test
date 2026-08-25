"""
src/media/player.py
In-app image preview and video playback controller using GTK and GdkPixbuf.
"""

import logging
import os
from typing import Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from src.media import MediaItem

logger = logging.getLogger("Media.Player")


class MediaPreviewWidget(Gtk.Box):
    """
    Embedded single-pane media preview widget.
    Supports zooming/fitting images and video metadata display / frame playback preview.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)

        self.current_item: Optional[MediaItem] = None
        self.pixbuf: Optional[GdkPixbuf.Pixbuf] = None
        self._live_frame_bytes = None

        self._init_ui()

    def _init_ui(self) -> None:
        """Construct preview area."""
        # Top Metadata Label
        self.info_lbl = Gtk.Label(label="未選擇媒體項目")
        self.info_lbl.set_halign(Gtk.Align.START)
        self.pack_start(self.info_lbl, False, False, 5)

        # Main View Stack (Image View or Placeholder)
        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.image_widget = Gtk.Image()
        self.scrolled.add(self.image_widget)
        self.pack_start(self.scrolled, True, True, 0)

        # Control Toolbar for Video / Image actions
        self.toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.open_btn = Gtk.Button(label="使用外部播放器開啟")
        self.open_btn.connect("clicked", self._on_open_external)
        self.toolbar.pack_start(self.open_btn, False, False, 5)

        self.live_btn = Gtk.Button(label="📹 回到鏡頭即時畫面")
        self.live_btn.set_no_show_all(True)
        self.toolbar.pack_start(self.live_btn, False, False, 5)

        self.pack_start(self.toolbar, False, False, 5)

    def load_item(self, item: Optional[MediaItem]) -> None:
        """Load and display MediaItem in preview area."""
        self.current_item = item
        self.open_btn.show()
        self.live_btn.show()
        if not item or not os.path.exists(item.filepath):
            self.info_lbl.set_markup('<span foreground="#FFFFFF" weight="bold">未選擇媒體項目</span>')
            self.image_widget.clear()
            return

        mb_size = item.filesize / (1024 * 1024)
        mtype = "圖片" if item.media_type == "image" else "影片"
        safe_filename = GLib.markup_escape_text(item.filename)
        self.info_lbl.set_markup(
            f'<span foreground="#FFFFFF" weight="bold">📄 {safe_filename} | 類型：{mtype} | 大小：{mb_size:.2f} MB</span>'
        )

        try:
            if item.media_type == "image":
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(item.filepath)
                # Scale to reasonable preview bounds if huge
                w, h = pixbuf.get_width(), pixbuf.get_height()
                max_dim = 900
                if w > max_dim or h > max_dim:
                    scale = min(max_dim / w, max_dim / h)
                    nw, nh = int(w * scale), int(h * scale)
                    pixbuf = pixbuf.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR)
                self.image_widget.set_from_pixbuf(pixbuf)
            elif item.media_type == "video":
                # Load video thumbnail frame
                if item.thumbnail_path and os.path.exists(item.thumbnail_path):
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(item.thumbnail_path)
                    self.image_widget.set_from_pixbuf(pixbuf)
                else:
                    self.image_widget.set_from_icon_name("video-x-generic", Gtk.IconSize.DIALOG)
        except Exception as e:
            logger.error("Error loading preview for %s: %s", item.filepath, e)
            self.image_widget.clear()

    def show_live_frame(
        self,
        frame,
        measured_fps: float = 0.0,
        configured_fps: float = 0.0,
    ) -> None:
        """Render an OpenCV BGR frame in the GTK preview without writing a temp file."""
        import cv2

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        source_height, source_width = rgb.shape[:2]
        height, width = source_height, source_width
        max_width, max_height = 1000, 680
        scale = min(max_width / width, max_height / height, 1.0)
        if scale < 1.0:
            width, height = max(1, int(width * scale)), max(1, int(height * scale))
            rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_AREA)
        rgb = rgb.copy()
        self._live_frame_bytes = GLib.Bytes.new(rgb.tobytes())
        pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
            self._live_frame_bytes,
            GdkPixbuf.Colorspace.RGB,
            False,
            8,
            width,
            height,
            width * 3,
        )
        self.image_widget.set_from_pixbuf(pixbuf)
        configured_text = (
            f"來源設定：{configured_fps:.0f} FPS" if configured_fps > 0 else "來源 FPS 未知"
        )
        measured_text = (
            f"實際接收：{measured_fps:.1f} FPS" if measured_fps > 0 else "實際接收：計算中…"
        )
        self.info_lbl.set_markup(
            f'<span foreground="#2ECC71" weight="bold">● 攝影機即時畫面　'
            f'原始輸出：{source_width} × {source_height}　|　{configured_text}　|　'
            f'{measured_text}　'
            f'<span foreground="#AAB2C8">（預覽自動縮放）</span></span>'
        )
        self.current_item = None
        self.open_btn.hide()
        self.live_btn.hide()

    def show_prepared_live_frame(self, prepared) -> None:
        """Render bytes prepared by the background latest-frame worker."""
        self._live_frame_bytes = GLib.Bytes.new(prepared.data)
        pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
            self._live_frame_bytes,
            GdkPixbuf.Colorspace.RGB,
            False,
            8,
            prepared.width,
            prepared.height,
            prepared.width * 3,
        )
        self.image_widget.set_from_pixbuf(pixbuf)
        configured_text = (
            f"來源設定：{prepared.configured_fps:.0f} FPS"
            if prepared.configured_fps > 0
            else "來源 FPS 未知"
        )
        measured_text = (
            f"實際接收：{prepared.measured_fps:.1f} FPS"
            if prepared.measured_fps > 0
            else "實際接收：計算中…"
        )
        self.info_lbl.set_markup(
            f'<span foreground="#2ECC71" weight="bold">● 攝影機即時畫面　'
            f'原始輸出：{prepared.source_width} × {prepared.source_height}　|　'
            f'{configured_text}　|　{measured_text}　'
            f'<span foreground="#AAB2C8">（平行處理／自動縮放）</span></span>'
        )
        self.current_item = None
        self.open_btn.hide()
        self.live_btn.hide()

    def show_camera_message(self, message: str) -> None:
        """Show an honest camera connection/permission message in the preview pane."""
        self.current_item = None
        self.image_widget.clear()
        self.info_lbl.set_markup(
            f'<span foreground="#FFB74D" weight="bold">📷 {GLib.markup_escape_text(message)}</span>'
        )
        self.open_btn.hide()
        self.live_btn.hide()

    def _on_open_external(self, btn):
        if self.current_item and os.path.exists(self.current_item.filepath):
            try:
                os.system(f"xdg-open '{self.current_item.filepath}' &")
            except Exception as e:
                logger.error("Failed to open file externally: %s", e)
