"""Unit tests for :mod:`vdl.core.options` — pure, no network, **no PySide6**.

Each test drives :func:`build_ydl_opts` with a settings permutation and asserts
the exact keys/values yt-dlp will receive (plan leaf 8.2: >= 8 permutations).
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from vdl.config import Settings
from vdl.core import options
from vdl.paths import deno_exe, ffmpeg_exe


@pytest.fixture(autouse=True)
def _isolate_archive(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Keep ``archive_path`` off the real user-data dir (hermetic tests)."""
    monkeypatch.setattr(options, "archive_path", lambda: str(tmp_path / "archive.txt"))


def make(**overrides: object) -> Settings:
    """A minimal, quiet Settings with all optional features off by default."""
    base: dict[str, object] = {
        "download_dir": r"C:\dl",
        "audio_only": False,
        "write_subs": False,
        "embed_subs": False,
        "embed_thumbnail": False,
        "embed_metadata": False,
        "sponsorblock_enabled": False,
        "archive_enabled": False,
        "js_runtime_enabled": False,
        "use_cookies": False,
        "cookie_browser": None,
        "video_container": None,
        "playlist_items": None,
        "proxy": None,
    }
    base.update(overrides)
    return Settings(**base)


# ── permutation 1: default / base ────────────────────────────────────────────
def test_base_keys_and_values() -> None:
    opts = options.build_ydl_opts(make())
    assert opts["quiet"] is True
    assert opts["no_warnings"] is True
    assert opts["noprogress"] is True
    assert opts["ffmpeg_location"] == os.path.dirname(ffmpeg_exe())
    assert opts["outtmpl"] == os.path.join(r"C:\dl", options.DEFAULT_OUTTMPL)
    assert opts["paths"] == {"home": r"C:\dl"}
    assert opts["progress_hooks"] == []
    assert opts["postprocessor_hooks"] == []
    assert opts["retries"] == 10
    assert opts["fragment_retries"] == 10
    assert opts["format"] == "bv*+ba/b"
    assert "postprocessors" not in opts
    assert "writethumbnail" not in opts


def test_default_settings_full_build() -> None:
    """Out-of-the-box Settings (subs + thumb + metadata + archive + js on)."""
    opts = options.build_ydl_opts(Settings(download_dir=r"C:\dl"))
    assert opts["format"] == "bv*+ba/b"
    assert opts["write_subtitles"] is True
    assert opts["writethumbnail"] is True
    assert [pp["key"] for pp in opts["postprocessors"]] == ["EmbedThumbnail", "FFmpegMetadata"]
    assert "download_archive" in opts
    assert "js_runtimes" in opts


# ── permutation 2/3: audio-only extraction (extra #2) ────────────────────────
def test_audio_only_mp3() -> None:
    opts = options.build_ydl_opts(make(audio_only=True, audio_codec="mp3"))
    assert opts["format"] == "bestaudio/best"
    assert opts["postprocessors"] == [
        {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}
    ]


def test_audio_only_m4a() -> None:
    opts = options.build_ydl_opts(make(audio_only=True, audio_codec="m4a"))
    assert opts["postprocessors"] == [
        {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "0"}
    ]


# ── permutation 4: subtitles write + embed (extra #8) ────────────────────────
def test_subtitles_write_and_embed() -> None:
    opts = options.build_ydl_opts(make(write_subs=True, embed_subs=True, sub_langs=["en", "es"]))
    assert opts["write_subtitles"] is True
    assert opts["writeautomaticsub"] is True
    assert opts["subtitleslangs"] == ["en", "es"]
    assert opts["subtitlesformat"] == "srt/best"
    assert {"key": "FFmpegEmbedSubtitle"} in opts["postprocessors"]


def test_subtitles_absent_when_disabled() -> None:
    opts = options.build_ydl_opts(make(write_subs=False, embed_subs=False))
    assert "write_subtitles" not in opts
    assert "subtitleslangs" not in opts


# ── permutation 5: sponsorblock (extra #10) ──────────────────────────────────
def test_sponsorblock_is_first_and_uses_correct_keys() -> None:
    opts = options.build_ydl_opts(
        make(sponsorblock_enabled=True, sponsorblock_categories=["sponsor", "selfpromo"])
    )
    # VERIFIED (yt-dlp 2026.08.19): SponsorBlock takes `categories` (+ when),
    # and removal is done by a separate ModifyChapters PP.
    assert opts["postprocessors"][0] == {
        "key": "SponsorBlock",
        "categories": ["sponsor", "selfpromo"],
        "when": "after_filter",
    }
    assert {
        "key": "ModifyChapters",
        "remove_sponsor_segments": ["sponsor", "selfpromo"],
    } in opts["postprocessors"]


# ── permutation 6: video conversion + upstream typo (extra #12) ──────────────
def test_video_conversion_uses_upstream_typo() -> None:
    opts = options.build_ydl_opts(make(video_container="mkv"))
    assert opts["postprocessors"] == [{"key": "FFmpegVideoConvertor", "preferedformat": "mkv"}]
    assert "preferedformat" in opts["postprocessors"][0]
    assert "preferredformat" not in opts["postprocessors"][0]


# ── permutation 7: cookies (extra #11) ───────────────────────────────────────
def test_cookies_from_browser() -> None:
    opts = options.build_ydl_opts(make(use_cookies=True, cookie_browser="chrome"))
    assert opts["cookiesfrombrowser"] == ("chrome",)


def test_cookies_absent_when_disabled() -> None:
    assert "cookiesfrombrowser" not in options.build_ydl_opts(make(use_cookies=False))


# ── permutation 8: archive (extra #14 engine) ────────────────────────────────
def test_archive_enabled_injects_path(tmp_path) -> None:
    opts = options.build_ydl_opts(make(archive_enabled=True))
    assert opts["download_archive"] == str(tmp_path / "archive.txt")


def test_archive_disabled_absent() -> None:
    assert "download_archive" not in options.build_ydl_opts(make(archive_enabled=False))


# ── permutation 9: playlist range + per-job overrides (extra #3) ─────────────
def test_playlist_range() -> None:
    opts = options.build_ydl_opts(make(playlist_items="1-10"))
    assert opts["playlist_items"] == "1-10"


def test_playlist_job_overrides() -> None:
    job = SimpleNamespace(format_selector=None, noplaylist=True, extract_flat=True)
    opts = options.build_ydl_opts(make(), job)
    assert opts["noplaylist"] is True
    assert opts["extract_flat"] is True


# ── additional: JS runtime, proxy, format override ───────────────────────────
def test_js_runtime_deno_path() -> None:
    opts = options.build_ydl_opts(make(js_runtime_enabled=True))
    assert opts["js_runtimes"] == {"deno": {"path": deno_exe()}}


def test_proxy_injected() -> None:
    opts = options.build_ydl_opts(make(proxy="http://127.0.0.1:8080"))
    assert opts["proxy"] == "http://127.0.0.1:8080"


def test_job_format_selector_override() -> None:
    job = SimpleNamespace(
        format_selector="137+bestaudio/best", noplaylist=False, extract_flat=False
    )
    opts = options.build_ydl_opts(make(), job)
    assert opts["format"] == "137+bestaudio/best"


def test_postprocessor_order_is_semantic() -> None:
    opts = options.build_ydl_opts(
        make(
            sponsorblock_enabled=True,
            audio_only=True,
            embed_subs=True,
            embed_thumbnail=True,
            embed_metadata=True,
        )
    )
    assert [pp["key"] for pp in opts["postprocessors"]] == [
        "SponsorBlock",
        "FFmpegExtractAudio",
        "FFmpegEmbedSubtitle",
        "ModifyChapters",
        "EmbedThumbnail",
        "FFmpegMetadata",
    ]
    assert opts["writethumbnail"] is True
