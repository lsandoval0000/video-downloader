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
        "js_runtime_enabled": False,
        "use_cookies": False,
        "cookie_browser": None,
        "cookie_file": None,
        "video_container": None,
        "video_remux": False,
        "convert_thumbnail": False,
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
    """Out-of-the-box Settings (subs + thumb + metadata + js on)."""
    opts = options.build_ydl_opts(Settings(download_dir=r"C:\dl"))
    assert opts["format"] == "bv*+ba/b"
    assert opts["writethumbnail"] is True
    assert [pp["key"] for pp in opts["postprocessors"]] == ["EmbedThumbnail", "FFmpegMetadata"]
    # Leaf 10.8: the download archive is NEVER injected — a URL always downloads.
    assert "download_archive" not in opts
    assert "js_runtimes" in opts
    # Subtitles are ISOLATED from the media pass (leaf 10.5): the media opts must
    # never carry subtitle-write/embed keys, or yt-dlp would fetch subtitles first
    # and a 429 could abort the job before the media was even merged.
    assert "writesubtitles" not in opts
    assert "FFmpegEmbedSubtitle" not in [pp["key"] for pp in opts["postprocessors"]]


# ── leaf 10.12: robust merge container (the "Conversion failed!" root cause) ──
def test_media_pass_pins_robust_merge_container() -> None:
    """The media pass must never let ``FFmpegMerger`` target webm (10.12).

    Merging YouTube's VP9 (HFR) video + Opus audio into webm aborts ffmpeg with
    ``non monotonically increasing dts`` → ``Conversion failed!`` (yt-dlp #3138 /
    Gentoo #846641); the documented fix is to merge into mkv. ``mp4`` stays first
    so the common h264+aac merge is unchanged.
    """
    opts = options.build_ydl_opts(make())
    assert opts["merge_output_format"] == "mp4/mkv"
    assert "webm" not in options.MERGE_OUTPUT_FORMAT
    # The isolated subtitle pass never merges, so it must not carry the key.
    assert "merge_output_format" not in options.build_subtitle_opts(make(write_subs=True))


def test_merge_container_present_for_every_media_permutation() -> None:
    """Every media-pass build pins the merge container, regardless of features."""
    for overrides in (
        {},
        {"audio_only": True, "audio_codec": "mp3"},
        {"video_container": "mp4"},
        {"sponsorblock_enabled": True, "sponsorblock_categories": ["sponsor"]},
        {"embed_thumbnail": True, "embed_metadata": True},
    ):
        opts = options.build_ydl_opts(make(**overrides))
        assert opts["merge_output_format"] == options.MERGE_OUTPUT_FORMAT, overrides


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


# ── permutation 4: subtitles write + embed (extra #8, isolated 10.5) ─────────
def test_media_pass_never_writes_or_embeds_subtitles() -> None:
    """The media pass must be subtitle-free so a subtitle 429 cannot abort it."""
    opts = options.build_ydl_opts(make(write_subs=True, embed_subs=True, sub_langs=["en", "es"]))
    for key in ("writesubtitles", "writeautomaticsub", "subtitleslangs", "subtitlesformat"):
        assert key not in opts
    assert "postprocessors" not in opts or "FFmpegEmbedSubtitle" not in [
        pp["key"] for pp in opts["postprocessors"]
    ]


def test_subtitle_pass_writes_with_user_semantics() -> None:
    """The isolated subtitle pass carries the user's language/format semantics."""
    opts = options.build_subtitle_opts(
        make(write_subs=True, embed_subs=True, sub_langs=["en", "es"])
    )
    # VERIFIED (yt-dlp 2026.08.19): the key is `writesubtitles` (no underscore).
    assert opts["writesubtitles"] is True
    assert opts["writeautomaticsub"] is True
    assert opts["subtitleslangs"] == ["en", "es"]
    assert opts["subtitlesformat"] == "srt/best"
    # skip_download stops the pass re-downloading (or touching) the media file.
    assert opts["skip_download"] is True


def test_subtitle_pass_omits_archive_and_flat() -> None:
    """The subtitle pass never carries an archive, so its entry is never skipped."""
    job = SimpleNamespace(format_selector=None, noplaylist=True, extract_flat=True)
    opts = options.build_subtitle_opts(make(write_subs=True), job)
    assert "download_archive" not in opts
    assert "extract_flat" not in opts
    assert opts["noplaylist"] is True


def test_subtitle_pass_empty_when_disabled() -> None:
    assert options.build_subtitle_opts(make(write_subs=False, embed_subs=False)) == {}


def test_subtitle_rate_limit_mitigation() -> None:
    """Subtitles set a modest inter-download pause to soften HTTP 429 bursts (10.5)."""
    opts = options.build_subtitle_opts(make(write_subs=True))
    assert opts["sleep_interval_subtitles"] == 1.0
    # Absent from the media pass, so the base opts stay minimal.
    assert "sleep_interval_subtitles" not in options.build_ydl_opts(make(write_subs=True))


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


# ── permutation 8: always download — archive NEVER injected (leaf 10.8) ──────
def test_build_opts_never_injects_download_archive() -> None:
    """Building opts must NEVER yield a ``download_archive`` (always re-download).

    yt-dlp would otherwise SKIP an already-archived id and produce no file. The
    app-level "previously downloaded" hint is cosmetic only — it never blocks.
    """
    assert "download_archive" not in options.build_ydl_opts(make())
    # Even the out-of-the-box defaults (which used to enable the archive) must not.
    assert "download_archive" not in options.build_ydl_opts(Settings(download_dir=r"C:\dl"))


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
        "ModifyChapters",
        "EmbedThumbnail",
        "FFmpegMetadata",
    ]
    assert opts["writethumbnail"] is True


# ══ branch 3 — media post-processing extensions ═══════════════════════════════


# ── 3.1 subtitles: availability helpers (extra #8) ───────────────────────────
_SAMPLE_INFO_WITH_SUBS = {
    "subtitles": {"en": [{"ext": "vtt"}], "en-US": [{"ext": "vtt"}]},
    "automatic_captions": {"es": [{"ext": "json3"}], "de": [{"ext": "json3"}]},
}


def test_subtitle_langs_present_exact_and_regex() -> None:
    info = _SAMPLE_INFO_WITH_SUBS
    assert options.subtitle_langs_present(info, ["en"]) == ["en"]
    assert options.subtitle_langs_present(info, ["en.*"]) == ["en", "en-US"]
    assert options.subtitle_langs_present(info, ["all"]) == ["de", "en", "en-US", "es"]
    assert options.subtitle_langs_present(info, ["fr"]) == []


def test_subtitle_warning_reports_no_subtitles() -> None:
    settings = make(write_subs=True, embed_subs=True)
    msg = options.subtitle_warning({"subtitles": {}, "automatic_captions": {}}, settings)
    assert msg is not None and "No subtitles" in msg


def test_subtitle_warning_reports_language_mismatch() -> None:
    settings = make(write_subs=True, sub_langs=["fr"])
    msg = options.subtitle_warning(_SAMPLE_INFO_WITH_SUBS, settings)
    assert msg is not None and "fr" in msg


def test_subtitle_warning_none_when_available() -> None:
    settings = make(write_subs=True, embed_subs=True, sub_langs=["en"])
    assert options.subtitle_warning(_SAMPLE_INFO_WITH_SUBS, settings) is None


def test_subtitle_warning_flags_unsupported_container() -> None:
    settings = make(write_subs=False, embed_subs=True, sub_langs=["en"], video_container="avi")
    msg = options.subtitle_warning(_SAMPLE_INFO_WITH_SUBS, settings)
    assert msg is not None and "avi" in msg


def test_subtitle_warning_absent_when_disabled() -> None:
    settings = make(write_subs=False, embed_subs=False)
    assert options.subtitle_warning({}, settings) is None


def test_embed_subtitles_supported_set() -> None:
    assert options.embed_subtitles_supported("mkv") is True
    assert options.embed_subtitles_supported("mp4") is True
    assert options.embed_subtitles_supported("avi") is False
    assert options.embed_subtitles_supported(None) is False


# ── 3.2 thumbnail + metadata (extra #9) ──────────────────────────────────────
def test_thumbnail_then_metadata_chain() -> None:
    opts = options.build_ydl_opts(make(embed_thumbnail=True, embed_metadata=True))
    assert opts["writethumbnail"] is True
    assert [pp["key"] for pp in opts["postprocessors"]] == ["EmbedThumbnail", "FFmpegMetadata"]


def test_thumbnail_conversion_inserted_before_embed() -> None:
    opts = options.build_ydl_opts(
        make(embed_thumbnail=True, embed_metadata=False, convert_thumbnail=True)
    )
    assert opts["postprocessors"] == [
        {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
        {"key": "EmbedThumbnail"},
    ]


def test_thumbnail_absent_when_disabled() -> None:
    opts = options.build_ydl_opts(make(embed_thumbnail=False, embed_metadata=False))
    assert "writethumbnail" not in opts
    assert "postprocessors" not in opts


def test_embed_thumbnail_supported_set() -> None:
    assert options.embed_thumbnail_supported("mp4") is True
    assert options.embed_thumbnail_supported("webm") is False


# ── 3.3 sponsorblock presets (extra #10) ─────────────────────────────────────
def test_sponsorblock_default_preset_expands() -> None:
    assert options.sponsorblock_categories_for("default") == ["all", "-filler"]
    assert options.sponsorblock_categories_for("sponsor") == ["sponsor"]
    assert options.sponsorblock_categories_for(["intro", "outro"]) == ["intro", "outro"]
    assert options.sponsorblock_categories_for(None) == []


def test_sponsorblock_non_removable_dropped() -> None:
    cats = options.removable_sponsorblock_categories(
        ["sponsor", "chapter", "poi_highlight", "intro"]
    )
    assert cats == ["sponsor", "intro"]


def test_sponsorblock_only_non_removable_adds_no_chain() -> None:
    opts = options.build_ydl_opts(
        make(sponsorblock_enabled=True, sponsorblock_categories=["chapter"])
    )
    assert "postprocessors" not in opts


def test_sponsorblock_default_remove_chain() -> None:
    opts = options.build_ydl_opts(
        make(sponsorblock_enabled=True, sponsorblock_categories=["all", "-filler"])
    )
    assert opts["postprocessors"][0] == {
        "key": "SponsorBlock",
        "categories": ["all", "-filler"],
        "when": "after_filter",
    }
    assert {
        "key": "ModifyChapters",
        "remove_sponsor_segments": ["all", "-filler"],
    } in opts["postprocessors"]


# ── 3.4 conversion (extra #12) ───────────────────────────────────────────────
def test_remux_uses_remuxer_key() -> None:
    opts = options.build_ydl_opts(make(video_container="mp4", video_remux=True))
    assert opts["postprocessors"] == [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}]


def test_recode_is_default_for_video_container() -> None:
    opts = options.build_ydl_opts(make(video_container="webm", video_remux=False))
    assert opts["postprocessors"] == [{"key": "FFmpegVideoConvertor", "preferedformat": "webm"}]


def test_validate_conversion_rejects_unknown_container() -> None:
    with pytest.raises(options.ConversionError):
        options.build_ydl_opts(make(video_container="doc"))


def test_validate_conversion_rejects_audio_plus_video() -> None:
    with pytest.raises(options.ConversionError):
        options.build_ydl_opts(make(audio_only=True, video_container="mp4"))


def test_validate_conversion_rejects_unknown_audio_codec() -> None:
    with pytest.raises(options.ConversionError):
        options.build_ydl_opts(make(audio_only=True, audio_codec="wma"))


def test_validate_conversion_accepts_valid_combos() -> None:
    options.validate_conversion(make(audio_only=True, audio_codec="m4a"))
    options.validate_conversion(make(video_container="mkv"))
    options.validate_conversion(make())


# ── 4.1 cookies (extra #11) ──────────────────────────────────────────────────
def test_cookiefile_injected() -> None:
    opts = options.build_ydl_opts(
        make(use_cookies=True, cookie_browser=None, cookie_file=r"C:\c\cookies.txt")
    )
    assert opts["cookiefile"] == r"C:\c\cookies.txt"
    assert "cookiesfrombrowser" not in opts


def test_cookies_both_sources_injected() -> None:
    opts = options.build_ydl_opts(
        make(use_cookies=True, cookie_browser="firefox", cookie_file=r"C:\c\cookies.txt")
    )
    assert opts["cookiefile"] == r"C:\c\cookies.txt"
    assert opts["cookiesfrombrowser"] == ("firefox",)


def test_cookies_disabled_ignores_sources() -> None:
    opts = options.build_ydl_opts(
        make(use_cookies=False, cookie_browser="chrome", cookie_file=r"C:\c\cookies.txt")
    )
    assert "cookiefile" not in opts
    assert "cookiesfrombrowser" not in opts


# ══ leaf 8.2 — consolidated exact-shape proof across >= 8 permutations ════════
# Each row drives ``build_ydl_opts`` from a hermetic ``fake_settings`` (conftest)
# and asserts the *exact* shape of the resulting opts for one feature permutation:
# the format string, the full ordered postprocessor chain (or its absence), and
# the feature-specific key. This complements the per-feature tests above with a
# single, table-driven exact-dict contract.

_OPTION_SHAPES: list[tuple[str, dict[str, object], dict[str, object]]] = [
    (
        "default",
        {},
        {"format": "bv*+ba/b", "postprocessors": None, "merge_output_format": "mp4/mkv"},
    ),
    (
        "audio-only",
        {"audio_only": True, "audio_codec": "mp3"},
        {
            "format": "bestaudio/best",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}
            ],
        },
    ),
    (
        "subtitles+embed",
        {"write_subs": True, "embed_subs": True, "sub_langs": ["en", "es"]},
        {"postprocessors": None},
    ),
    (
        "sponsorblock",
        {"sponsorblock_enabled": True, "sponsorblock_categories": ["sponsor", "selfpromo"]},
        {
            "postprocessors": [
                {
                    "key": "SponsorBlock",
                    "categories": ["sponsor", "selfpromo"],
                    "when": "after_filter",
                },
                {
                    "key": "ModifyChapters",
                    "remove_sponsor_segments": ["sponsor", "selfpromo"],
                },
            ]
        },
    ),
    (
        "conversion",
        {"video_container": "mkv"},
        {"postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mkv"}]},
    ),
    (
        "cookies",
        {"use_cookies": True, "cookie_browser": "chrome"},
        {"cookiesfrombrowser": ("chrome",)},
    ),
    (
        "playlist-range",
        {"playlist_items": "1-10"},
        {"playlist_items": "1-10"},
    ),
]


@pytest.mark.parametrize(
    ("case", "overrides", "expected"),
    _OPTION_SHAPES,
    ids=[case for case, _, _ in _OPTION_SHAPES],
)
def test_exact_option_shape(fake_settings, case, overrides, expected) -> None:
    opts = options.build_ydl_opts(fake_settings(**overrides))

    # Leaf 10.8: no permutation may ever inject a download archive.
    assert "download_archive" not in opts, case
    if "format" in expected:
        assert opts["format"] == expected["format"], case
    if "merge_output_format" in expected:
        assert opts["merge_output_format"] == expected["merge_output_format"], case
    if "postprocessors" in expected:
        if expected["postprocessors"] is None:
            assert "postprocessors" not in opts, case
        else:
            assert opts["postprocessors"] == expected["postprocessors"], case
    if "cookiesfrombrowser" in expected:
        assert opts["cookiesfrombrowser"] == expected["cookiesfrombrowser"], case
    if "playlist_items" in expected:
        assert opts["playlist_items"] == expected["playlist_items"], case


def test_sample_info_dict_fixture_subtitle_helpers(sample_info_dict) -> None:
    """The shared info fixture exercises the subtitle-availability helpers."""
    assert options.subtitle_langs_present(sample_info_dict, ["en"]) == ["en"]
    assert options.subtitle_langs_present(sample_info_dict, ["all"]) == ["en", "es"]
    assert options.subtitle_langs_present(sample_info_dict, ["fr"]) == []
    settings = make(write_subs=True, sub_langs=["en"])
    assert options.subtitle_warning(sample_info_dict, settings) is None
