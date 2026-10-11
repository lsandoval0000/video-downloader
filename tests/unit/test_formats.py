"""Unit tests for :mod:`vdl.core.formats` — no network, no PySide6.

Format enumeration is exercised against a fake yt-dlp info dict; the real
:func:`list_formats` (which hits the network) is left to integration tests.
"""

from __future__ import annotations

from typing import Any

from vdl.core.formats import (
    FORMAT_PRESETS,
    FormatInfo,
    _formats_from_info,
    format_selector,
)

FAKE_INFO: dict[str, Any] = {
    "formats": [
        {"format_id": "137", "vcodec": "avc1", "acodec": "none"},
        {"format_id": "140", "vcodec": "none", "acodec": "mp4a"},
        {"format_id": "18", "vcodec": "avc1", "acodec": "mp4a"},
    ]
}


def test_preset_strings_are_exact() -> None:
    assert FORMAT_PRESETS == {
        "best": "bv*+ba/b",
        "1080p": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
        "720p": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
        "audio": "bestaudio/best",
        "smallest": "wv*+wa/w",
    }


def test_named_presets_round_trip() -> None:
    for name, expected in FORMAT_PRESETS.items():
        assert format_selector(name) == expected


def test_unknown_preset_defaults_to_video_plus_audio() -> None:
    assert format_selector("137") == "137+bestaudio/best"


def test_explicit_video_only_format() -> None:
    assert format_selector("137", FAKE_INFO) == "137+bestaudio/best"


def test_explicit_audio_only_format() -> None:
    assert format_selector("140", FAKE_INFO) == "140/bestaudio/best"


def test_explicit_muxed_format() -> None:
    assert format_selector("18", FAKE_INFO) == "18/best"


def test_format_info_from_ytdlp_full() -> None:
    info = FormatInfo.from_ytdlp(
        {
            "format_id": "137",
            "ext": "mp4",
            "resolution": "1920x1080",
            "fps": 30,
            "vcodec": "avc1",
            "acodec": "none",
            "filesize": 1234,
            "format_note": "1080p",
        }
    )
    assert info.id == "137"
    assert info.ext == "mp4"
    assert info.resolution == "1920x1080"
    assert info.fps == 30
    assert info.filesize == 1234
    assert info.note == "1080p"


def test_format_info_resolution_fallback_and_approx_size() -> None:
    info = FormatInfo.from_ytdlp(
        {"format_id": "x", "width": 1280, "height": 720, "filesize_approx": 999}
    )
    assert info.resolution == "1280x720"
    assert info.filesize == 999


def test_formats_from_info_flattens_formats() -> None:
    out = _formats_from_info({"formats": FAKE_INFO["formats"]})
    assert [f.id for f in out] == ["137", "140", "18"]


def test_formats_from_info_playlist_uses_first_entry() -> None:
    info = {
        "_type": "playlist",
        "entries": [
            {"formats": [{"format_id": "1"}]},
            {"formats": [{"format_id": "2"}]},
        ],
    }
    assert [f.id for f in _formats_from_info(info)] == ["1"]


def test_formats_from_info_empty() -> None:
    assert _formats_from_info(None) == []
    assert _formats_from_info({}) == []
