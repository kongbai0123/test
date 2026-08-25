"""
src/media/manager.py
Captures directory scanner and metadata indexer.
"""

import logging
import os
from typing import List

from src.media import MediaItem

logger = logging.getLogger("Media.Manager")


class MediaManager:
    """
    Scans media capture directory and indexes screenshots and video recordings.
    """

    IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
    VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".avi"}

    def scan_captures(self, output_dir: str) -> List[MediaItem]:
        """
        Scan directory for screenshot images and video files.
        Returns list of MediaItem tuples sorted by newest first.
        """
        items: List[MediaItem] = []
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                logger.error("Failed to create output directory %s: %s", output_dir, e)
                return items

        try:
            entries = os.scandir(output_dir)
            for entry in entries:
                if not entry.is_file():
                    continue
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in self.IMAGE_EXTS:
                    mtype = "image"
                elif ext in self.VIDEO_EXTS:
                    mtype = "video"
                else:
                    continue

                try:
                    stat = entry.stat()
                    item = MediaItem(
                        filepath=entry.path,
                        filename=entry.name,
                        media_type=mtype,
                        filesize=stat.st_size,
                        timestamp=stat.st_mtime,
                        thumbnail_path=None,
                    )
                    items.append(item)
                except Exception as e:
                    logger.warning("Error reading file stat for %s: %s", entry.path, e)
        except Exception as e:
            logger.error("Error scanning captures directory %s: %s", output_dir, e)

        # Sort newest first
        items.sort(key=lambda x: x.timestamp, reverse=True)
        return items
