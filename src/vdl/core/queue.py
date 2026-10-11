"""Download queue with pause / resume / cancel (extra #5).

:class:`DownloadQueue` is a thin, Qt-aware scheduler over
:class:`~vdl.core.engine.DownloadWorker`. It enforces ``settings.max_concurrent``
and exposes pause/resume/cancel with yt-dlp's "no true pause" reality in mind:

* **pause** stops the worker at the next tick and *keeps* the ``.part`` file
  (resume re-downloads with continue semantics, so it picks up where it left
  off);
* **cancel** stops the worker and *deletes* the ``.part`` file.

The worker never deletes anything; the queue owns that decision.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal

from vdl.core.engine import DownloadWorker

if TYPE_CHECKING:
    from vdl.config import Settings

logger = logging.getLogger("vdl.core.queue")


class JobState(Enum):
    """Lifecycle of a queued download."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


#: States from which a job never transitions again.
TERMINAL_STATES = frozenset({JobState.DONE, JobState.ERROR, JobState.CANCELLED})


@dataclass
class Job:
    """One queued download (per plan blueprint + per-job overrides)."""

    id: str
    url: str
    title: str = ""
    state: JobState = JobState.QUEUED
    progress: float = 0.0
    speed: float | None = None
    eta: int | None = None
    out_path: str | None = None
    error: str | None = None
    # Per-job overrides driven by the format picker / playlist controls.
    format_selector: str | None = None
    noplaylist: bool = False
    extract_flat: bool = False


class DownloadQueue(QObject):
    """Schedules :class:`Job`\\ s onto workers, honouring ``max_concurrent``.

    Signals
    -------
    job_added(Job): a new job entered the queue.
    job_updated(Job): a job's state/progress changed (render in place).
    job_finished(Job): a job reached a terminal state (done/error/cancelled).
    """

    job_added = Signal(object)
    job_updated = Signal(object)
    job_finished = Signal(object)

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._jobs: list[Job] = []
        self._workers: dict[str, DownloadWorker] = {}
        self._part_hints: dict[str, str] = {}

    # ── queries ──────────────────────────────────────────────────────────────
    @property
    def jobs(self) -> list[Job]:
        """A snapshot copy of the current jobs (insertion order)."""
        return list(self._jobs)

    @property
    def max_concurrent(self) -> int:
        return max(1, int(self._settings.max_concurrent))

    def running_count(self) -> int:
        return sum(1 for worker in self._workers.values() if worker.isRunning())

    # ── queue management ─────────────────────────────────────────────────────
    def add(self, url: str, *, title: str = "", **overrides: Any) -> Job:
        """Create a job for ``url``, enqueue it, and start work if a slot is free."""
        job = Job(id=uuid.uuid4().hex, url=url, title=title, **overrides)
        self._jobs.append(job)
        self.job_added.emit(job)
        self.start_next()
        return job

    def remove(self, job: Job) -> None:
        """Cancel a job (if active) and drop it from the queue."""
        self.cancel(job)
        if job in self._jobs:
            self._jobs.remove(job)

    def start_next(self) -> None:
        """Start queued jobs until ``max_concurrent`` are running."""
        while self.running_count() < self.max_concurrent:
            job = self._next_queued()
            if job is None:
                break
            self._start(job)

    def _next_queued(self) -> Job | None:
        for job in self._jobs:
            # A job whose previous worker is still winding down is not eligible
            # yet; its finish handler will re-drive start_next().
            if job.state is JobState.QUEUED and job.id not in self._workers:
                return job
        return None

    def _start(self, job: Job) -> None:
        if job.id in self._workers:
            return
        job.state = JobState.RUNNING
        job.error = None
        worker = DownloadWorker(self._settings, job, parent=self)
        worker.progress.connect(lambda d, j=job: self._on_progress(j, d))
        worker.postprocess.connect(lambda d, j=job: self._on_postprocess(j, d))
        worker.finished.connect(lambda paths, j=job: self._on_finished(j, paths))
        worker.error.connect(lambda msg, j=job: self._on_error(j, msg))
        self._workers[job.id] = worker
        self.job_updated.emit(job)
        worker.start()

    # ── pause / resume / cancel ──────────────────────────────────────────────
    def pause(self, job: Job) -> None:
        """Stop the active job, keeping its ``.part`` file for a later resume."""
        if job.state is not JobState.RUNNING:
            return
        job.state = JobState.PAUSED
        self.job_updated.emit(job)
        worker = self._workers.get(job.id)
        if worker is not None:
            worker.request_stop()  # NEVER deletes the .part file

    def resume(self, job: Job) -> None:
        """Re-queue a paused job; yt-dlp continues from the retained ``.part``."""
        if job.state is not JobState.PAUSED:
            return
        job.state = JobState.QUEUED
        self.job_updated.emit(job)
        self.start_next()

    def cancel(self, job: Job) -> None:
        """Stop the job and delete its partial file (only cancel does this)."""
        if job.state in TERMINAL_STATES:
            return
        job.state = JobState.CANCELLED
        self.job_updated.emit(job)
        worker = self._workers.get(job.id)
        if worker is not None:
            worker.request_stop()
            # The worker's finish handler deletes the .part once it stops.
        else:
            self._delete_part_files(job)
            self.job_finished.emit(job)
            self.start_next()

    # ── worker signal handlers (GUI thread) ──────────────────────────────────
    def _on_progress(self, job: Job, data: dict[str, Any]) -> None:
        percent = data.get("percent")
        if percent is not None:
            job.progress = float(percent)
        job.speed = data.get("speed")
        job.eta = data.get("eta")
        if data.get("filename"):
            self._part_hints[job.id] = data["filename"]
        self.job_updated.emit(job)

    def _on_postprocess(self, job: Job, data: dict[str, Any]) -> None:
        # The UI renders the stage; nothing to persist here beyond notifying.
        self.job_updated.emit(job)

    def _on_finished(self, job: Job, paths: list[str]) -> None:
        self._workers.pop(job.id, None)
        if job.state is JobState.PAUSED:
            self.job_updated.emit(job)
        elif job.state is JobState.CANCELLED:
            self._delete_part_files(job)
            self.job_finished.emit(job)
        else:
            job.state = JobState.DONE
            job.progress = 100.0
            if paths:
                job.out_path = paths[-1]
            self.job_finished.emit(job)
        self.start_next()

    def _on_error(self, job: Job, message: str) -> None:
        self._workers.pop(job.id, None)
        job.state = JobState.ERROR
        job.error = message
        self.job_finished.emit(job)
        self.start_next()

    # ── helpers ──────────────────────────────────────────────────────────────
    def _delete_part_files(self, job: Job) -> None:
        hint = self._part_hints.pop(job.id, None)
        if not hint:
            return
        for candidate in (hint, hint + ".part", hint + ".ytdl"):
            try:
                if os.path.isfile(candidate):
                    os.remove(candidate)
                    logger.info("cancel: removed partial file %s", candidate)
            except OSError as exc:  # pragma: no cover - best effort cleanup
                logger.warning("cancel: could not remove %s (%s)", candidate, exc)
