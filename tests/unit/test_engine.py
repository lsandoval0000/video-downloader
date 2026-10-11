"""Unit tests for :mod:`vdl.core.engine` — subtitle isolation (10.5 round 2).

Hermetic: ``yt_dlp.YoutubeDL`` is replaced with a stub (no network / no ffmpeg).
The contract under test is the fix for the reproduced bug where yt-dlp wrote
subtitles *before* the media, so a rate-limited subtitle request (``HTTP 429``)
raised ``DownloadError`` with **no media on disk yet** and aborted the whole job.

Covered:

* the media pass is subtitle-free and a subtitle 429 in the isolated pass is only
  a warning — the media job still finishes;
* a genuine media failure (no media output) stays fatal and skips subtitles;
* subtitle embedding is best-effort (a failed embed is a warning);
* helper edge cases (sidecar/language parsing).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from typing import Any

import pytest
import yt_dlp

from vdl.core import engine
from vdl.core.queue import Job
from vdl.paths import ffprobe_exe

#: The real message yt-dlp raises when a subtitle write is rate-limited.
_SUBTITLE_429 = (
    "ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests"
)

#: A genuine media failure message.
_MEDIA_FAIL = "ERROR: unable to download video data: HTTP Error 403: Forbidden"


class _StubYDL:
    """A ``YoutubeDL`` stand-in that runs a per-pass action (or raises)."""

    def __init__(self, opts: dict[str, Any], calls: list[dict[str, Any]]) -> None:
        self._opts = opts
        self._calls = calls

    def __enter__(self) -> _StubYDL:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def download(self, urls: list[str]) -> None:
        self._calls.append(dict(self._opts))
        action = self._opts.get("__action__")
        if isinstance(action, BaseException):
            raise action
        if callable(action):
            action()


def _install_ydl(
    monkeypatch: pytest.MonkeyPatch,
    *,
    media: Callable[[], None] | BaseException | None = None,
    subtitle: Callable[[], None] | BaseException | None = None,
) -> list[dict[str, Any]]:
    """Install a stub ``YoutubeDL``; ``media``/``subtitle`` run per pass.

    The engine marks the isolated subtitle pass with ``skip_download=True``; the
    stub dispatches on that key. Returns the list of opts dicts seen, in order.
    """
    calls: list[dict[str, Any]] = []

    def _factory(opts: dict[str, Any]) -> _StubYDL:
        opts = dict(opts)
        opts["__action__"] = subtitle if opts.get("skip_download") else media
        return _StubYDL(opts, calls)

    monkeypatch.setattr(engine.yt_dlp, "YoutubeDL", _factory)
    return calls


def _raise(exc: BaseException) -> Callable[[], None]:
    def _action() -> None:
        raise exc

    return _action


def _run(worker: engine.DownloadWorker) -> tuple[list[list[str]], list[str]]:
    """Run ``worker`` synchronously and collect its ``finished``/``error`` payloads."""
    finished: list[list[str]] = []
    errors: list[str] = []
    worker.finished.connect(finished.append)
    worker.error.connect(errors.append)
    worker.run()
    return finished, errors


# ══ media-pass isolation (leaf 10.5 round 2) ═════════════════════════════════


def test_media_pass_is_subtitle_free(fake_settings) -> None:
    """The media opts must not enable subtitle writing (the root cause)."""
    from vdl.core.options import build_ydl_opts

    opts = build_ydl_opts(fake_settings(write_subs=True, embed_subs=True))
    assert "writesubtitles" not in opts
    assert "writeautomaticsub" not in opts
    assert "FFmpegEmbedSubtitle" not in [pp["key"] for pp in opts.get("postprocessors", [])]


def test_subtitle_429_in_isolated_pass_keeps_media_job(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A subtitle 429 (isolated pass) is a warning; the media job still finishes."""
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")

    settings = fake_settings(download_dir=str(tmp_path), write_subs=True, embed_subs=False)
    worker = engine.DownloadWorker(settings, Job(id="j1", url="https://example.com/v"))
    worker._output_paths.append(str(media))  # the media pass completed

    calls = _install_ydl(monkeypatch, subtitle=_raise(yt_dlp.utils.DownloadError(_SUBTITLE_429)))

    finished, errors = _run(worker)

    assert errors == [], "a subtitle 429 must not fail a job whose media exists"
    assert finished == [[str(media)]]
    assert any(c.get("skip_download") for c in calls), "a subtitle-only pass must run"
    # The media pass must NOT have downloaded subtitles itself.
    assert not any(c.get("writesubtitles") for c in calls if not c.get("skip_download"))


def test_subtitle_pass_success_keeps_media_job(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")

    settings = fake_settings(download_dir=str(tmp_path), write_subs=True)
    worker = engine.DownloadWorker(settings, Job(id="j1b", url="https://example.com/v"))
    worker._output_paths.append(str(media))
    _install_ydl(monkeypatch)

    finished, errors = _run(worker)

    assert errors == []
    assert finished == [[str(media)]]


def test_media_failure_without_output_is_fatal(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine media failure (no media output) stays fatal and skips subtitles."""
    settings = fake_settings(download_dir=str(tmp_path), write_subs=True)
    worker = engine.DownloadWorker(settings, Job(id="j2", url="https://example.com/v"))
    calls = _install_ydl(monkeypatch, media=_raise(yt_dlp.utils.DownloadError(_MEDIA_FAIL)))

    finished, errors = _run(worker)

    assert finished == [], "no media output means the job must not be marked done"
    assert errors == [_MEDIA_FAIL]
    assert not any(c.get("skip_download") for c in calls), "no subtitle pass on a dead job"


def test_media_error_with_output_finishes_with_warning(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A late post-process error that leaves the media on disk is not fatal."""
    media = tmp_path / "clip.webm"
    media.write_bytes(b"media")

    settings = fake_settings(download_dir=str(tmp_path))
    worker = engine.DownloadWorker(settings, Job(id="j2b", url="https://example.com/v"))
    worker._output_paths.append(str(media))
    _install_ydl(monkeypatch, media=_raise(yt_dlp.utils.DownloadError("ERROR: ffmpeg exited")))

    finished, errors = _run(worker)

    assert errors == []
    assert finished == [[str(media)]]


def test_sidecar_only_output_is_still_fatal(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stray subtitle file does not count as the media deliverable."""
    sidecar = tmp_path / "clip.en.srt"
    sidecar.write_text("1\n", encoding="utf-8")

    settings = fake_settings(download_dir=str(tmp_path), write_subs=True)
    worker = engine.DownloadWorker(settings, Job(id="j3", url="https://example.com/v"))
    worker._output_paths.append(str(sidecar))
    _install_ydl(monkeypatch, media=_raise(yt_dlp.utils.DownloadError(_SUBTITLE_429)))

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
    _install_ydl(
        monkeypatch, media=_raise(yt_dlp.utils.DownloadError("ERROR: ffmpeg exited with code 1"))
    )

    finished, errors = _run(worker)

    assert finished == []
    assert errors == ["ERROR: ffmpeg exited with code 1"]


def test_subtitles_skipped_when_disabled(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No subtitle pass is run when the user asked for no subtitles."""
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")

    settings = fake_settings(download_dir=str(tmp_path), write_subs=False, embed_subs=False)
    worker = engine.DownloadWorker(settings, Job(id="j5", url="https://example.com/v"))
    worker._output_paths.append(str(media))
    calls = _install_ydl(monkeypatch)

    finished, errors = _run(worker)

    assert errors == [] and finished == [[str(media)]]
    assert not any(c.get("skip_download") for c in calls)


# ══ embedding (leaf 10.5 phase 3) ═════════════════════════════════════════════


def test_embed_failure_is_non_fatal_and_keeps_media(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")
    sub = tmp_path / "clip.en.srt"
    sub.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")

    settings = fake_settings(download_dir=str(tmp_path), write_subs=False, embed_subs=True)
    worker = engine.DownloadWorker(settings, Job(id="j6", url="https://example.com/v"))
    worker._output_paths.append(str(media))
    _install_ydl(monkeypatch)

    def _bad_run(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr(engine.subprocess, "run", _bad_run)

    finished, errors = _run(worker)

    assert errors == [], "a failed embed must never fail the job"
    assert finished == [[str(media)]]
    assert media.exists() and sub.exists(), "the failed embed must not destroy anything"


def test_embed_success_removes_sidecar_unless_write_subs(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")
    sub = tmp_path / "clip.en.srt"
    sub.write_text("1\n", encoding="utf-8")

    def _ok_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        # Emulate ffmpeg writing the muxed output to the temp target.
        with open(cmd[-1], "wb") as handle:
            handle.write(b"muxed")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(engine.subprocess, "run", _ok_run)

    # embed-only -> sidecar is deleted (yt-dlp semantics)
    settings = fake_settings(download_dir=str(tmp_path), write_subs=False, embed_subs=True)
    worker = engine.DownloadWorker(settings, Job(id="j7", url="https://example.com/v"))
    worker._output_paths.append(str(media))
    _install_ydl(monkeypatch)
    finished, errors = _run(worker)
    assert errors == [] and finished == [[str(media)]]
    assert media.read_bytes() == b"muxed"
    assert not sub.exists(), "embed-only must delete the sidecar after embedding"

    # write + embed -> sidecar is kept
    sub.write_text("1\n", encoding="utf-8")
    settings2 = fake_settings(download_dir=str(tmp_path), write_subs=True, embed_subs=True)
    worker2 = engine.DownloadWorker(settings2, Job(id="j8", url="https://example.com/v"))
    worker2._output_paths.append(str(media))
    _install_ydl(monkeypatch)
    finished2, errors2 = _run(worker2)
    assert errors2 == [] and finished2 == [[str(media)]]
    assert sub.exists(), "write+embed must keep the sidecar"


def test_ffmpeg_cmd_uses_mov_text_for_mp4(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The mux command mirrors yt-dlp (``-c copy`` + ``mov_text`` for mp4).

    The language tag must be the ISO 639-2/T **3-letter** code (``eng``): the mp4
    muxer silently drops the 2-letter form (leaf 10.5 follow-up).
    """
    captured: list[list[str]] = []

    def _capture(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        captured.append(cmd)
        with open(cmd[-1], "wb") as handle:
            handle.write(b"x")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(engine.subprocess, "run", _capture)
    media = tmp_path / "movie.mp4"
    media.write_bytes(b"m")
    sub = tmp_path / "movie.en.srt"
    sub.write_text("1\n", encoding="utf-8")

    engine.DownloadWorker._mux_subtitles(str(media), [str(sub)], "mp4")

    cmd = captured[0]
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert "-c:s" in cmd and cmd[cmd.index("-c:s") + 1] == "mov_text"
    assert cmd.count("-map") >= 3  # 0, -0:s, and each subtitle
    assert "language=eng" in cmd, "mp4/mov_text needs the 3-letter ISO 639-2 code"
    assert "language=en" not in cmd


def test_ffmpeg_cmd_keeps_two_letter_language_for_mkv(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mkv keeps the 2-letter tag (its muxer accepts it) — behaviour unchanged."""
    captured: list[list[str]] = []

    def _capture(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        captured.append(cmd)
        with open(cmd[-1], "wb") as handle:
            handle.write(b"x")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(engine.subprocess, "run", _capture)
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"m")
    sub = tmp_path / "movie.en.srt"
    sub.write_text("1\n", encoding="utf-8")

    engine.DownloadWorker._mux_subtitles(str(media), [str(sub)], "mkv")

    cmd = captured[0]
    assert "-c:s" not in cmd, "mkv uses its native subtitle codec (no mov_text)"
    assert "language=en" in cmd and "language=eng" not in cmd


def test_mp4_embed_writes_three_letter_language_tag(tmp_path) -> None:
    """Real ffmpeg -> ffprobe round-trip: the mp4 subtitle tag is 3-letter.

    Skipped when the bundled ``ffmpeg``/``ffprobe`` are unavailable (the unit
    suite must stay runnable without the vendored binaries).
    """
    ffmpeg = engine.ffmpeg_exe()
    ffprobe = ffprobe_exe()
    if not (os.path.exists(ffmpeg) and os.path.exists(ffprobe)):
        pytest.skip("bundled ffmpeg/ffprobe not available")

    src = tmp_path / "movie.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-t",
            "1",
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    sub = tmp_path / "movie.en.srt"
    sub.write_text("1\n00:00:00,000 --> 00:00:00,500\nhi\n", encoding="utf-8")

    engine.DownloadWorker._mux_subtitles(str(src), [str(sub)], "mp4")

    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream_tags=language",
            "-of",
            "default=noprint_wrappers=1",
            str(src),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "language=eng" in probe.stdout, f"expected a 3-letter tag, got: {probe.stdout!r}"


def test_unexpected_subtitle_exception_still_finishes_media_job(
    fake_settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a bug in the subtitle phase must not stop the job reporting finished."""
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")

    settings = fake_settings(download_dir=str(tmp_path), write_subs=True)
    worker = engine.DownloadWorker(settings, Job(id="j9", url="https://example.com/v"))
    worker._output_paths.append(str(media))
    _install_ydl(monkeypatch)

    def _boom() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "_acquire_subtitles", _boom)

    finished, errors = _run(worker)

    assert errors == []
    assert finished == [[str(media)]]


# ══ pure helpers ══════════════════════════════════════════════════════════════


def test_subtitle_language_parsing() -> None:
    assert engine._subtitle_language("/dl/Foo [id].webm", "/dl/Foo [id].en.vtt") == "en"
    assert engine._subtitle_language("/dl/Foo [id].webm", "/dl/Foo [id].en-US.srt") == "en-US"
    assert engine._subtitle_language("/dl/Foo.webm", "/dl/Other.en.vtt") is None


def test_subtitle_language_tag_maps_to_iso639_2_for_mp4() -> None:
    """mov_text containers get the 3-letter code; other containers are verbatim."""
    # mp4 family -> ISO 639-2/T
    assert engine._subtitle_language_tag("en", "mp4") == "eng"
    assert engine._subtitle_language_tag("es", "mp4") == "spa"
    assert engine._subtitle_language_tag("fr", "mp4") == "fra"
    assert engine._subtitle_language_tag("ja", "mp4") == "jpn"
    # region-qualified -> primary subtag mapped
    assert engine._subtitle_language_tag("en-US", "mp4") == "eng"
    assert engine._subtitle_language_tag("pt-BR", "mov") == "por"
    # mkv/webm keep the code as-is (behaviour unchanged)
    assert engine._subtitle_language_tag("en", "mkv") == "en"
    assert engine._subtitle_language_tag("en", "webm") == "en"
    # unknown code / no code -> unchanged
    assert engine._subtitle_language_tag("xx", "mp4") == "xx"
    assert engine._subtitle_language_tag("en-US", "mkv") == "en-US"
    assert engine._subtitle_language_tag(None, "mp4") is None
    assert engine._subtitle_language_tag("", "mp4") == ""


def test_subtitle_sidecars_match_media_stem(tmp_path) -> None:
    media = tmp_path / "Foo [id].webm"
    media.write_bytes(b"m")
    (tmp_path / "Foo [id].en.vtt").write_text("x", encoding="utf-8")
    (tmp_path / "Foo [id].es.srt").write_text("x", encoding="utf-8")
    (tmp_path / "Foo [id].json3").write_text("x", encoding="utf-8")  # not embeddable
    (tmp_path / "Other.en.vtt").write_text("x", encoding="utf-8")  # different stem

    subs = engine.DownloadWorker._subtitle_sidecars(str(media))

    names = sorted(os.path.basename(p) for p in subs)
    assert names == ["Foo [id].en.vtt", "Foo [id].es.srt"]
