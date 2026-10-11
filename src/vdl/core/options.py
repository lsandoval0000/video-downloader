"""Pure builder for yt-dlp options — the SINGLE place opts are assembled.

Everything yt-dlp is configured with flows through :func:`build_ydl_opts`; no
other module may assemble an opts dict (plan anti-pattern). The builder is a
composition of small, pure helpers so leaves 2.2-4.2 extend behaviour by calling
into here rather than duplicating dicts.

Design constraints:

* **No Qt, no network, no download I/O** — importable and testable headless.
* The only filesystem side effect is :func:`archive_path`, which resolves (and
  lazily creates) the user-data directory; unit tests monkeypatch it.
* **Postprocessor order is semantic** and must not be reshuffled::

      SponsorBlock → (FFmpegExtractAudio | FFmpegVideoConvertor)
      → FFmpegEmbedSubtitle → ModifyChapters → EmbedThumbnail → FFmpegMetadata

  (``ModifyChapters`` performs the actual SponsorBlock cuts and is placed after
  subtitle embedding / before metadata, mirroring yt-dlp's own CLI ordering.)

* The ``FFmpegVideoConvertor`` key ``preferedformat`` (single ``r``) is the real
  upstream spelling — do **not** "fix" it.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from vdl.core.formats import FORMAT_PRESETS
from vdl.paths import deno_exe, ffmpeg_exe, user_data_dir

if TYPE_CHECKING:
    from vdl.config import Settings
    from vdl.core.queue import Job

#: Output template: title (bounded to 200 bytes so long titles stay valid on
#: Windows), the video id (guarantees uniqueness), then the extension.
DEFAULT_OUTTMPL = "%(title).200B [%(id)s].%(ext)s"

_ARCHIVE_FILENAME = "archive.txt"


def archive_path() -> str:
    """Absolute path to yt-dlp's plain-text download archive.

    Temporary home until leaf 4.2 (``core/history.py``) takes ownership; kept
    here because it is injected into the opts and must have one definition.
    """
    return str(user_data_dir() / _ARCHIVE_FILENAME)


# ── pure helpers (one concern each) ──────────────────────────────────────────


def _base_opts() -> dict[str, Any]:
    """Stable, settings-independent plumbing (quiet, retries, hook slots)."""
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ffmpeg_location": os.path.dirname(ffmpeg_exe()),  # GOTCHA: a DIR, not the exe
        "progress_hooks": [],  # engine injects its callbacks
        "postprocessor_hooks": [],
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "ignoreerrors": False,
        "nocheckcertificate": False,
    }


def _paths_opts(settings: Settings) -> dict[str, Any]:
    """Output template + the home path (extra #15 default dir)."""
    download_dir = settings.download_dir or ""
    return {
        "outtmpl": os.path.join(download_dir, DEFAULT_OUTTMPL),
        "paths": {"home": download_dir},
    }


def _format_opts(settings: Settings, job: Job | None) -> dict[str, Any]:
    """Format selection: audio-only (#2), explicit id, else named preset (#1)."""
    if settings.audio_only:
        return {"format": FORMAT_PRESETS["audio"]}
    if job is not None and job.format_selector:
        return {"format": job.format_selector}
    return {"format": FORMAT_PRESETS.get(settings.default_format_preset, FORMAT_PRESETS["best"])}


def _subtitle_opts(settings: Settings) -> dict[str, Any]:
    """Write and/or embed subtitles (extra #8)."""
    if not (settings.write_subs or settings.embed_subs):
        return {}
    return {
        "write_subtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": list(settings.sub_langs),
        "subtitlesformat": "srt/best",
    }


def _playlist_opts(settings: Settings, job: Job | None) -> dict[str, Any]:
    """Playlist / channel download controls (extra #3)."""
    opts: dict[str, Any] = {}
    if settings.playlist_items:
        opts["playlist_items"] = settings.playlist_items
    if job is not None and job.noplaylist:
        opts["noplaylist"] = True
    if job is not None and job.extract_flat:
        opts["extract_flat"] = True
    return opts


def _network_opts(settings: Settings) -> dict[str, Any]:
    """Proxy (#15) and browser cookie import (extra #11)."""
    opts: dict[str, Any] = {}
    if settings.proxy:
        opts["proxy"] = settings.proxy
    if settings.use_cookies and settings.cookie_browser:
        # yt-dlp expects a tuple, e.g. ('chrome',) -> ('chrome', None, None, None)
        opts["cookiesfrombrowser"] = (settings.cookie_browser,)
    return opts


def _archive_opts(settings: Settings) -> dict[str, Any]:
    """Download archive to skip already-downloaded videos (extra #14, engine)."""
    if settings.archive_enabled:
        return {"download_archive": archive_path()}
    return {}


def _js_opts(settings: Settings) -> dict[str, Any]:
    """Bundled ``deno`` runtime for YouTube JS challenges."""
    if settings.js_runtime_enabled:
        return {"js_runtimes": {"deno": {"path": deno_exe()}}}
    return {}


def _postprocessor_opts(settings: Settings) -> dict[str, Any]:
    """Assemble the ORDER-SENSITIVE postprocessor chain (+ writethumbnail).

    See the module docstring for the required order. Returns a fragment that may
    contain ``postprocessors`` and/or ``writethumbnail``.
    """
    postprocessors: list[dict[str, Any]] = []

    # 1) SponsorBlock fetches the segment list FIRST (it is scheduled at the
    #    "after_filter" stage). VERIFIED CORRECTION (yt-dlp 2026.08.19): the real
    #    PP parameter is ``categories`` and it needs ``when='after_filter'`` — the
    #    plan's pseudocode key ``remove_sponsor_segments`` belongs to the
    #    *separate* ``ModifyChapters`` PP below and would crash ``YoutubeDL``.
    if settings.sponsorblock_enabled:
        postprocessors.append(
            {
                "key": "SponsorBlock",
                "categories": list(settings.sponsorblock_categories),
                "when": "after_filter",
            }
        )

    # 2) Audio extraction (extra #2) OR video conversion (extra #12).
    if settings.audio_only:
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": settings.audio_codec,
                "preferredquality": "0",
            }
        )
    elif settings.video_container:
        postprocessors.append(
            {
                "key": "FFmpegVideoConvertor",
                # NOTE: upstream spelling (single 'r') — do NOT "fix" it.
                "preferedformat": settings.video_container,
            }
        )

    # 3) Subtitle muxing AFTER the container is final (extra #8).
    if settings.embed_subs:
        postprocessors.append({"key": "FFmpegEmbedSubtitle"})

    # 3b) SponsorBlock segment REMOVAL. yt-dlp requires this after subtitle
    #     embedding and before metadata/thumbnail muxing (see the CLI glue:
    #     "ModifyChapters must run before FFmpegMetadataPP").
    if settings.sponsorblock_enabled:
        postprocessors.append(
            {
                "key": "ModifyChapters",
                "remove_sponsor_segments": list(settings.sponsorblock_categories),
            }
        )

    # 4) Thumbnail embedding (extra #9) — requires writethumbnail.
    fragment: dict[str, Any] = {}
    if settings.embed_thumbnail:
        fragment["writethumbnail"] = True
        postprocessors.append({"key": "EmbedThumbnail"})

    # 5) Metadata LAST so tags survive any earlier re-encode (extra #9).
    if settings.embed_metadata:
        postprocessors.append({"key": "FFmpegMetadata"})

    if postprocessors:
        fragment["postprocessors"] = postprocessors
    return fragment


def build_ydl_opts(settings: Settings, job: Job | None = None) -> dict[str, Any]:
    """Return a fully-formed yt-dlp options dict for one job.

    Pure: same inputs always produce the same dict. ``job`` may be ``None`` for
    a settings-only build, or carry per-job overrides (``format_selector``,
    ``noplaylist``, ``extract_flat``).
    """
    opts: dict[str, Any] = {}
    opts.update(_base_opts())
    opts.update(_paths_opts(settings))
    opts.update(_format_opts(settings, job))
    opts.update(_subtitle_opts(settings))
    opts.update(_playlist_opts(settings, job))
    opts.update(_network_opts(settings))
    opts.update(_archive_opts(settings))
    opts.update(_js_opts(settings))
    # Applied last so the semantic postprocessor order is never clobbered.
    opts.update(_postprocessor_opts(settings))
    return opts
