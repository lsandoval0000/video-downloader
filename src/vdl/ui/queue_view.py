"""Download queue table with live progress, speed, ETA and post-process stages.

Leaf 2.8 (UI half) + the queue portion of leaf 6.1. The view renders a
:class:`~vdl.core.queue.Job` per row and updates **in place** so it can keep up
with yt-dlp's multi-per-second progress callbacks; it never blocks and never
touches anything from the worker thread (it only consumes Qt signals).

Two pieces of information the plain queue discards are surfaced by
:class:`UiDownloadQueue`: the downloaded/total byte counts and the name of the
post-processor currently running (e.g. "Merging"). It does so by *extending*
:class:`~vdl.core.queue.DownloadQueue` — calling ``super()`` — and re-emitting the
extra detail, so no core code is modified and the threading contract is intact.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vdl.core.queue import TERMINAL_STATES, DownloadQueue, Job, JobState
from vdl.ui.formatting import human_bytes, human_eta, human_speed

log = logging.getLogger("vdl.ui.queue_view")

_COLUMNS: tuple[str, ...] = ("Title", "Status", "Progress", "Size", "Speed", "ETA")

_STATE_LABELS: dict[JobState, str] = {
    JobState.QUEUED: "Queued",
    JobState.RUNNING: "Downloading",
    JobState.PAUSED: "Paused",
    JobState.DONE: "Completed",
    JobState.ERROR: "Error",
    JobState.CANCELLED: "Cancelled",
}

#: yt-dlp postprocessor class names -> friendly stage labels.
_STAGE_LABELS: dict[str, str] = {
    "FFmpegMerger": "Merging",
    "Merger": "Merging",
    "FFmpegExtractAudio": "Extracting audio",
    "FFmpegVideoConvertor": "Converting video",
    "FFmpegVideoRemuxer": "Remuxing",
    "FFmpegEmbedSubtitle": "Embedding subtitles",
    "EmbedSubtitle": "Embedding subtitles",
    "EmbedThumbnail": "Embedding thumbnail",
    "FFmpegMetadata": "Writing metadata",
    "Metadata": "Writing metadata",
    "FFmpegThumbnailsConvertor": "Converting thumbnail",
    "ModifyChapters": "Applying SponsorBlock",
    "SponsorBlock": "SponsorBlock",
    "MoveFilesAfterDownload": "Finalizing",
}

_EMPTY = "\u2014"


def _stage_label(stage: str) -> str:
    return _STAGE_LABELS.get(stage, stage)


class UiDownloadQueue(DownloadQueue):
    """A :class:`DownloadQueue` that additionally reports byte counts + stages.

    ``download_progress(job, detail)`` mirrors each progress callback with the raw
    ``downloaded``/``total``/``speed``/``eta`` values; ``postprocess_stage(job,
    stage, detail)`` fires when a post-processor starts (``stage`` is the PP name)
    and again with an empty ``stage`` when it finishes. Both are emitted from the
    GUI thread (the base class already marshals worker signals there).
    """

    download_progress = Signal(object, dict)
    postprocess_stage = Signal(object, str, dict)

    def _on_progress(self, job: Job, data: dict[str, Any]) -> None:  # noqa: D102 - Qt signal slot
        super()._on_progress(job, data)
        self.download_progress.emit(job, data)

    def _on_postprocess(self, job: Job, data: dict[str, Any]) -> None:  # noqa: D102
        super()._on_postprocess(job, data)
        stage = str(data.get("postprocessor") or "")
        running = data.get("status") == "started"
        self.postprocess_stage.emit(job, stage if running else "", data)


class QueueView(QWidget):
    """A table rendering queue jobs with per-row controls.

    The view owns no download logic: pause/resume/cancel/remove are delegated to
    the :class:`~vdl.core.queue.DownloadQueue`, and the "open in player" action is
    surfaced as :attr:`play_requested` for the main window to wire to the player.
    """

    #: Emitted with a local file path when the user asks to play a finished job.
    play_requested = Signal(str)

    def __init__(self, queue: DownloadQueue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._row_ids: list[str] = []
        self._jobs: dict[str, Job] = {}
        self._details: dict[str, dict[str, Any]] = {}
        self._stages: dict[str, str] = {}

        self._table = QTableWidget(0, len(_COLUMNS), self)
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.itemSelectionChanged.connect(self._update_actions)
        self._table.cellDoubleClicked.connect(self._on_double_clicked)

        self._pause_button = QPushButton("Pause", self)
        self._pause_button.clicked.connect(self._pause_current)
        self._resume_button = QPushButton("Resume", self)
        self._resume_button.clicked.connect(self._resume_current)
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.clicked.connect(self._cancel_current)
        self._remove_button = QPushButton("Remove", self)
        self._remove_button.clicked.connect(self._remove_current)
        self._open_button = QPushButton("Open", self)
        self._open_button.clicked.connect(self._open_current)

        buttons = QHBoxLayout()
        for button in (
            self._pause_button,
            self._resume_button,
            self._cancel_button,
            self._remove_button,
            self._open_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table, 1)
        layout.addLayout(buttons)

        queue.job_added.connect(self._add_job)
        queue.job_updated.connect(self._update_job)
        queue.job_finished.connect(self._finish_job)
        progress = getattr(queue, "download_progress", None)
        if progress is not None:
            progress.connect(self._on_progress)
        stage = getattr(queue, "postprocess_stage", None)
        if stage is not None:
            stage.connect(self._on_stage)

        self._update_actions()

    # ── signal handlers ──────────────────────────────────────────────────────
    def _add_job(self, job: Job) -> None:
        if job.id in self._jobs:
            self._render(job)
            return
        self._jobs[job.id] = job
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._row_ids.append(job.id)

        title = QTableWidgetItem(job.title or job.url)
        title.setToolTip(job.url)
        self._table.setItem(row, 0, title)
        self._table.setItem(row, 1, QTableWidgetItem(_STATE_LABELS[JobState.QUEUED]))

        bar = QProgressBar(self._table)
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(True)
        self._table.setCellWidget(row, 2, bar)

        for column in (3, 4, 5):
            self._table.setItem(row, column, QTableWidgetItem(_EMPTY))
        self._render(job)
        self._update_actions()

    def _update_job(self, job: Job) -> None:
        self._jobs[job.id] = job
        self._render(job)
        self._update_actions()

    def _finish_job(self, job: Job) -> None:
        self._jobs[job.id] = job
        self._stages.pop(job.id, None)
        self._render(job)
        self._update_actions()

    def _on_progress(self, job: Job, data: dict[str, Any]) -> None:
        self._jobs[job.id] = job
        self._details[job.id] = dict(data)
        if data.get("status") == "downloading":
            self._stages.pop(job.id, None)
        self._render(job)

    def _on_stage(self, job: Job, stage: str, data: dict[str, Any]) -> None:
        self._jobs[job.id] = job
        if stage:
            self._stages[job.id] = stage
        else:
            self._stages.pop(job.id, None)
        self._render(job)

    # ── rendering ────────────────────────────────────────────────────────────
    def _render(self, job: Job) -> None:
        row = self._find_row(job.id)
        if row < 0:
            return

        title_item = self._table.item(row, 0)
        if title_item is not None:
            title_item.setText(job.title or job.url)
            title_item.setToolTip(job.url)

        status_item = self._table.item(row, 1)
        if status_item is not None:
            status_item.setText(self._status_text(job))
            if job.error:
                status_item.setToolTip(job.error)

        bar = self._table.cellWidget(row, 2)
        if isinstance(bar, QProgressBar):
            bar.setValue(max(0, min(100, int(round(job.progress)))))

        detail = self._details.get(job.id, {})
        self._set_item(row, 3, self._size_text(job, detail))
        self._set_item(
            row, 4, _EMPTY if job.state in TERMINAL_STATES else human_speed(detail.get("speed"))
        )
        self._set_item(
            row, 5, _EMPTY if job.state in TERMINAL_STATES else human_eta(detail.get("eta"))
        )

    def _size_text(self, job: Job, detail: dict[str, Any]) -> str:
        downloaded = detail.get("downloaded")
        total = detail.get("total")
        if job.state in TERMINAL_STATES and not total:
            return _EMPTY
        if downloaded is None and total is None:
            return _EMPTY
        return f"{human_bytes(downloaded)} / {human_bytes(total)}"

    def _status_text(self, job: Job) -> str:
        if job.state is JobState.RUNNING:
            stage = self._stages.get(job.id)
            if stage:
                return _stage_label(stage)
            if job.progress >= 100:
                return "Processing"
        return _STATE_LABELS[job.state]

    def _set_item(self, row: int, column: int, text: str) -> None:
        item = self._table.item(row, column)
        if item is None:
            self._table.setItem(row, column, QTableWidgetItem(text))
        else:
            item.setText(text)

    def _find_row(self, job_id: str) -> int:
        try:
            return self._row_ids.index(job_id)
        except ValueError:
            return -1

    # ── actions ──────────────────────────────────────────────────────────────
    def _current_job(self) -> Job | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        if 0 <= index < len(self._row_ids):
            return self._jobs.get(self._row_ids[index])
        return None

    def _pause_current(self) -> None:
        job = self._current_job()
        if job is not None:
            self._queue.pause(job)

    def _resume_current(self) -> None:
        job = self._current_job()
        if job is not None:
            self._queue.resume(job)

    def _cancel_current(self) -> None:
        job = self._current_job()
        if job is not None:
            self._queue.cancel(job)

    def _remove_current(self) -> None:
        job = self._current_job()
        if job is None:
            return
        self._queue.remove(job)
        self._drop_row(job.id)

    def _open_current(self) -> None:
        job = self._current_job()
        if job is None:
            return
        if job.out_path and os.path.isfile(job.out_path):
            self.play_requested.emit(job.out_path)
            return
        if job.out_path:
            folder = os.path.dirname(job.out_path)
            if os.path.isdir(folder):
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
                return
        QMessageBox.information(self, "Open", "This job has no downloadable output yet.")

    def _on_double_clicked(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._row_ids):
            job = self._jobs.get(self._row_ids[row])
            if job is not None and job.state is JobState.DONE and job.out_path:
                self.play_requested.emit(job.out_path)

    def _show_context_menu(self, position) -> None:
        job = self._current_job()
        menu = QMenu(self)
        actions = [
            ("Pause", self._pause_current, job is not None and job.state is JobState.RUNNING),
            ("Resume", self._resume_current, job is not None and job.state is JobState.PAUSED),
            (
                "Cancel",
                self._cancel_current,
                job is not None and job.state not in TERMINAL_STATES,
            ),
            ("Remove", self._remove_current, job is not None),
            (
                "Open",
                self._open_current,
                job is not None and bool(job.out_path),
            ),
        ]
        for label, slot, enabled in actions:
            action = menu.addAction(label)
            action.setEnabled(enabled)
            action.triggered.connect(slot)
        menu.exec(self._table.viewport().mapToGlobal(position))

    def _update_actions(self) -> None:
        job = self._current_job()
        self._pause_button.setEnabled(job is not None and job.state is JobState.RUNNING)
        self._resume_button.setEnabled(job is not None and job.state is JobState.PAUSED)
        self._cancel_button.setEnabled(job is not None and job.state not in TERMINAL_STATES)
        self._remove_button.setEnabled(job is not None)
        self._open_button.setEnabled(job is not None and bool(job.out_path))

    # ── helpers ──────────────────────────────────────────────────────────────
    def _drop_row(self, job_id: str) -> None:
        row = self._find_row(job_id)
        if row < 0:
            return
        self._table.removeRow(row)
        self._row_ids.pop(row)
        self._jobs.pop(job_id, None)
        self._details.pop(job_id, None)
        self._stages.pop(job_id, None)
        self._update_actions()
