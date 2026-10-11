"""Format enumeration and quality-preset selectors (extra #1).

Qt-free and import-light: :mod:`yt_dlp` is imported lazily inside
:func:`list_formats` so importing this module (and, transitively,
:mod:`vdl.core.options`) never drags in the full download stack. The pure
selector/parsing helpers are unit-tested against fake info dicts with no
network access.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: Named quality presets -> yt-dlp format selector string.
#:
#: ``bv*+ba/b`` is "best video + best audio, fall back to a single best".
#: ``wv*+wa/w`` is the "worst" analogue used by the *smallest* preset.
FORMAT_PRESETS: dict[str, str] = {
    "best": "bv*+ba/b",
    "1080p": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
    "720p": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
    "audio": "bestaudio/best",
    "smallest": "wv*+wa/w",
}


@dataclass(frozen=True)
class FormatInfo:
    """A single downloadable format, flattened for display in a table."""

    id: str
    ext: str | None = None
    resolution: str | None = None
    fps: float | None = None
    vcodec: str | None = None
    acodec: str | None = None
    filesize: int | None = None
    note: str | None = None

    @classmethod
    def from_ytdlp(cls, fmt: Mapping[str, Any]) -> FormatInfo:
        """Build a :class:`FormatInfo` from a yt-dlp format dict."""
        return cls(
            id=str(fmt.get("format_id") or fmt.get("id") or ""),
            ext=fmt.get("ext"),
            resolution=fmt.get("resolution") or _resolution(fmt),
            fps=fmt.get("fps"),
            vcodec=fmt.get("vcodec"),
            acodec=fmt.get("acodec"),
            filesize=fmt.get("filesize") or fmt.get("filesize_approx"),
            note=fmt.get("format_note") or fmt.get("format") or None,
        )


def _resolution(fmt: Mapping[str, Any]) -> str | None:
    """Fall back to ``WIDTHxHEIGHT`` when yt-dlp omits ``resolution``."""
    width, height = fmt.get("width"), fmt.get("height")
    if width and height:
        return f"{width}x{height}"
    if height:
        return f"{height}p"
    return None


def _has_stream(value: Any) -> bool:
    return bool(value) and value != "none"


def _find_format(info: Mapping[str, Any] | None, format_id: str) -> Mapping[str, Any] | None:
    if not info:
        return None
    for fmt in info.get("formats") or []:
        if isinstance(fmt, Mapping) and str(fmt.get("format_id")) == format_id:
            return fmt
    return None


def format_selector(preset: str, info: Mapping[str, Any] | None = None) -> str:
    """Return a yt-dlp ``format`` string for a named preset or an explicit id.

    * A known preset name (see :data:`FORMAT_PRESETS`) returns its selector.
    * Anything else is treated as a concrete ``format_id`` chosen from the
      formats table: video-only ids get ``+bestaudio/best`` appended, muxed ids
      are used alone, audio-only ids fall back to ``bestaudio/best``.

    ``info`` is the yt-dlp info dict (optional) used to inspect the chosen id.
    """
    if preset in FORMAT_PRESETS:
        return FORMAT_PRESETS[preset]

    fmt_id = str(preset)
    fmt = _find_format(info, fmt_id)
    if fmt is not None:
        has_video = _has_stream(fmt.get("vcodec"))
        has_audio = _has_stream(fmt.get("acodec"))
        if has_video and has_audio:
            return f"{fmt_id}/best"
        if has_video:
            return f"{fmt_id}+bestaudio/best"
        if has_audio:
            return f"{fmt_id}/bestaudio/best"
    return f"{fmt_id}+bestaudio/best"


def list_formats(url: str, *, ydl: Any = None) -> list[FormatInfo]:
    """Enumerate the downloadable formats for ``url`` without downloading.

    Pass an existing ``ydl`` (e.g. one carrying cookies/proxy) to reuse its
    configuration; otherwise a quiet throw-away instance is created. For a
    playlist/channel URL the first entry with formats is used.
    """
    import yt_dlp

    owns_ydl = ydl is None
    if owns_ydl:
        ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True})
    try:
        info = ydl.extract_info(url, download=False)
    finally:
        if owns_ydl:
            ydl.close()
    return _formats_from_info(info)


def _formats_from_info(info: Mapping[str, Any] | None) -> list[FormatInfo]:
    """Flatten a yt-dlp info dict (or the first playlist entry) into formats."""
    if not info:
        return []
    if info.get("_type") in ("playlist", "multi_video") or "entries" in info:
        for entry in info.get("entries") or []:
            if entry:
                return _formats_from_info(entry)
        return []
    return [FormatInfo.from_ytdlp(fmt) for fmt in info.get("formats") or []]
