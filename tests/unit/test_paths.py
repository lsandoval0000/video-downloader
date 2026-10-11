"""Unit tests for :mod:`vdl.paths` (frozen vs unfrozen resolution)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from vdl import paths


def _go_unfrozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)


def _go_frozen(monkeypatch: pytest.MonkeyPatch, base: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(base), raising=False)


def test_resource_path_dev_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    _go_unfrozen(monkeypatch)
    assert Path(paths.resource_path("bin", "ffmpeg.exe")) == (
        paths._REPO_ROOT / "vendor" / "bin" / "ffmpeg.exe"
    )


def test_resource_path_frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _go_frozen(monkeypatch, tmp_path)
    assert Path(paths.resource_path("bin", "ffmpeg.exe")) == tmp_path / "bin" / "ffmpeg.exe"


def test_resource_path_dev_package_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    _go_unfrozen(monkeypatch)
    assert Path(paths.resource_path("resources", "icons", "app.png")) == (
        paths._PACKAGE_DIR / "resources" / "icons" / "app.png"
    )


def test_binary_helpers_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    _go_unfrozen(monkeypatch)
    assert Path(paths.ffmpeg_exe()) == paths._REPO_ROOT / "vendor" / "bin" / "ffmpeg.exe"
    assert Path(paths.ffprobe_exe()) == paths._REPO_ROOT / "vendor" / "bin" / "ffprobe.exe"
    assert Path(paths.deno_exe()) == paths._REPO_ROOT / "vendor" / "bin" / "deno.exe"
    assert Path(paths.libmpv_dll()) == paths._REPO_ROOT / "vendor" / "libmpv" / "libmpv-2.dll"


def test_binary_helpers_frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _go_frozen(monkeypatch, tmp_path)
    assert Path(paths.ffmpeg_exe()) == tmp_path / "bin" / "ffmpeg.exe"
    assert Path(paths.libmpv_dll()) == tmp_path / "libmpv" / "libmpv-2.dll"


def test_user_data_dir_portable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    (tmp_path / "portable.txt").write_text("", encoding="utf-8")
    result = paths.user_data_dir()
    assert result == tmp_path / "data"
    assert result.is_dir()


def test_user_data_dir_non_portable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(
        paths.platformdirs, "user_data_dir", lambda *_a, **_k: str(tmp_path / "appdata")
    )
    result = paths.user_data_dir()
    assert result == tmp_path / "appdata"
    assert result.is_dir()


def test_user_data_dir_passes_appauthor_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Guard against the doubled ``VideoDownloader\\VideoDownloader`` directory (10.6).

    platformdirs mirrors ``appauthor=appname`` when the author is left unset, which
    would build ``<...>/VideoDownloader/VideoDownloader``. The resolver must pass
    ``appauthor=False`` so the app name appears exactly once.
    """
    captured: dict[str, object] = {}

    def fake_user_data_dir(appname: str, *args: object, **kwargs: object) -> str:
        captured["appname"] = appname
        captured["appauthor"] = kwargs.get("appauthor", "MISSING")
        return str(tmp_path / "appdata")

    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(paths.platformdirs, "user_data_dir", fake_user_data_dir)

    paths.user_data_dir()

    assert captured["appname"] == "VideoDownloader"
    assert captured["appauthor"] is False


@pytest.mark.skipif(os.name != "nt", reason="Windows-only DLL search sanitisation")
def test_sanitize_dll_search_strips_meipass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", r"C:\fake\meipass", raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([r"C:\fake\meipass", r"C:\Windows"]))
    paths._sanitize_dll_search()
    entries = os.environ["PATH"].split(os.pathsep)
    assert r"C:\fake\meipass" not in entries
    assert r"C:\Windows" in entries
