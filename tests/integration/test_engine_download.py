"""Integration test: real download through :mod:`vdl.core.engine` (leaf 8.3).

Opt-in only — marked ``integration`` and skipped unless ``--run-integration`` or
``VDL_RUN_INTEGRATION=1`` (see ``tests/conftest.py``). Downloads a KNOWN SHORT
public video ("Me at the zoo", 19 s) to a temp dir via
:class:`~vdl.core.engine.DownloadWorker` and asserts that a non-empty output file
exists and that a ``progress_hooks`` ``"finished"`` event was received.

Override the URL with ``VDL_TEST_URL`` (e.g. a non-YouTube source) to exercise a
different extractor.

GOTCHA: with ``js_runtime_enabled=True`` this validates the bundled-``deno`` /
``yt-dlp-ejs`` path. A failure that reproduces *only* on YouTube (format
extraction / signature challenges) is the JS-runtime signal — install/populate
``vendor/bin/deno.exe`` + ``yt_dlp_ejs`` — and is **not** a download-engine bug.
The assertion messages say so explicitly.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

#: "Me at the zoo" — the first YouTube video, 19 s, public and stable.
DEFAULT_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

#: Sidecar/intermediate artefacts that do not count as the finished media file.
_IGNORED_SUFFIXES = frozenset({".part", ".ytdl", ".webp", ".jpg", ".jpeg", ".png"})


def _test_url() -> str:
    return os.environ.get("VDL_TEST_URL", "").strip() or DEFAULT_URL


def _media_files(directory: Path) -> list[Path]:
    return [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() not in _IGNORED_SUFFIXES
    ]


def test_engine_downloads_short_video(tmp_path: Path) -> None:
    from vdl.config import Settings
    from vdl.core.engine import DownloadWorker
    from vdl.core.queue import Job

    url = _test_url()
    settings = Settings(
        download_dir=str(tmp_path),
        default_format_preset="best",
        # Keep the run minimal + hermetic: a single media file in tmp_path, no
        # sidecar subtitles/thumbnails, and no writes to the real user-data dir.
        write_subs=False,
        embed_subs=False,
        embed_thumbnail=False,
        embed_metadata=False,
        archive_enabled=False,
        # Exercise the deno / yt-dlp-ejs path (the whole point of the gotcha).
        js_runtime_enabled=True,
    )
    job = Job(id="integration-download", url=url)

    worker = DownloadWorker(settings, job)
    progress: list[dict] = []
    errors: list[str] = []
    worker.progress.connect(progress.append)
    worker.error.connect(errors.append)

    # Run synchronously on this thread: signal connections become direct calls,
    # so no QApplication / event loop is required (the test stays headless).
    worker.run()

    assert not errors, (
        f"engine reported an error for {url!r}: {errors!r}\n"
        "If this only fails on YouTube, it is the deno / yt-dlp-ejs JS-runtime "
        "signal (bundled deno.exe + yt_dlp_ejs) — not a download-engine bug."
    )

    finished = [event for event in progress if event.get("status") == "finished"]
    assert finished, (
        f"no progress hook reported status='finished' for {url!r} — the download never completed"
    )

    files = _media_files(tmp_path)
    assert files, (
        f"no output file was produced under {tmp_path} for {url!r} "
        "(a YouTube-only failure again points at the JS runtime)."
    )
    produced = max(files, key=lambda path: path.stat().st_size)
    assert produced.stat().st_size > 0, f"output file {produced} is empty"
