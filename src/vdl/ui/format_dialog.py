"""Format/quality picker dialog (leaf 2.2, UI half).

Enumerates the downloadable formats for a URL and lets the user pick one. The
network-bound :func:`vdl.core.formats.list_formats` call **blocks**, so it runs
on a :class:`QThread` worker and only ever reports back through signals — the GUI
thread never freezes (plan leaf 2.2 / anti-pattern).

The value handed back to the caller is a yt-dlp ``format`` selector produced by
the verified :func:`vdl.core.formats.format_selector`, either from a named
preset (Best/1080p/720p/Audio-only/Smallest) or from a table row.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vdl.core.formats import FORMAT_PRESETS, FormatInfo, format_selector, list_formats
from vdl.ui.formatting import human_bytes

log = logging.getLogger("vdl.ui.format_dialog")

#: Table columns in display order.
_COLUMNS: tuple[str, ...] = (
    "ID",
    "Ext",
    "Resolution",
    "FPS",
    "Video",
    "Audio",
    "Size",
    "Note",
)

#: Named presets exposed at the top of the dialog (label shown -> preset key).
_PRESET_CHOICES: tuple[tuple[str, str], ...] = (
    ("best", "Best available"),
    ("1080p", "1080p (max)"),
    ("720p", "720p (max)"),
    ("audio", "Audio only"),
    ("smallest", "Smallest"),
)

#: Sentinel stored in the preset combo for "the user picked a table row".
_CUSTOM = "__custom__"

#: Fetchers whose dialog closed before they finished. Kept alive (detached from
#: their parent dialog) so Qt never destroys a running ``QThread``.
_ORPHAN_WORKERS: set[_FormatFetchWorker] = set()


class _FormatFetchWorker(QThread):
    """Runs :func:`list_formats` off the GUI thread and reports via signals."""

    fetched = Signal(list)
    failed = Signal(str)

    def __init__(self, url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:  # noqa: D102 - documented on the class
        try:
            formats = list_formats(self._url)
        except Exception as exc:  # noqa: BLE001 - surface any yt-dlp failure to the UI
            log.warning("format fetch failed for %s: %s", self._url, exc)
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.fetched.emit(formats)


def _selector_for(fmt: FormatInfo) -> str:
    """Build a ``format`` selector for a concrete table row.

    Reuses the verified :func:`format_selector` by handing it a minimal info
    dict built from the row's codecs, so a video-only id gets ``+bestaudio`` and
    a muxed id stays standalone — the same logic the core uses.
    """
    info = {"formats": [{"format_id": fmt.id, "vcodec": fmt.vcodec, "acodec": fmt.acodec}]}
    return format_selector(fmt.id, info)


class FormatDialog(QDialog):
    """A modal format table + preset chooser."""

    def __init__(
        self,
        url: str,
        parent: QWidget | None = None,
        *,
        selector: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select format / quality")
        self.resize(760, 460)

        self._url = url
        self._formats: list[FormatInfo] = []
        self._selector: str | None = selector
        self._worker: _FormatFetchWorker | None = None

        header = QLabel(self)
        header.setWordWrap(True)
        header.setText(f"Formats for: {url}" if url else "Formats for: (no URL)")

        self._preset = QComboBox(self)
        for key, label in _PRESET_CHOICES:
            self._preset.addItem(label, key)
        self._preset.addItem("Custom (pick a row below)", _CUSTOM)
        self._preset.currentIndexChanged.connect(self._on_preset_changed)

        self._fetch_button = QPushButton("Fetch formats", self)
        self._fetch_button.clicked.connect(self._start_fetch)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Quality:", self))
        preset_row.addWidget(self._preset)
        preset_row.addStretch(1)
        preset_row.addWidget(self._fetch_button)

        self._table = QTableWidget(0, len(_COLUMNS), self)
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.itemSelectionChanged.connect(self._on_row_selected)

        self._status = QLabel("Press \u201cFetch formats\u201d to list available formats.", self)
        self._status.setWordWrap(True)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addLayout(preset_row)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._status)
        layout.addWidget(self._buttons)

        self._sync_status()

    # ── public API ───────────────────────────────────────────────────────────
    def chosen_selector(self) -> str:
        """The yt-dlp ``format`` selector chosen by the user (never empty)."""
        if self._selector:
            return self._selector
        preset = self._preset.currentData()
        if isinstance(preset, str) and preset in FORMAT_PRESETS:
            return FORMAT_PRESETS[preset]
        return FORMAT_PRESETS["best"]

    # ── fetching ─────────────────────────────────────────────────────────────
    def _start_fetch(self) -> None:
        if not self._url:
            self._status.setText("No URL to fetch formats for.")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._fetch_button.setEnabled(False)
        self._status.setText("Fetching formats\u2026")
        worker = _FormatFetchWorker(self._url, self)
        worker.fetched.connect(self._on_fetched)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _on_fetched(self, formats: list[FormatInfo]) -> None:
        self._formats = list(formats)
        self._table.setRowCount(0)
        for fmt in self._formats:
            row = self._table.rowCount()
            self._table.insertRow(row)
            values = (
                fmt.id,
                fmt.ext or "",
                fmt.resolution or "",
                "" if fmt.fps is None else f"{fmt.fps:g}",
                fmt.vcodec or "",
                fmt.acodec or "",
                self._format_size(fmt.filesize),
                fmt.note or "",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                self._table.setItem(row, column, item)
        if self._formats:
            self._status.setText(f"{len(self._formats)} format(s) found. Select a row.")
        else:
            self._status.setText("No downloadable formats were reported for this URL.")

    def _on_failed(self, message: str) -> None:
        self._status.setText(f"Could not fetch formats: {message}")

    def _on_worker_finished(self) -> None:
        self._fetch_button.setEnabled(True)
        self._worker = None

    @staticmethod
    def _format_size(size: int | None) -> str:
        return human_bytes(size)

    # ── selection ────────────────────────────────────────────────────────────
    def _on_preset_changed(self, _index: int) -> None:
        preset = self._preset.currentData()
        if isinstance(preset, str) and preset in FORMAT_PRESETS:
            self._selector = FORMAT_PRESETS[preset]
            self._table.clearSelection()
        self._sync_status()

    def _on_row_selected(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        index = rows[0].row()
        if 0 <= index < len(self._formats):
            self._selector = _selector_for(self._formats[index])
            self._preset.blockSignals(True)
            self._preset.setCurrentIndex(self._preset.findData(_CUSTOM))
            self._preset.blockSignals(False)
        self._sync_status()

    def _sync_status(self) -> None:
        self._status.setToolTip("")
        current = self._selector or FORMAT_PRESETS["best"]
        self._status.setText(f"Selected format selector: {current}")

    # ── lifecycle ────────────────────────────────────────────────────────────
    def _detach_worker(self) -> None:
        """Re-parent a still-running worker so dialog teardown can't kill it."""
        worker = self._worker
        if worker is None or not worker.isRunning():
            return
        for signal in (worker.fetched, worker.failed, worker.finished):
            signal.disconnect()
        worker.setParent(None)
        _ORPHAN_WORKERS.add(worker)
        worker.finished.connect(lambda w=worker: _ORPHAN_WORKERS.discard(w))
        log.info("format fetch still running; detached worker from closing dialog")
        self._worker = None

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._detach_worker()
        super().closeEvent(event)

    def done(self, result: int) -> None:  # noqa: D102 - Qt override
        self._detach_worker()
        super().done(result)
