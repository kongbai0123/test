"""
src/media/thumbnail.py
Asynchronous & cached thumbnail generator for images and videos.
"""

import logging
import os
import subprocess
from typing import Dict, Optional

from PIL import Image

from src.media import MediaItem

logger = logging.getLogger("Media.Thumbnail")


class ThumbnailGenerator:
    """
    Thumbnail generator and memory/disk cache for MediaItem preview icons.
    """

    def __init__(self, cache_dir: str = "/tmp/video_app_thumbs"):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self._memory_cache: Dict[str, str] = {}

    def get_thumbnail(self, item: MediaItem, size: int = 128) -> Optional[str]:
        """
        Get or generate thumbnail file path for a MediaItem.
        Returns filepath to thumbnail image or None if failed.
        """
        if item.filepath in self._memory_cache:
            cached = self._memory_cache[item.filepath]
            if os.path.exists(cached):
                return cached

        thumb_filename = f"thumb_{hash(item.filepath)}_{size}.png"
        thumb_path = os.path.join(self.cache_dir, thumb_filename)

        if os.path.exists(thumb_path):
            self._memory_cache[item.filepath] = thumb_path
            return thumb_path

        # Generate thumbnail
        try:
            if item.media_type == "image":
                with Image.open(item.filepath) as img:
                    img.thumbnail((size, size))
                    img.save(thumb_path, "PNG")
                self._memory_cache[item.filepath] = thumb_path
                return thumb_path
            elif item.media_type == "video":
                # Extract frame via ffmpeg
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    "00:00:01",
                    "-i",
                    item.filepath,
                    "-vframes",
                    "1",
                    "-vf",
                    f"scale={size}:-1",
                    thumb_path,
                ]
                res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                if res.returncode == 0 and os.path.exists(thumb_path):
                    self._memory_cache[item.filepath] = thumb_path
                    return thumb_path
                else:
                    # Fallback to 00:00:00
                    cmd[3] = "00:00:00"
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                    if os.path.exists(thumb_path):
                        self._memory_cache[item.filepath] = thumb_path
                        return thumb_path
        except Exception as e:
            logger.warning("Thumbnail generation failed for %s: %s", item.filepath, e)

        return None
