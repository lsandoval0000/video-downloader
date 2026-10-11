"""Placeholder main window.

Branch 6 (leaf 6.1) replaces this with the real layout: a ``QSplitter`` with the
download panel, queue table and embedded player, plus a menu/toolbar and tray
icon. For now it is a bare ``QMainWindow`` so the branch-1 bootstrap has
something to show and the vertical slice runs end-to-end.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget


class MainWindow(QMainWindow):
    """Minimal placeholder window (full UI lands in branch 6)."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VideoDownloader")
        self.resize(960, 640)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        label = QLabel("VideoDownloader — scaffolding build (branch 1)", central)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        self.setCentralWidget(central)
