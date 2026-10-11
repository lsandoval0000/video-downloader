"""History browse view over the SQLite index (extra #14, leaf 6.6).

Lists past downloads (title, site, quality, size, date, status) from
:class:`~vdl.core.history.HistoryStore` and lets the user re-open a row in the
embedded player, reveal its folder, or clear the whole history.

The engine-side index is deliberately thin (id/video_id/title/url/path/status/
timestamp); *site* and *quality* are derived best-effort from the URL host and
the output file name, and *size* from the file on disk — nothing is fabricated,
unknown columns render as an em dash.

The module also exposes :func:`video_id_from_url` and :func:`is_known_url`, the
pure helpers the download panel uses to show the "already downloaded" state when
a URL is pasted again (the archive + index are both consulted).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vdl.core.history import (
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_SKIPPED,
    HistoryRecord,
    HistoryStore,
    is_in_archive,
)
from vdl.ui.formatting import human_bytes

log = logging.getLogger("vdl.ui.history_view")

_EMPTY = "\u2014"

_COLUMNS: tuple[str, ...] = ("Title", "Site", "Quality", "Size", "Date", "Status")

_STATUS_LABELS: dict[str, str] = {
    STATUS_DONE: "Completed",
    STATUS_ERROR: "Failed",
    STATUS_SKIPPED: "Skipped",
    "cancelled": "Cancelled",
}

#: yt-dlp-style quality token embedded in a file name, e.g. "… 1080p …".
_QUALITY_RE = re.compile(r"(\d{3,4})p", re.IGNORECASE)
_AUDIO_EXTS = frozenset({".mp3", ".m4a", ".opus", ".ogg", ".flac", ".wav", ".aac"})

#: The common YouTube URL shapes whose 11-char id can be recovered offline.
_YT_ID_RE = re.compile(
    r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/|/v/)([A-Za-z0-9_-]{11})",
    re.IGNORECASE,
)


# ── pure helpers ─────────────────────────────────────────────────────────────


def video_id_from_url(url: str | None) -> str | None:
    """Best-effort, offline extraction of a YouTube video id from ``url``."""
    if not url:
        return None
    match = _YT_ID_RE.search(url)
    return match.group(1) if match else None


def site_from_url(url: str | None) -> str:
    """Return the bare host of ``url`` (``"www."`` stripped), or ``""``."""
    if not url:
        return ""
    try:
        authority = url.split("://", 1)[-1]
        authority = authority.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
        host = authority.rsplit("@", 1)[-1].split(":", 1)[0]
    except (IndexError, ValueError):
        return ""
    return host[4:] if host.startswith("www.") else host


def quality_from_path(path: str | None) -> str:
    """Derive a quality label from an output file name (resolution or "Audio")."""
    if not path:
        return _EMPTY
    name = os.path.basename(path)
    match = _QUALITY_RE.search(name)
    if match:
        return f"{match.group(1)}p"
    if os.path.splitext(path)[1].lower() in _AUDIO_EXTS:
        return "Audio"
    return _EMPTY


def size_from_path(path: str | None) -> str:
    """Human-readable size of ``path`` on disk, or an em dash if it is missing."""
    if not path:
        return _EMPTY
    try:
        if os.path.isfile(path):
            return human_bytes(os.path.getsize(path))
    except OSError:
        pass
    return _EMPTY


def format_timestamp(timestamp: float | None) -> str:
    """Format a POSIX timestamp as local ``YYYY-MM-DD HH:MM``."""
    if timestamp is None:
        return _EMPTY
    try:
        return datetime.fromtimestamp(float(timestamp)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return _EMPTY


def is_known_url(store: HistoryStore, url: str | None) -> bool:
    """``True`` when ``url`` was already downloaded (index or yt-dlp archive).

    Uses the offline YouTube-id extraction when possible, then falls back to an
    exact-URL match against the completed history rows.
    """
    if not url:
        return False
    video_id = video_id_from_url(url)
    if video_id and (store.was_downloaded(video_id) or is_in_archive(video_id)):
        return True
    try:
        return any(record.url == url and record.status == STATUS_DONE for record in store.items())
    except Exception:  # pragma: no cover - a lookup must never crash the UI
        log.exception("history lookup failed for %s", url)
        return False


def _status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status or _EMPTY)


# ── view ─────────────────────────────────────────────────────────────────────


class HistoryView(QDialog):
    """A non-modal table of past downloads, wired to the embedded player."""

    #: Emitted with a local file path when the user asks to replay a row.
    play_requested = Signal(str)

    def __init__(
        self,
        store: HistoryStore,
        parent: QWidget | None = None,
        *,
        download_dir: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("History")
        self.resize(820, 480)
        self._store = store
        self._download_dir = download_dir
        self._records: list[HistoryRecord] = []

        self._table = QTableWidget(0, len(_COLUMNS), self)
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._update_actions)
        self._table.cellDoubleClicked.connect(self._on_double_clicked)

        self._play_button = QPushButton("Open in player", self)
        self._play_button.clicked.connect(self._open_selected)
        self._folder_button = QPushButton("Open folder", self)
        self._folder_button.clicked.connect(self._open_folder)
        self._refresh_button = QPushButton("Refresh", self)
        self._refresh_button.clicked.connect(self.reload)
        self._clear_button = QPushButton("Clear history", self)
        self._clear_button.clicked.connect(self._clear)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addWidget(self._play_button)
        buttons.addWidget(self._folder_button)
        buttons.addWidget(self._refresh_button)
        buttons.addWidget(self._clear_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)

        self._status = QLabel("", self)
        self._status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._status)
        layout.addLayout(buttons)

        self.reload()

    # ── data ─────────────────────────────────────────────────────────────────
    def reload(self) -> None:
        """Reload every row from the store (newest first)."""
        try:
            self._records = self._store.items()
        except Exception:  # pragma: no cover - a read must never crash the view
            log.exception("could not read history")
            self._records = []
        self._table.setRowCount(0)
        for record in self._records:
            row = self._table.rowCount()
            self._table.insertRow(row)
            values = (
                record.title or record.url,
                site_from_url(record.url),
                quality_from_path(record.path),
                size_from_path(record.path),
                format_timestamp(record.timestamp),
                _status_label(record.status),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setToolTip(record.url)
                self._table.setItem(row, column, item)
        self._status.setText(f"{len(self._records)} record(s).")
        self._update_actions()

    # ── actions ──────────────────────────────────────────────────────────────
    def _current(self) -> HistoryRecord | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        if 0 <= index < len(self._records):
            return self._records[index]
        return None

    def _open_selected(self) -> None:
        record = self._current()
        if record is None:
            return
        if record.path and os.path.isfile(record.path):
            self.play_requested.emit(record.path)
            return
        QMessageBox.information(
            self, "Open in player", "The file for this entry is no longer on disk."
        )

    def _open_folder(self) -> None:
        record = self._current()
        target = ""
        if record is not None and record.path:
            target = record.path if os.path.isdir(record.path) else os.path.dirname(record.path)
        if not target or not os.path.isdir(target):
            target = self._download_dir
        if not target or not os.path.isdir(target):
            QMessageBox.information(
                self, "Open folder", "The download folder is not available yet."
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _clear(self) -> None:
        if not self._records:
            return
        confirm = QMessageBox.question(
            self,
            "Clear history",
            "Remove every history entry? This does not delete the downloaded files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = self._store.clear()
        except Exception:  # pragma: no cover
            log.exception("could not clear history")
            return
        log.info("history cleared (%d row(s))", removed)
        self.reload()

    def _on_double_clicked(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._records):
            self._table.selectRow(row)
            self._open_selected()

    def _update_actions(self) -> None:
        record = self._current()
        playable = record is not None and bool(record.path) and os.path.isfile(record.path or "")
        self._play_button.setEnabled(playable)
        self._folder_button.setEnabled(record is not None or bool(self._download_dir))
        self._clear_button.setEnabled(bool(self._records))
