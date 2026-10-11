"""Pure builder for yt-dlp options — the SINGLE place opts are assembled.

Everything yt-dlp is configured with flows through :func:`build_ydl_opts`; no
other module may assemble an opts dict (plan anti-pattern). The builder is a
composition of small, pure helpers so leaves 2.2-4.2 extend behaviour by calling
into here rather than duplicating dicts.

Design constraints:

* **No Qt, no network, no download I/O** — importable and testable headless.
* The only filesystem side effect is :func:`vdl.core.history.archive_path`, which
  resolves (and lazily creates) the user-data directory; unit tests monkeypatch
  it. (It moved to ``core/history.py`` in leaf 4.2 and is re-exported by name.)
* **Postprocessor order is semantic** and must not be reshuffled::

      SponsorBlock → (FFmpegExtractAudio | FFmpegVideoConvertor/Remuxer)
      → FFmpegEmbedSubtitle → ModifyChapters → EmbedThumbnail → FFmpegMetadata

  (``ModifyChapters`` performs the actual SponsorBlock cuts and is placed after
  subtitle embedding / before metadata, mirroring yt-dlp's own CLI ordering.)

* The ``FFmpegVideoConvertor`` key ``preferedformat`` (single ``r``) is the real
  upstream spelling — do **not** "fix" it.

Verified corrections against installed yt-dlp 2026.08.19 (see worklog / plan
rulings):

* **Subtitles**: the option key is ``writesubtitles`` (no underscore) — the
  plan's ``write_subtitles`` is ignored by yt-dlp, which silently yields *no*
  subtitles and makes ``FFmpegEmbedSubtitle`` no-op. Use the correct key.
* **SponsorBlock** (R-003): ``SponsorBlockPP`` takes ``categories`` (+ ``when``)
  and removal is the *separate* ``ModifyChapters`` PP. Do **not** reintroduce
  ``remove_sponsor_segments`` on ``SponsorBlock``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from vdl.core import cookies
from vdl.core.formats import FORMAT_PRESETS
from vdl.core.history import archive_path  # re-exported; injected as download_archive
from vdl.paths import deno_exe, ffmpeg_exe

if TYPE_CHECKING:
    from vdl.config import Settings
    from vdl.core.queue import Job

#: Output template: title (bounded to 200 bytes so long titles stay valid on
#: Windows), the video id (guarantees uniqueness), then the extension.
DEFAULT_OUTTMPL = "%(title).200B [%(id)s].%(ext)s"

# ── capability sets (mirror the installed yt-dlp postprocessors) ─────────────

#: Containers ``FFmpegEmbedSubtitlePP`` can mux a subtitle stream into.
EMBEDDABLE_SUB_CONTAINERS: frozenset[str] = frozenset({"mp4", "mov", "m4a", "webm", "mkv", "mka"})

#: Video targets ``FFmpegVideoConvertorPP`` / ``FFmpegVideoRemuxerPP`` support.
CONVERTIBLE_VIDEO_EXTS: frozenset[str] = frozenset({"avi", "flv", "mkv", "mov", "mp4", "webm"})

#: Audio targets ``FFmpegExtractAudioPP`` supports.
CONVERTIBLE_AUDIO_EXTS: frozenset[str] = frozenset(
    {"aac", "aiff", "alac", "flac", "m4a", "mka", "mp3", "ogg", "opus", "vorbis", "wav"}
)

#: Containers ``EmbedThumbnailPP`` can attach a cover image to.
THUMBNAIL_CONTAINERS: frozenset[str] = frozenset(
    {"mp3", "mkv", "mka", "ogg", "opus", "flac", "m4a", "mp4", "m4v", "mov"}
)

# ── SponsorBlock vocabulary (extra #10) ──────────────────────────────────────

#: ``--sponsorblock-remove default`` semantics (yt-dlp docs): all but filler.
SPONSORBLOCK_DEFAULT_REMOVE: tuple[str, ...] = ("all", "-filler")

#: Categories SponsorBlock never removes (POI markers / chapters).
SPONSORBLOCK_NON_SKIPPABLE: frozenset[str] = frozenset({"poi_highlight", "chapter"})

#: Named removal presets the UI can offer (extra #10).
SPONSORBLOCK_PRESETS: dict[str, tuple[str, ...]] = {
    "default": SPONSORBLOCK_DEFAULT_REMOVE,
    "sponsor": ("sponsor",),
    "selfpromo": ("selfpromo",),
    "interaction": ("interaction",),
    "intro": ("intro",),
    "outro": ("outro",),
    "preview": ("preview",),
    "music_offtopic": ("music_offtopic",),
    "filler": ("filler",),
}


class ConversionError(ValueError):
    """Raised when a requested container/codec combination is not convertible."""


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


# ── subtitles (extra #8) ─────────────────────────────────────────────────────


def _subtitle_opts(settings: Settings) -> dict[str, Any]:
    """Write and/or embed subtitles (extra #8).

    ``writesubtitles`` (no underscore) is the real yt-dlp key — see the module
    docstring; the plan's ``write_subtitles`` spelling is ignored by yt-dlp.
    """
    if not (settings.write_subs or settings.embed_subs):
        return {}
    return {
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": list(settings.sub_langs),
        "subtitlesformat": "srt/best",
    }


def available_subtitle_langs(info: Mapping[str, Any] | None) -> set[str]:
    """Union of subtitle + automatic-caption language codes advertised by ``info``."""
    if not info:
        return set()
    langs: set[str] = set()
    for key in ("subtitles", "automatic_captions"):
        section = info.get(key)
        if isinstance(section, Mapping):
            langs.update(str(lang) for lang in section)
    return langs


def subtitle_langs_present(
    info: Mapping[str, Any] | None,
    langs: Iterable[str] | None,
) -> list[str]:
    """Return which requested languages match available subtitles.

    Mirrors yt-dlp's ``orderedSet_from_options(..., use_regex=True)`` matching
    (case-insensitive ``re.fullmatch``), and expands the ``all`` alias. Ordered
    by language code for deterministic output.
    """
    available = available_subtitle_langs(info)
    if not available:
        return []
    requested = [str(lang) for lang in (langs or [])]
    if "all" in requested:
        return sorted(available)

    matched: list[str] = []
    for pattern in requested:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = None
        for lang in sorted(available):
            if lang in matched:
                continue
            if regex is not None and regex.fullmatch(lang):
                matched.append(lang)
    return matched


def embed_subtitles_supported(container: str | None) -> bool:
    """``True`` if ``FFmpegEmbedSubtitle`` can mux into ``container``."""
    if not container:
        return False
    return container.lower() in EMBEDDABLE_SUB_CONTAINERS


def _target_container(settings: Settings) -> str | None:
    """Best-known post-processing container (``None`` when decided by the source)."""
    if settings.audio_only:
        return settings.audio_codec
    return settings.video_container


def subtitle_warning(
    info: Mapping[str, Any] | None,
    settings: Settings,
) -> str | None:
    """Return an actionable message when requested subtitles will be absent.

    ``FFmpegEmbedSubtitle`` silently no-ops when ``info['requested_subtitles']``
    is empty (and so does writing when nothing matches). Call this after
    ``extract_info`` to tell the UI *why* — "no subtitles available", a language
    mismatch, or an unsupported container — instead of leaving the user with a
    file that has no subtitle stream.

    Returns ``None`` when subtitles are disabled or everything looks fine.
    """
    if not (settings.write_subs or settings.embed_subs):
        return None
    if info is None:
        return None

    available = available_subtitle_langs(info)
    if not available:
        return "No subtitles or automatic captions are available for this video."

    if settings.write_subs and not subtitle_langs_present(info, settings.sub_langs):
        langs = ", ".join(settings.sub_langs) or "(none)"
        return f"None of the requested subtitle languages ({langs}) are available for this video."

    if settings.embed_subs:
        container = _target_container(settings)
        if container and not embed_subtitles_supported(container):
            return f"Subtitles cannot be embedded in .{container} files."

    return None


# ── playlist (extra #3) ──────────────────────────────────────────────────────


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


# ── network / cookies (extra #11) ────────────────────────────────────────────


def _network_opts(settings: Settings) -> dict[str, Any]:
    """Proxy (#15) and cookie sources (extra #11).

    Injects yt-dlp's ``cookiefile`` (a ``cookies.txt`` path) and/or
    ``cookiesfrombrowser`` (a tuple). Both may be present — yt-dlp merges them.
    """
    opts: dict[str, Any] = {}
    if settings.proxy:
        opts["proxy"] = settings.proxy
    if settings.use_cookies:
        cookie_file = cookies.cookie_file_option(getattr(settings, "cookie_file", None))
        if cookie_file:
            opts["cookiefile"] = cookie_file
        if settings.cookie_browser:
            spec = cookies.cookies_option(settings.cookie_browser)
            if spec:
                opts["cookiesfrombrowser"] = spec
    return opts


# ── archive / history (extra #14, engine) ────────────────────────────────────


def _archive_opts(settings: Settings) -> dict[str, Any]:
    """Download archive to skip already-downloaded videos (extra #14, engine).

    Uses :func:`vdl.core.history.archive_path` (imported above); tests monkeypatch
    the module-level name to stay off the real user-data dir.
    """
    if settings.archive_enabled:
        return {"download_archive": archive_path()}
    return {}


def _js_opts(settings: Settings) -> dict[str, Any]:
    """Bundled ``deno`` runtime for YouTube JS challenges."""
    if settings.js_runtime_enabled:
        return {"js_runtimes": {"deno": {"path": deno_exe()}}}
    return {}


# ── conversion (extra #12) ───────────────────────────────────────────────────


def validate_conversion(settings: Settings) -> None:
    """Reject incompatible container/codec combinations *before* a download.

    Called by :func:`build_ydl_opts` so an invalid choice surfaces immediately
    (the worker turns the :class:`ConversionError` into an ``error`` signal)
    rather than failing deep inside ffmpeg after a long download.
    """
    if settings.audio_only:
        if settings.video_container:
            raise ConversionError(
                "audio-only download cannot also target a video container "
                f"({settings.video_container!r})"
            )
        if settings.audio_codec.lower() not in CONVERTIBLE_AUDIO_EXTS:
            raise ConversionError(f"unsupported audio codec: {settings.audio_codec!r}")
        return
    if settings.video_container and settings.video_container.lower() not in CONVERTIBLE_VIDEO_EXTS:
        raise ConversionError(f"unsupported video container: {settings.video_container!r}")


def conversion_postprocessor(settings: Settings) -> dict[str, Any] | None:
    """The single conversion postprocessor for ``settings`` (audio or video).

    * audio-only -> ``FFmpegExtractAudio`` (extra #2);
    * video target -> ``FFmpegVideoRemuxer`` (stream-copy, fast) when
      ``settings.video_remux`` is set, else ``FFmpegVideoConvertor`` (re-encode).
    """
    if settings.audio_only:
        return {
            "key": "FFmpegExtractAudio",
            "preferredcodec": settings.audio_codec,
            "preferredquality": "0",
        }
    if settings.video_container:
        key = (
            "FFmpegVideoRemuxer"
            if getattr(settings, "video_remux", False)
            else "FFmpegVideoConvertor"
        )
        # NOTE: upstream spelling (single 'r') — do NOT "fix" it.
        return {"key": key, "preferedformat": settings.video_container}
    return None


# ── thumbnails (extra #9) ────────────────────────────────────────────────────


def thumbnail_convertor_pp(target_format: str = "jpg") -> dict[str, Any]:
    """A ``FFmpegThumbnailsConvertor`` postprocessor (runs at the ``before_dl`` stage).

    ``EmbedThumbnailPP`` already converts unsupported cover formats (e.g. webp)
    internally, so this is only needed to *force* a format up front — e.g. jpg
    for mp4-family containers where muxing a webp cover can be fragile.
    """
    return {"key": "FFmpegThumbnailsConvertor", "format": target_format, "when": "before_dl"}


def embed_thumbnail_supported(container: str | None) -> bool:
    """``True`` if ``EmbedThumbnail`` can attach a cover to ``container``."""
    if not container:
        return False
    return container.lower() in THUMBNAIL_CONTAINERS


# ── SponsorBlock (extra #10) ─────────────────────────────────────────────────


def sponsorblock_categories_for(preset: str | Iterable[str] | None) -> list[str]:
    """Resolve a preset name / alias (or a raw list) to a category list.

    ``'default'`` expands to ``['all', '-filler']`` (yt-dlp's documented
    ``--sponsorblock-remove`` default); a bare category or list passes through.
    """
    if preset is None:
        return []
    if isinstance(preset, str):
        return list(SPONSORBLOCK_PRESETS.get(preset, (preset,)))
    return [str(item) for item in preset]


def removable_sponsorblock_categories(categories: Iterable[str]) -> list[str]:
    """Drop non-removable categories (``poi_highlight``/``chapter``).

    Mirrors yt-dlp, which subtracts ``NON_SKIPPABLE_CATEGORIES`` before cutting.
    ``all`` / ``-filler`` style entries are preserved verbatim.
    """
    removable: list[str] = []
    for category in categories:
        name = category[1:] if category.startswith("-") else category
        if name in SPONSORBLOCK_NON_SKIPPABLE:
            continue
        removable.append(category)
    return removable


# ── postprocessor assembly (order is semantic) ───────────────────────────────


def _postprocessor_opts(settings: Settings) -> dict[str, Any]:
    """Assemble the ORDER-SENSITIVE postprocessor chain (+ ``writethumbnail``).

    See the module docstring for the required order. Returns a fragment that may
    contain ``postprocessors`` and/or ``writethumbnail``.
    """
    postprocessors: list[dict[str, Any]] = []

    # 1) SponsorBlock fetches the segment list FIRST (scheduled at the
    #    "after_filter" stage). VERIFIED (yt-dlp 2026.08.19): the PP parameter is
    #    ``categories``; removal is the separate ModifyChapters PP below.
    remove_categories: list[str] = []
    if settings.sponsorblock_enabled:
        remove_categories = removable_sponsorblock_categories(settings.sponsorblock_categories)
        if remove_categories:
            postprocessors.append(
                {
                    "key": "SponsorBlock",
                    "categories": list(remove_categories),
                    "when": "after_filter",
                }
            )

    # 2) Audio extraction (extra #2) OR video conversion (extra #12).
    conversion = conversion_postprocessor(settings)
    if conversion is not None:
        postprocessors.append(conversion)

    # 3) Subtitle muxing AFTER the container is final (extra #8).
    if settings.embed_subs:
        postprocessors.append({"key": "FFmpegEmbedSubtitle"})

    # 3b) SponsorBlock segment REMOVAL. yt-dlp requires this after subtitle
    #     embedding and before metadata/thumbnail muxing.
    if remove_categories:
        postprocessors.append(
            {"key": "ModifyChapters", "remove_sponsor_segments": list(remove_categories)}
        )

    # 4) Thumbnail embedding (extra #9) — requires writethumbnail.
    fragment: dict[str, Any] = {}
    if settings.embed_thumbnail:
        fragment["writethumbnail"] = True
        if getattr(settings, "convert_thumbnail", False):
            postprocessors.append(thumbnail_convertor_pp("jpg"))
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
    ``noplaylist``, ``extract_flat``). Raises :class:`ConversionError` for an
    incompatible container/codec choice (checked before the download starts).
    """
    validate_conversion(settings)
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
