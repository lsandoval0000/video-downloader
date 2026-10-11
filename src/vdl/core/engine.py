"""In-process yt-dlp download worker (extra #6).

A :class:`DownloadWorker` is a :class:`~PySide6.QtCore.QThread` that runs one
job through ``yt_dlp.YoutubeDL`` in-process. yt-dlp's ``progress_hooks`` /
``postprocessor_hooks`` fire **on this worker thread**, so the hooks only ever
emit Qt signals — they must never touch widgets (plan anti-pattern). The GUI
thread stays responsive and renders from the signals.

Cancellation / pausing: yt-dlp has no true pause. Both pause and cancel work by
raising :class:`yt_dlp.utils.DownloadCancelled` from the progress hook at the
next tick, which aborts cleanly while leaving the ``.part`` file in place. The
queue decides the final state (paused keeps ``.part``; cancel deletes it).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import yt_dlp
from PySide6.QtCore import QThread, Signal

from vdl.core.options import build_ydl_opts

if TYPE_CHECKING:
    from vdl.config import Settings
    from vdl.core.queue import Job

logger = logging.getLogger("vdl.core.engine")


class DownloadWorker(QThread):
    """Runs a single :class:`~vdl.core.queue.Job` to completion off the GUI thread.

    Signals
    -------
    progress(dict): ``status`` is ``"downloading"`` or ``"finished"`` with
        ``percent``/``downloaded``/``total``/``speed``/``eta``/``filename``.
    postprocess(dict): ``status`` (``"started"``/``"finished"``),
        ``postprocessor`` (e.g. ``"EmbedThumbnail"``), and ``filename``.
    finished(list): the resolved output path(s); emitted on success *and* on a
        clean stop (cancel/pause) so the queue always learns the thread ended.
    error(str): human-readable failure text (never lets the thread die silently).
    """

    progress = Signal(dict)
    postprocess = Signal(dict)
    finished = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        settings: Settings,
        job: Job,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._job = job
        self._stopped = False
        self._ydl: yt_dlp.YoutubeDL | None = None
        self._output_paths: list[str] = []
        self._current_filename: str | None = None

    # ── control (called from the GUI thread) ─────────────────────────────────
    def request_stop(self) -> None:
        """Ask the worker to abort cleanly at the next progress tick.

        The abort preserves the ``.part`` file so a later resume can continue.
        """
        self._stopped = True

    # Alias kept for the queue/plan vocabulary ("cancel() stops cleanly").
    def cancel(self) -> None:
        self.request_stop()

    @property
    def current_filename(self) -> str | None:
        """Last filename reported by yt-dlp (used to locate the ``.part`` file)."""
        return self._current_filename

    # ── hooks: run on the WORKER thread -> emit signals only ─────────────────
    def _on_progress(self, d: dict[str, Any]) -> None:
        self._check_stop()
        status = d.get("status")
        filename = d.get("filename")
        if filename:
            self._current_filename = filename

        if status == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            # GOTCHA: total_bytes may be None -> fall back to the estimate.
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            self.progress.emit(
                {
                    "status": "downloading",
                    "percent": (downloaded / total * 100.0) if total else 0.0,
                    "downloaded": downloaded,
                    "total": total,
                    "speed": d.get("speed"),
                    "eta": d.get("eta"),
                    "filename": filename,
                }
            )
        elif status == "finished":
            if filename:
                self._remember(filename)
            total = d.get("total_bytes") or d.get("downloaded_bytes") or 0
            self.progress.emit(
                {
                    "status": "finished",
                    "percent": 100.0,
                    "downloaded": d.get("downloaded_bytes") or total,
                    "total": total,
                    "speed": None,
                    "eta": 0,
                    "filename": filename,
                }
            )

    def _on_postprocess(self, d: dict[str, Any]) -> None:
        info = d.get("info_dict") or {}
        filename = info.get("filepath") or info.get("filename")
        self.postprocess.emit(
            {
                "status": d.get("status"),
                "postprocessor": d.get("postprocessor"),
                "filename": filename,
            }
        )
        if d.get("status") == "finished" and filename:
            self._remember(filename)

    # ── internals ────────────────────────────────────────────────────────────
    def _check_stop(self) -> None:
        if self._stopped:
            raise yt_dlp.utils.DownloadCancelled("cancelled by user")

    def _remember(self, path: str | None) -> None:
        if path and path not in self._output_paths:
            self._output_paths.append(path)

    def _existing_paths(self) -> list[str]:
        """Only paths that actually exist on disk (post-processed intermediates
        may have been deleted/replaced by a later postprocessor)."""
        return [p for p in self._output_paths if p and os.path.exists(p)]

    # ── thread entry point ───────────────────────────────────────────────────
    def run(self) -> None:  # noqa: D102 - documented on the class
        opts = build_ydl_opts(self._settings, self._job)
        opts["progress_hooks"] = [self._on_progress]
        opts["postprocessor_hooks"] = [self._on_postprocess]
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                self._ydl = ydl
                ydl.download([self._job.url])
        except yt_dlp.utils.DownloadCancelled:
            logger.info("download stopped (cancel/pause): %s", self._job.url)
            self.finished.emit(self._existing_paths())
            return
        except yt_dlp.utils.DownloadError as exc:
            message = str(exc)
            logger.error("download failed: %s — %s", self._job.url, message)
            self.error.emit(message)
            return
        except Exception as exc:  # noqa: BLE001 - never let the thread die silently
            logger.exception("unexpected download error for %s", self._job.url)
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        finally:
            self._ydl = None
        self.finished.emit(self._existing_paths())
