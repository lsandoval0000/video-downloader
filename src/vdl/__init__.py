"""VideoDownloader — a light, portable Windows desktop video downloader.

Wraps ``yt-dlp`` + ``ffmpeg`` and embeds a real ``libmpv`` player, shipped as a
self-contained PyInstaller *onedir* folder. See ``.aiw/plan.md`` for the design.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
