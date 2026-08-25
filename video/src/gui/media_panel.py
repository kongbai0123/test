"""
src/gui/media_panel.py
Embedded media gallery panel with split-view layout:
Left: Recent captures list (thumbnails + filename)
Right: In-app media previewer & player
"""

import logging
import os
from typing import Callable, List, Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gtk

from src.media import MediaItem
from src.media.manager import MediaManager
from src.media.player import MediaPreviewWidget
from src.media.thumbnail import ThumbnailGenerator

logger = logging.getLogger("GUI.MediaPanel")


class MediaPanelWidget(Gtk.Paned):
    """
    Split-pane Media Gallery & Preview Panel embedded directly in the single main window.
    """

    def __init__(self, output_dir: str, on_open_folder: Optional[Callable[[], None]] = None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.output_dir = output_dir
        self.on_open_folder = on_open_folder

        self.media_manager = MediaManager()
        self.thumb_gen = ThumbnailGenerator()
        self.items: List[MediaItem] = []
        self.live_preview_enabled = True

        self._init_ui()

    def _init_ui(self) -> None:
        """Construct split view."""
        # Left Side: Captures List
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        left_box.set_border_width(5)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        lbl = Gtk.Label()
        lbl.set_markup('<span foreground="#FFFFFF" weight="bold">最近擷取項目</span>')
        header_box.pack_start(lbl, True, True, 0)

        refresh_btn = Gtk.Button(label="🔄 重新整理")
        refresh_btn.connect("clicked", lambda b: self.refresh())
        header_box.pack_end(refresh_btn, False, False, 0)

        left_box.pack_start(header_box, False, False, 5)

        # ListStore: [Thumbnail Pixbuf, Filename, MediaItem]
        self.store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, object)
        self.icon_view = Gtk.IconView(model=self.store)
        self.icon_view.set_pixbuf_column(0)
        self.icon_view.set_text_column(1)
        self.icon_view.set_item_width(120)
        self.icon_view.connect("selection-changed", self._on_selection_changed)

        scrolled_list = Gtk.ScrolledWindow()
        scrolled_list.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_list.add(self.icon_view)
        left_box.pack_start(scrolled_list, True, True, 0)

        self.pack1(left_box, False, False)

        # Right Side: Media Preview Widget
        self.preview_widget = MediaPreviewWidget()
        self.preview_widget.live_btn.connect("clicked", lambda _button: self.show_live_preview())
        self.pack2(self.preview_widget, True, False)

        self.set_position(320)

    def refresh(self) -> None:
        """Refresh recent captures list from output directory."""
        self.store.clear()
        self.items = self.media_manager.scan_captures(self.output_dir)

        for item in self.items:
            thumb_path = self.thumb_gen.get_thumbnail(item, size=64)
            pixbuf = None
            if thumb_path and os.path.exists(thumb_path):
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(thumb_path)
                except Exception:
                    pass

            if not pixbuf:
                icon_name = "image-x-generic" if item.media_type == "image" else "video-x-generic"
                pixbuf = Gtk.IconTheme.get_default().load_icon(icon_name, 48, 0)

            # Copy item with thumbnail path attached
            item_with_thumb = MediaItem(
                filepath=item.filepath,
                filename=item.filename,
                media_type=item.media_type,
                filesize=item.filesize,
                timestamp=item.timestamp,
                thumbnail_path=thumb_path,
            )
            self.store.append([pixbuf, item.filename, item_with_thumb])

        if len(self.items) > 0 and not self.live_preview_enabled:
            # Select first item by default
            self.icon_view.select_path(Gtk.TreePath.new_first())

    def _on_selection_changed(self, icon_view):
        selected_paths = icon_view.get_selected_items()
        if selected_paths:
            self.live_preview_enabled = False
            tree_iter = self.store.get_iter(selected_paths[0])
            item = self.store.get_value(tree_iter, 2)
            self.preview_widget.load_item(item)

    def show_live_preview(self) -> None:
        self.live_preview_enabled = True
        self.icon_view.unselect_all()

    def update_live_frame(
        self,
        frame,
        measured_fps: float = 0.0,
        configured_fps: float = 0.0,
    ) -> None:
        if self.live_preview_enabled:
            self.preview_widget.show_live_frame(
                frame,
                measured_fps=measured_fps,
                configured_fps=configured_fps,
            )

    def update_prepared_live_frame(self, prepared) -> None:
        if self.live_preview_enabled:
            self.preview_widget.show_prepared_live_frame(prepared)

    def update_camera_message(self, message: str) -> None:
        if self.live_preview_enabled:
            self.preview_widget.show_camera_message(message)
