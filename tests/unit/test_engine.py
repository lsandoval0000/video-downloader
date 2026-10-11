"""Unit tests for :mod:`vdl.core.engine` — outcome-aware ``DownloadError`` (10.5).

Hermetic: ``yt_dlp.YoutubeDL`` is replaced with a stub that raises the exact
``DownloadError`` a failed subtitle fetch produces (``HTTP Error 429``), so no
network/ffmpeg runs. The contract under test is the fix for the observed bug
where a subtitle write failing *after* the media downloaded aborted the whole job:

* a ``DownloadError`` with the media deliverable on disk finishes the job
  (``finished``) with a warning instead of failing it (``error``);
* a ``DownloadError`` with no media output (or only sidecar/fragment files) stays
  fatal — genuine media failures must not be masked.
"""

from __future__ import annotations

from typing import Any

import pytest
import yt_dlp

from vdl.core import engine
from vdl.core.queue import Job

#: The real message yt-dlp raises when a subtitle write is rate-limited.
_SUBTITLE_429 = (
    "ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests"
)


def _install_raising_ydl(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """Replace ``yt_dlp.YoutubeDL`` with a context manager whose download raises."""

    class _RaisingYDL:
        def __init__(self, opts: dict[str, Any]) -> None:
            self._opts = opts

        def __enter__(self) -> _RaisingYDL:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def download(self, urls: list[str]) -> None:
            raise exc

    monkeypatch.setattr(engine.yt_dlp, "YoutubeDL", _RaisingYDL)


def _run(worker: engine.DownloadWorker) -> tuple[list[list[str]], list[str]]:
    """Run ``worker`` synchronously and collect its ``finished``/``error`` payloads."""
    finished: list[list[str]] = []
    errors: list[str] = []
    worker.finished.connect(finished.append)
    worker.error.connect(errors.append)
    worker.run()
    return finished, errors


def test_subtitle_error_with_existing_media_is_success(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")

    settings = fake_settings(download_dir=str(tmp_path), write_subs=True, embed_subs=True)
    worker = engine.DownloadWorker(settings, Job(id="j1", url="https://example.com/v"))
    worker._output_paths.append(str(media))  # the media already completed

    _install_raising_ydl(monkeypatch, yt_dlp.utils.DownloadError(_SUBTITLE_429))

    finished, errors = _run(worker)

    assert errors == [], "a subtitle 429 must not fail a job whose media exists"
    assert finished == [[str(media)]]


def test_media_error_without_output_is_fatal(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = fake_settings(download_dir=str(tmp_path))
    worker = engine.DownloadWorker(settings, Job(id="j2", url="https://example.com/v"))
    _install_raising_ydl(monkeypatch, yt_dlp.utils.DownloadError(_SUBTITLE_429))

    finished, errors = _run(worker)

    assert finished == [], "no media output means the job must not be marked done"
    assert errors == [_SUBTITLE_429]


def test_sidecar_only_output_is_still_fatal(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stray subtitle file does not count as the media deliverable."""
    sidecar = tmp_path / "clip.en.srt"
    sidecar.write_text("1\n", encoding="utf-8")

    settings = fake_settings(download_dir=str(tmp_path), write_subs=True)
    worker = engine.DownloadWorker(settings, Job(id="j3", url="https://example.com/v"))
    worker._output_paths.append(str(sidecar))
    _install_raising_ydl(monkeypatch, yt_dlp.utils.DownloadError(_SUBTITLE_429))

    finished, errors = _run(worker)

    assert finished == []
    assert errors == [_SUBTITLE_429]


def test_fragment_only_output_is_still_fatal(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un-merged ``.f<id>`` intermediates are not the finished media."""
    fragment = tmp_path / "clip [id].f137.mp4"
    fragment.write_bytes(b"fragment")

    settings = fake_settings(download_dir=str(tmp_path))
    worker = engine.DownloadWorker(settings, Job(id="j4", url="https://example.com/v"))
    worker._output_paths.append(str(fragment))
    _install_raising_ydl(
        monkeypatch, yt_dlp.utils.DownloadError("ERROR: ffmpeg exited with code 1")
    )

    finished, errors = _run(worker)

    assert finished == []
    assert errors == ["ERROR: ffmpeg exited with code 1"]
