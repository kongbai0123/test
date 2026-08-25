"""
src/media package initialization
"""
from typing import NamedTuple, Optional


class MediaItem(NamedTuple):
    filepath: str
    filename: str
    media_type: str  # 'image' or 'video'
    filesize: int
    timestamp: float
    thumbnail_path: Optional[str]
