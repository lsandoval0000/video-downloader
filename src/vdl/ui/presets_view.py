"""Presets management view (extra #15, leaf 6.5).

A small dialog over :meth:`vdl.config.ConfigStore.list_presets` /
:meth:`~vdl.config.ConfigStore.delete_preset` that lets the user *load* a named
preset into the shared settings (repopulating every option control via the
download panel) and *delete* presets. Saving a preset from the current options
is done directly in the download panel's preset row, which owns the option
widgets; this view is the browse/manage counterpart reachable from the menu.

Loading only writes the keys a preset captured, through ``ConfigStore.set`` +
``ConfigStore.save`` — no option bypasses the store (plan leaf 6.7 rule).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
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

from vdl.config import ConfigStore

log = logging.getLogger("vdl.ui.presets_view")

_COLUMNS: tuple[str, ...] = ("Preset", "Options")


def describe_values(values: dict) -> str:
    """Render a preset's captured options as a compact ``key=value`` summary."""
    if not values:
        return "(no options)"
    return ", ".join(f"{key}={values[key]!r}" for key in sorted(values))


class PresetsView(QDialog):
    """Browse, load and delete named download presets."""

    #: Emitted (from the GUI thread) with the name of the preset to apply.
    preset_loaded = Signal(str)

    def __init__(self, config: ConfigStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Presets")
        self.resize(620, 400)
        self._config = config
        self._names: list[str] = []

        self._table = QTableWidget(0, len(_COLUMNS), self)
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._update_actions)
        self._table.cellDoubleClicked.connect(lambda _r, _c: self._load_selected())

        self._load_button = QPushButton("Load", self)
        self._load_button.clicked.connect(self._load_selected)
        self._delete_button = QPushButton("Delete", self)
        self._delete_button.clicked.connect(self._delete_selected)
        refresh = QPushButton("Refresh", self)
        refresh.clicked.connect(self.reload)
        close = QPushButton("Close", self)
        close.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self._load_button)
        buttons.addWidget(self._delete_button)
        buttons.addStretch(1)
        buttons.addWidget(refresh)
        buttons.addWidget(close)

        self._status = QLabel("", self)
        self._status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Double-click a preset to load it into the download options. "
                "To save the current options as a preset, use \u201cSave preset\u2026\u201d "
                "in the download panel.",
                self,
            )
        )
        layout.addWidget(self._table, 1)
        layout.addWidget(self._status)
        layout.addLayout(buttons)

        self.reload()

    # ── data ─────────────────────────────────────────────────────────────────
    def reload(self) -> None:
        """Repopulate the table from the store."""
        presets = self._config.list_presets()
        self._names = [preset.name for preset in presets]
        self._table.setRowCount(0)
        for preset in presets:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(preset.name))
            options = QTableWidgetItem(describe_values(preset.values))
            options.setToolTip(describe_values(preset.values))
            self._table.setItem(row, 1, options)
        self._status.setText(f"{len(presets)} preset(s).")
        self._update_actions()

    # ── actions ──────────────────────────────────────────────────────────────
    def _current_name(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        if 0 <= index < len(self._names):
            return self._names[index]
        return None

    def _load_selected(self) -> None:
        name = self._current_name()
        if name is None:
            self._status.setText("Select a preset to load.")
            return
        log.info("requested preset load: %s", name)
        self.preset_loaded.emit(name)
        self._status.setText(f"Loaded preset \u201c{name}\u201d.")

    def _delete_selected(self) -> None:
        name = self._current_name()
        if name is None:
            self._status.setText("Select a preset to delete.")
            return
        confirm = QMessageBox.question(
            self,
            "Delete preset",
            f"Delete the preset \u201c{name}\u201d?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if self._config.delete_preset(name):
            log.info("deleted preset: %s", name)
            self.reload()

    def _update_actions(self) -> None:
        has_selection = self._current_name() is not None
        self._load_button.setEnabled(has_selection)
        self._delete_button.setEnabled(has_selection)
