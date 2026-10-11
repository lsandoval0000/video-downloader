"""Scheduler view — CRUD over timed downloads (extra #13, leaf 6.4).

A dialog over :class:`vdl.core.scheduler.Scheduler` that lets the user schedule a
URL for a specific date/time or a daily repeat, review the pending items, and
cancel one. All scheduling state (the pure due-computation, persistence and the
30 s poll timer) lives in :mod:`vdl.core.scheduler`; this view is presentation
plus a couple of guards.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vdl.core.scheduler import (
    REPEAT_DAILY,
    REPEAT_ONCE,
    STATUS_CANCELLED,
    STATUS_FIRED,
    STATUS_MISSED,
    STATUS_PENDING,
    ScheduleItem,
    Scheduler,
)
from vdl.core.urls import extract_urls, is_probably_valid

log = logging.getLogger("vdl.ui.scheduler_view")

_EMPTY = "\u2014"
_COLUMNS: tuple[str, ...] = ("When", "Repeat", "URL", "Status")

_STATUS_LABELS: dict[str, str] = {
    STATUS_PENDING: "Scheduled",
    STATUS_FIRED: "Fired",
    STATUS_MISSED: "Missed",
    STATUS_CANCELLED: "Cancelled",
}

_REPEAT_LABELS: dict[str, str] = {REPEAT_ONCE: "Once", REPEAT_DAILY: "Daily"}


class SchedulerView(QDialog):
    """Schedule downloads for a date/time or a daily repeat."""

    def __init__(
        self,
        scheduler: Scheduler,
        parent: QWidget | None = None,
        *,
        default_urls: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scheduler")
        self.resize(720, 460)
        self._scheduler = scheduler
        self._ids: list[str] = []

        self._url = QLineEdit(self)
        self._url.setPlaceholderText("https://\u2026 (one URL)")
        if default_urls:
            self._url.setText(default_urls[0])

        self._when = QDateTimeEdit(self)
        self._when.setCalendarPopup(True)
        self._when.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._when.setDateTime(QDateTime.currentDateTime().addSecs(300))
        self._when.setMinimumDateTime(QDateTime.currentDateTime())

        self._repeat = QComboBox(self)
        for key, label in _REPEAT_LABELS.items():
            self._repeat.addItem(label, key)

        add_button = QPushButton("Schedule", self)
        add_button.clicked.connect(self._add)

        form = QHBoxLayout()
        form.addWidget(self._url, 3)
        form.addWidget(self._when, 2)
        form.addWidget(self._repeat)
        form.addWidget(add_button)

        self._table = QTableWidget(0, len(_COLUMNS), self)
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in (0, 1, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._update_actions)

        self._remove_button = QPushButton("Cancel selected", self)
        self._remove_button.clicked.connect(self._remove_selected)
        self._clear_button = QPushButton("Clear finished", self)
        self._clear_button.clicked.connect(self._clear_finished)
        close = QPushButton("Close", self)
        close.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self._remove_button)
        buttons.addWidget(self._clear_button)
        buttons.addStretch(1)
        buttons.addWidget(close)

        self._status = QLabel("", self)
        self._status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._status)
        layout.addLayout(buttons)

        scheduler.items_changed.connect(self.reload)
        self.reload()

    # ── data ─────────────────────────────────────────────────────────────────
    def reload(self) -> None:
        """Repopulate the table from the scheduler."""
        items = self._scheduler.items
        self._ids = [item.id for item in items]
        self._table.setRowCount(0)
        for item in items:
            row = self._table.rowCount()
            self._table.insertRow(row)
            values = (
                self._format_when(item.when),
                _REPEAT_LABELS.get(item.repeat, item.repeat),
                item.url or _EMPTY,
                _STATUS_LABELS.get(item.status, item.status),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column == 2:
                    cell.setToolTip(item.url)
                self._table.setItem(row, column, cell)
        pending = sum(1 for item in items if item.status == STATUS_PENDING)
        self._status.setText(f"{len(items)} item(s); {pending} pending.")
        self._update_actions()

    @staticmethod
    def _format_when(when: float) -> str:
        try:
            return datetime.fromtimestamp(float(when)).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OSError, OverflowError):
            return _EMPTY

    # ── actions ──────────────────────────────────────────────────────────────
    def _add(self) -> None:
        urls = [url for url in extract_urls(self._url.text()) if is_probably_valid(url)]
        if len(urls) != 1:
            QMessageBox.warning(
                self, "Schedule", "Enter exactly one valid http(s) URL to schedule."
            )
            return
        when = float(self._when.dateTime().toSecsSinceEpoch())
        if when <= time.time():
            QMessageBox.warning(self, "Schedule", "Choose a date/time in the future.")
            return
        item = ScheduleItem(
            when=when,
            repeat=str(self._repeat.currentData() or REPEAT_ONCE),
            job={"url": urls[0]},
        )
        self._scheduler.add(item)
        log.info("scheduled %s for %s (%s)", urls[0], self._format_when(when), item.repeat)
        self._status.setText(
            f"Scheduled {self._format_when(when)} ({_REPEAT_LABELS.get(item.repeat, item.repeat)})."
        )
        self._url.clear()

    def _current_id(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        if 0 <= index < len(self._ids):
            return self._ids[index]
        return None

    def _remove_selected(self) -> None:
        item_id = self._current_id()
        if item_id is None:
            self._status.setText("Select an item to cancel.")
            return
        if self._scheduler.remove(item_id):
            self._status.setText("Scheduled item cancelled.")

    def _clear_finished(self) -> None:
        removed = self._scheduler.clear_finished()
        if removed:
            self._status.setText(f"Cleared {removed} finished item(s).")

    def _update_actions(self) -> None:
        self._remove_button.setEnabled(self._current_id() is not None)
        has_finished = any(item.status != STATUS_PENDING for item in self._scheduler.items)
        self._clear_button.setEnabled(has_finished)
