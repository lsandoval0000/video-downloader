"""Unit tests for :mod:`vdl.config` (round-trip, recovery, preset CRUD)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vdl.config import ConfigStore, Preset, Settings


def test_defaults_when_file_absent(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.json").load()
    assert store.settings == Settings()
    assert store.list_presets() == []


def test_settings_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    store = ConfigStore(path).load()
    store.set("download_dir", r"C:\downloads")
    store.set("max_concurrent", 5)
    store.set("audio_codec", "m4a")
    store.save()

    reloaded = ConfigStore(path).load()
    assert reloaded.get("download_dir") == r"C:\downloads"
    assert reloaded.get("max_concurrent") == 5
    assert reloaded.get("audio_codec") == "m4a"


def test_get_unknown_key_returns_default(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.json").load()
    assert store.get("does_not_exist", "fallback") == "fallback"


def test_set_unknown_key_raises(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.json").load()
    with pytest.raises(KeyError):
        store.set("does_not_exist", 1)


def test_corrupt_file_recovery(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{ this is : not valid json", encoding="utf-8")
    store = ConfigStore(path).load()  # must not raise
    assert store.get("max_concurrent") == 2
    # and it can still be written over cleanly
    store.save()
    assert json.loads(path.read_text(encoding="utf-8"))["settings"]["max_concurrent"] == 2


def test_non_object_file_recovery(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    store = ConfigStore(path).load()
    assert store.settings == Settings()


def test_incompatible_settings_recovery(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"settings": {"max_concurrent": "not-an-int"}}), encoding="utf-8")
    store = ConfigStore(path).load()
    assert store.get("max_concurrent") == 2


def test_preset_crud_and_persistence(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    store = ConfigStore(path).load()
    store.add_preset(Preset(name="Music", values={"audio_only": True, "audio_codec": "mp3"}))
    store.add_preset(Preset(name="Video 1080p", values={"default_format_preset": "1080p"}))

    assert [p.name for p in store.list_presets()] == ["Music", "Video 1080p"]

    # persists across a fresh process-equivalent store
    reloaded = ConfigStore(path).load()
    music = reloaded.get_preset("Music")
    assert music is not None
    assert music.values["audio_codec"] == "mp3"

    # upsert replaces by name
    reloaded.add_preset(Preset(name="Music", values={"audio_only": True, "audio_codec": "m4a"}))
    assert reloaded.get_preset("Music") is not None
    assert reloaded.get_preset("Music").values["audio_codec"] == "m4a"
    assert len(reloaded.list_presets()) == 2

    assert reloaded.delete_preset("Music") is True
    assert reloaded.delete_preset("Music") is False
    assert [p.name for p in reloaded.list_presets()] == ["Video 1080p"]
