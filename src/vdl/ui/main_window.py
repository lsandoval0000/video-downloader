"""Main window, layout and shell wiring (leaf 6.1).

Assembles the vertical slice: a :class:`~vdl.ui.download_panel.DownloadPanel` on
the left and, on the right, a vertical splitter holding the
:class:`~vdl.ui.queue_view.QueueView` over the embedded libmpv player. Adds the
menu bar, toolbar and a system-tray icon, and wires a finished job's
``out_path`` into the player.

Threading note: the window only consumes Qt signals from
:class:`~vdl.core.queue.DownloadQueue` / :class:`~vdl.player.widget.VideoPlayerWidget`;
the queue already marshals worker callbacks onto the GUI thread, so nothing here
touches widgets from a worker thread.

Shortcuts note: the player is created with ``shortcuts=False`` so its
window-scoped Space/←/→/F/M bindings cannot steal keystrokes from the URL box.
Equivalent shortcuts are installed here with a focus guard that suppresses them
while a text-entry widget has focus (see ``.aiw/worklog.md``).
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QPolygon,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from vdl.config import ConfigStore
from vdl.core.history import STATUS_CANCELLED, STATUS_DONE, STATUS_ERROR, HistoryStore
from vdl.core.queue import Job, JobState
from vdl.player.widget import VideoPlayerWidget
from vdl.ui.clipboard import ClipboardWatcher
from vdl.ui.download_panel import DownloadPanel
from vdl.ui.history_view import HistoryView, is_known_url, video_id_from_url
from vdl.ui.notifications import Notifier
from vdl.ui.player_bar import PlayerBar
from vdl.ui.presets_view import PresetsView
from vdl.ui.queue_view import QueueView, UiDownloadQueue
from vdl.ui.settings_dialog import SettingsDialog

log = logging.getLogger("vdl.ui.main_window")

#: Seconds moved by the Left/Right window shortcuts.
_SEEK_STEP = 5.0


def _focus_is_text_entry() -> bool:
    """``True`` when the focused widget consumes plain keystrokes as text."""
    widget = QApplication.focusWidget()
    if widget is None:
        return False
    if isinstance(widget, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)):
        return True
    return isinstance(widget, QComboBox) and widget.isEditable()


def _guard(slot):
    """Wrap ``slot`` so it never fires while a text-entry widget has focus."""

    def handler() -> None:
        if not _focus_is_text_entry():
            slot()

    return handler


def _make_icon() -> QIcon:
    """Build the application/tray icon in code (no bundled icon file required)."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2d7ff9"))
        painter.drawRoundedRect(4, 4, 56, 56, 16, 16)
        painter.setBrush(QColor("#ffffff"))
        painter.drawPolygon(QPolygon([QPoint(22, 16), QPoint(42, 16), QPoint(32, 34)]))
        painter.drawRect(20, 38, 24, 7)
    finally:
        painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    """The application's single top-level window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VideoDownloader")
        self.resize(1200, 760)

        self.config = ConfigStore().load()
        self.queue = UiDownloadQueue(self.config.settings, self)
        self.history = HistoryStore()
        self._history_view: HistoryView | None = None

        # Video fullscreen state (leaf 10.10): remembered chrome visibility and
        # splitter sizes so exiting fullscreen restores the exact prior layout.
        self._player_fullscreen = False
        self._fs_state: dict[str, bool] = {}
        self._fs_splitter_sizes: list[int] = []
        self._fs_right_splitter_sizes: list[int] = []

        self._icon = _make_icon()
        self.setWindowIcon(self._icon)

        self._build_central_widget()
        self._build_actions()
        self._build_tray()

        self.notifier = Notifier(self.tray, self.config, self)
        self.clipboard = ClipboardWatcher(
            self, enabled_getter=lambda: self.config.settings.clipboard_watch
        )

        self._install_player_shortcuts()

        self.queue.job_added.connect(self._on_job)
        self.queue.job_finished.connect(self._on_job_finished)
        self.queue_view.play_requested.connect(self._play_path)
        self.clipboard.url_detected.connect(self._on_clipboard_url)
        self._player.fullscreen_requested.connect(self._toggle_player_fullscreen)
        self.download_panel.set_known_checker(lambda url: is_known_url(self.history, url))

        self.statusBar().showMessage("Ready")
        log.info("main window ready")

    # ── layout ───────────────────────────────────────────────────────────────
    def _build_central_widget(self) -> None:
        self.download_panel = DownloadPanel(self.config, self.queue, self)

        self.queue_view = QueueView(self.queue, self)

        self._player_container = QWidget(self)
        self._player = VideoPlayerWidget(self._player_container, shortcuts=False)
        self.player_bar = PlayerBar(self._player, self._player_container)
        player_layout = QVBoxLayout(self._player_container)
        player_layout.setContentsMargins(0, 0, 0, 0)
        player_layout.setSpacing(0)
        player_layout.addWidget(self._player, 1)
        player_layout.addWidget(self.player_bar)

        self._right_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self._right_splitter.addWidget(self.queue_view)
        self._right_splitter.addWidget(self._player_container)
        self._right_splitter.setStretchFactor(0, 3)
        self._right_splitter.setStretchFactor(1, 2)

        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.addWidget(self.download_panel)
        self._splitter.addWidget(self._right_splitter)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([360, 840])
        self.setCentralWidget(self._splitter)

    # ── actions / menus / toolbar ────────────────────────────────────────────
    def _make_action(
        self,
        text: str,
        slot,
        *,
        shortcut: str | None = None,
        checkable: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        if checkable:
            action.toggled.connect(slot)
        else:
            action.triggered.connect(slot)
        return action

    def _build_actions(self) -> None:
        self.action_add_urls = self._make_action(
            "Add URLs…", self._focus_url_input, shortcut="Ctrl+N"
        )
        self.action_open_file = self._make_action("Open file…", self._open_file, shortcut="Ctrl+O")
        self.action_quit = self._make_action("Quit", self.close, shortcut="Ctrl+Q")
        self.action_toggle_player = self._make_action(
            "Show player", self._toggle_player, checkable=True
        )
        self.action_toggle_player.setChecked(True)
        self.action_reset_layout = self._make_action("Reset layout", self._reset_layout)
        self.action_history = self._make_action("Open history\u2026", self._open_history)
        self.action_presets = self._make_action("Manage presets\u2026", self._open_presets)
        self.action_settings = self._make_action(
            "Preferences\u2026", self._open_settings, shortcut="Ctrl+,"
        )
        self.action_dnd = self._make_action("Do not disturb", self._toggle_dnd, checkable=True)
        self.action_dnd.blockSignals(True)
        self.action_dnd.setChecked(not self.config.settings.notify_on_complete)
        self.action_dnd.blockSignals(False)
        self.action_notify_focused = self._make_action(
            "Notify even while focused", self._toggle_notify_focused, checkable=True
        )
        self.action_notify_focused.blockSignals(True)
        self.action_notify_focused.setChecked(True)
        self.action_notify_focused.blockSignals(False)
        self.action_about = self._make_action("About", self._about)

        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.action_add_urls)
        file_menu.addAction(self.action_open_file)
        file_menu.addSeparator()
        file_menu.addAction(self.action_quit)

        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self.action_toggle_player)
        view_menu.addAction(self.action_reset_layout)

        menu_bar.addMenu("&History").addAction(self.action_history)
        menu_bar.addMenu("&Presets").addAction(self.action_presets)

        settings_menu = menu_bar.addMenu("&Settings")
        settings_menu.addAction(self.action_settings)
        settings_menu.addSeparator()
        settings_menu.addAction(self.action_dnd)
        settings_menu.addAction(self.action_notify_focused)

        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self.action_about)

        toolbar = self.addToolBar("Main")
        self._toolbar = toolbar
        toolbar.setMovable(False)
        toolbar.addAction(self.action_add_urls)
        toolbar.addAction(self.action_open_file)
        toolbar.addSeparator()
        toolbar.addAction(self.action_history)
        toolbar.addAction(self.action_presets)
        toolbar.addAction(self.action_settings)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self._icon, self)
        self.tray.setToolTip("VideoDownloader")
        menu = QMenu(self)
        show_action = menu.addAction("Show / hide window")
        show_action.triggered.connect(self._toggle_visible)
        menu.addAction(self.action_open_file)
        menu.addSeparator()
        menu.addAction(self.action_dnd)
        menu.addSeparator()
        menu.addAction(self.action_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            log.info("system tray unavailable on this platform")

    # ── player wiring ────────────────────────────────────────────────────────
    def _install_player_shortcuts(self) -> None:
        """Window-level player shortcuts with a text-entry focus guard."""
        bindings = (
            ("Space", self._player.toggle_pause),
            ("Left", lambda: self._player.seek(-_SEEK_STEP)),
            ("Right", lambda: self._player.seek(_SEEK_STEP)),
            ("F", self._toggle_player_fullscreen),
            ("M", self._player.toggle_mute),
        )
        for sequence, slot in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(_guard(slot))

        # Esc exits the video fullscreen (leaf 10.10). Enabled only while
        # fullscreen so it never swallows Esc from other widgets otherwise.
        self._escape_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._escape_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._escape_shortcut.setEnabled(False)
        self._escape_shortcut.activated.connect(self._exit_player_fullscreen)

    def _play_path(self, path: str) -> None:
        if not path:
            return
        if not self.action_toggle_player.isChecked():
            self.action_toggle_player.setChecked(True)
            self._player_container.show()
        self._player.load(path)
        self.statusBar().showMessage(f"Playing: {os.path.basename(path)}", 5000)

    # ── slots ────────────────────────────────────────────────────────────────
    def _on_job(self, job: Job) -> None:
        self.statusBar().showMessage(f"Queued: {job.title or job.url}", 4000)

    def _on_job_finished(self, job: Job) -> None:
        if job.state is JobState.DONE:
            name = os.path.basename(job.out_path) if job.out_path else job.url
            self.statusBar().showMessage(f"Completed: {name}", 8000)
        elif job.state is JobState.ERROR:
            self.statusBar().showMessage(f"Failed: {job.error or job.url}", 8000)
        self._record_history(job)
        self._notify_job(job)

    # ── history + notifications (extras #14, #16) ────────────────────────────
    def _record_history(self, job: Job) -> None:
        """Write a history row for a terminal job (extra #14 engine contract)."""
        status = {
            JobState.DONE: STATUS_DONE,
            JobState.ERROR: STATUS_ERROR,
            JobState.CANCELLED: STATUS_CANCELLED,
        }.get(job.state)
        if status is None:
            return
        try:
            self.history.add(
                job.url,
                video_id=video_id_from_url(job.url),
                title=job.title,
                path=job.out_path,
                status=status,
            )
        except Exception:
            log.exception("could not record history for %s", job.url)
        if self._history_view is not None and self._history_view.isVisible():
            self._history_view.reload()

    def _notify_job(self, job: Job) -> None:
        """Show a tray balloon for a finished job (extra #16)."""
        if job.state is JobState.DONE:
            name = os.path.basename(job.out_path) if job.out_path else (job.title or job.url)
            path = job.out_path
            callback = (lambda p=path: self._play_path(p)) if path else None
            self.notifier.notify("Download complete", name, on_click=callback)
        elif job.state is JobState.ERROR:
            name = job.title or job.url
            detail = f"{name}\n{job.error}" if job.error else name
            self.notifier.notify("Download failed", detail, urgent=True)

    def _focus_url_input(self) -> None:
        self.download_panel.focus_input()

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open media",
            self.config.settings.download_dir or "",
            "Media files (*.mp4 *.mkv *.webm *.mp3 *.m4a *.mov *.avi);;All files (*)",
        )
        if path:
            self._play_path(path)

    def _toggle_player(self) -> None:
        visible = self.action_toggle_player.isChecked()
        self._player_container.setVisible(visible)

    def _reset_layout(self) -> None:
        self._splitter.setSizes([360, 840])
        self._right_splitter.setSizes([460, 320])

    # ── player fullscreen (leaf 10.10) ───────────────────────────────────────
    def _toggle_player_fullscreen(self) -> None:
        """Toggle a video-focused fullscreen (leaf 10.10).

        Option A: the *existing* top-level window is fullscreened while the
        surrounding chrome is hidden, so the video fills the screen and the
        transport bar (a permanent sibling inside ``_player_container``) stays
        visible and usable. No native widget is reparented, so the leaf-10.4
        native video surface (and libmpv's ``wid``) is left exactly as-is.
        """
        if self._player_fullscreen:
            self._exit_player_fullscreen()
        else:
            self._enter_player_fullscreen()

    def _enter_player_fullscreen(self) -> None:
        """Hide the surrounding chrome and fullscreen the window.

        The current chrome visibility and splitter proportions are remembered so
        :meth:`_exit_player_fullscreen` restores the prior windowed layout.
        """
        self._fs_state = {
            "menu_bar": self.menuBar().isVisible(),
            "toolbar": self._toolbar.isVisible(),
            "status_bar": self.statusBar().isVisible(),
            "download_panel": self.download_panel.isVisible(),
            "queue_view": self.queue_view.isVisible(),
            "player_container": self._player_container.isVisible(),
        }
        self._fs_splitter_sizes = self._splitter.sizes()
        self._fs_right_splitter_sizes = self._right_splitter.sizes()

        self.menuBar().setVisible(False)
        self._toolbar.setVisible(False)
        self.statusBar().setVisible(False)
        self.download_panel.setVisible(False)
        self.queue_view.setVisible(False)
        self._player_container.setVisible(True)

        self._player_fullscreen = True
        self._escape_shortcut.setEnabled(True)
        self.showFullScreen()

    def _exit_player_fullscreen(self) -> None:
        """Leave fullscreen and restore the exact prior windowed layout."""
        if not self._player_fullscreen:
            return
        self._player_fullscreen = False
        self._escape_shortcut.setEnabled(False)
        self.showNormal()

        state = self._fs_state
        self.menuBar().setVisible(state.get("menu_bar", True))
        self._toolbar.setVisible(state.get("toolbar", True))
        self.statusBar().setVisible(state.get("status_bar", True))
        self.download_panel.setVisible(state.get("download_panel", True))
        self.queue_view.setVisible(state.get("queue_view", True))
        self._player_container.setVisible(state.get("player_container", True))

        if self._fs_splitter_sizes:
            self._splitter.setSizes(self._fs_splitter_sizes)
        if self._fs_right_splitter_sizes:
            self._right_splitter.setSizes(self._fs_right_splitter_sizes)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            self.download_panel.reload_from_settings()
            self.statusBar().showMessage("Settings saved.", 4000)

    def _about(self) -> None:
        from vdl import __version__

        QMessageBox.about(
            self,
            "About VideoDownloader",
            f"VideoDownloader {__version__}\n\n"
            "A light, portable video downloader built on yt-dlp, ffmpeg and an "
            "embedded libmpv player.",
        )

    def _open_history(self) -> None:
        if self._history_view is None:
            self._history_view = HistoryView(
                self.history, self, download_dir=self.config.settings.download_dir
            )
            self._history_view.play_requested.connect(self._play_path)
        self._history_view.reload()
        self._history_view.show()
        self._history_view.raise_()
        self._history_view.activateWindow()

    def _open_presets(self) -> None:
        dialog = PresetsView(self.config, self)
        dialog.preset_loaded.connect(self.download_panel.load_preset)
        dialog.exec()
        self.download_panel.reload_from_settings()

    def _on_clipboard_url(self, url: str) -> None:
        if self.download_panel.append_url(url):
            self.download_panel.show_clipboard_hint()
            self.statusBar().showMessage("URL detected on the clipboard.", 4000)

    # ── notification toggles (extra #16) ─────────────────────────────────────
    def _toggle_dnd(self, enabled: bool) -> None:
        self.notifier.set_enabled(not enabled)
        self.statusBar().showMessage(
            "Do not disturb enabled." if enabled else "Notifications enabled.", 3000
        )

    def _toggle_notify_focused(self, enabled: bool) -> None:
        self.notifier.suppress_when_focused = not enabled

    def _toggle_visible(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_visible()

    # ── lifecycle ────────────────────────────────────────────────────────────
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        try:
            self.tray.hide()
        except Exception:  # pragma: no cover - teardown must never fail
            pass
        try:
            self.history.close()
        except Exception:  # pragma: no cover - teardown must never fail
            log.exception("could not close the history store")
        self._player.shutdown()
        super().closeEvent(event)
