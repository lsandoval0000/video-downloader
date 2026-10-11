"""Settings dialog (leaf 6.7).

Edits the full :class:`~vdl.config.Settings` surface in a small tabbed form and
persists through :meth:`vdl.config.ConfigStore.save` — no option is ever written
to disk any other way (plan leaf 6.7). Because the dialog mutates the *shared*
``Settings`` instance held by the queue, a changed download directory (or any
other option) takes effect for the next job with no extra plumbing.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vdl.config import ConfigStore
from vdl.core.cookies import browser_choices
from vdl.core.formats import FORMAT_PRESETS
from vdl.core.options import CONVERTIBLE_VIDEO_EXTS
from vdl.paths import is_portable, user_data_dir

log = logging.getLogger("vdl.ui.settings_dialog")

_AUDIO_CODECS: tuple[str, ...] = ("mp3", "m4a")


def _split_list(text: str) -> list[str]:
    """Parse a comma/semicolon separated list into trimmed non-empty items."""
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]


class SettingsDialog(QDialog):
    """A modal editor over :class:`~vdl.config.Settings`."""

    def __init__(self, store: ConfigStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("Settings")
        self.resize(560, 520)

        settings = store.settings
        tabs = QTabWidget(self)
        tabs.addTab(self._build_downloads_tab(settings), "Downloads")
        tabs.addTab(self._build_processing_tab(settings), "Processing")
        tabs.addTab(self._build_network_tab(settings), "Network & access")
        tabs.addTab(self._build_behaviour_tab(settings), "Behaviour")

        mode = "Portable" if is_portable() else "Installed"
        self._portable = QLabel(f"Mode: {mode}  \u00b7  Data directory: {user_data_dir()}", self)
        self._portable.setWordWrap(True)
        self._portable.setObjectName("portableIndicator")
        open_data = QPushButton("Open data folder", self)
        open_data.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(user_data_dir())))
        )

        portable_row = QHBoxLayout()
        portable_row.addWidget(self._portable, 1)
        portable_row.addWidget(open_data)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs, 1)
        layout.addLayout(portable_row)
        layout.addWidget(buttons)

    # ── tabs ─────────────────────────────────────────────────────────────────
    def _build_downloads_tab(self, settings) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)

        self._download_dir = QLineEdit(settings.download_dir, page)
        self._download_dir.setPlaceholderText("Leave empty to use the default (app) folder")
        browse = QPushButton("Browse\u2026", page)
        browse.clicked.connect(self._browse_download_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self._download_dir, 1)
        dir_row.addWidget(browse)
        form.addRow("Download directory", dir_row)

        self._max_concurrent = QSpinBox(page)
        self._max_concurrent.setRange(1, 16)
        self._max_concurrent.setValue(max(1, int(settings.max_concurrent)))
        form.addRow("Max concurrent downloads", self._max_concurrent)

        self._format_preset = QComboBox(page)
        for key in FORMAT_PRESETS:
            self._format_preset.addItem(key, key)
        self._format_preset.setCurrentIndex(
            max(0, self._format_preset.findData(settings.default_format_preset))
        )
        form.addRow("Default quality preset", self._format_preset)

        self._playlist_items = QLineEdit(settings.playlist_items or "", page)
        self._playlist_items.setPlaceholderText("e.g. 1-10 (leave empty for all)")
        form.addRow("Playlist items", self._playlist_items)

        return page

    def _build_processing_tab(self, settings) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)

        self._audio_only = QCheckBox("Audio only", page)
        self._audio_only.setChecked(settings.audio_only)
        form.addRow("Audio extraction", self._audio_only)

        self._audio_codec = QComboBox(page)
        for codec in _AUDIO_CODECS:
            self._audio_codec.addItem(codec, codec)
        self._audio_codec.setCurrentIndex(max(0, self._audio_codec.findData(settings.audio_codec)))
        form.addRow("Audio codec", self._audio_codec)

        self._container = QComboBox(page)
        self._container.addItem("(keep source)", None)
        for ext in sorted(CONVERTIBLE_VIDEO_EXTS):
            self._container.addItem(ext, ext)
        self._container.setCurrentIndex(max(0, self._container.findData(settings.video_container)))
        form.addRow("Video container", self._container)

        self._remux = QCheckBox("Remux (stream-copy, fast) instead of re-encode", page)
        self._remux.setChecked(settings.video_remux)
        form.addRow("Conversion", self._remux)

        self._write_subs = QCheckBox("Write subtitle files", page)
        self._write_subs.setChecked(settings.write_subs)
        form.addRow("Subtitles", self._write_subs)

        self._embed_subs = QCheckBox("Embed subtitles in the container", page)
        self._embed_subs.setChecked(settings.embed_subs)
        form.addRow("", self._embed_subs)

        self._sub_langs = QLineEdit(", ".join(settings.sub_langs), page)
        self._sub_langs.setPlaceholderText("en, es, all")
        form.addRow("Subtitle languages", self._sub_langs)

        self._embed_thumbnail = QCheckBox("Embed thumbnail", page)
        self._embed_thumbnail.setChecked(settings.embed_thumbnail)
        form.addRow("Thumbnail", self._embed_thumbnail)

        self._convert_thumbnail = QCheckBox("Convert thumbnail to jpg first", page)
        self._convert_thumbnail.setChecked(settings.convert_thumbnail)
        form.addRow("", self._convert_thumbnail)

        self._embed_metadata = QCheckBox("Embed metadata", page)
        self._embed_metadata.setChecked(settings.embed_metadata)
        form.addRow("Metadata", self._embed_metadata)

        self._sponsorblock = QCheckBox("Remove sponsor segments", page)
        self._sponsorblock.setChecked(settings.sponsorblock_enabled)
        form.addRow("SponsorBlock", self._sponsorblock)

        self._sponsor_categories = QLineEdit(", ".join(settings.sponsorblock_categories), page)
        self._sponsor_categories.setPlaceholderText("sponsor, selfpromo")
        form.addRow("SponsorBlock categories", self._sponsor_categories)

        return page

    def _build_network_tab(self, settings) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)

        self._proxy = QLineEdit(settings.proxy or "", page)
        self._proxy.setPlaceholderText("e.g. socks5://127.0.0.1:1080")
        form.addRow("Proxy", self._proxy)

        self._js_runtime = QCheckBox("Enable bundled deno JS runtime (YouTube)", page)
        self._js_runtime.setChecked(settings.js_runtime_enabled)
        form.addRow("JS runtime", self._js_runtime)

        self._use_cookies = QCheckBox("Import cookies from a browser", page)
        self._use_cookies.setChecked(settings.use_cookies)
        form.addRow("Cookies", self._use_cookies)

        self._cookie_browser = QComboBox(page)
        self._cookie_browser.addItem("(none)", None)
        for browser in browser_choices():
            self._cookie_browser.addItem(browser, browser)
        self._cookie_browser.setCurrentIndex(
            max(0, self._cookie_browser.findData(settings.cookie_browser))
        )
        form.addRow("Cookie browser", self._cookie_browser)

        self._cookie_file = QLineEdit(settings.cookie_file or "", page)
        self._cookie_file.setPlaceholderText("Optional cookies.txt path")
        cookie_browse = QPushButton("Browse\u2026", page)
        cookie_browse.clicked.connect(self._browse_cookie_file)
        cookie_row = QHBoxLayout()
        cookie_row.addWidget(self._cookie_file, 1)
        cookie_row.addWidget(cookie_browse)
        form.addRow("Cookie file", cookie_row)

        return page

    def _build_behaviour_tab(self, settings) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)

        self._notify = QCheckBox("Notify when a download finishes", page)
        self._notify.setChecked(settings.notify_on_complete)
        form.addRow("Notifications", self._notify)

        self._clipboard = QCheckBox("Watch the clipboard for video URLs", page)
        self._clipboard.setChecked(settings.clipboard_watch)
        form.addRow("Clipboard", self._clipboard)

        return page

    # ── actions ──────────────────────────────────────────────────────────────
    def _browse_download_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose download directory")
        if directory:
            self._download_dir.setText(directory)

    def _browse_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose cookies.txt", "", "Cookie files (*.txt);;All files (*)"
        )
        if path:
            self._cookie_file.setText(path)

    def _accept(self) -> None:
        self._apply()
        self.accept()

    def _apply(self) -> None:
        """Write every widget value back into the shared ``Settings`` and save."""
        settings = self._store.settings
        settings.download_dir = self._download_dir.text().strip()
        settings.max_concurrent = max(1, int(self._max_concurrent.value()))
        settings.default_format_preset = self._format_preset.currentData() or "best"
        settings.playlist_items = self._playlist_items.text().strip() or None

        settings.audio_only = self._audio_only.isChecked()
        settings.audio_codec = self._audio_codec.currentData() or "mp3"
        settings.video_container = self._container.currentData()
        settings.video_remux = self._remux.isChecked()
        settings.write_subs = self._write_subs.isChecked()
        settings.embed_subs = self._embed_subs.isChecked()
        settings.sub_langs = _split_list(self._sub_langs.text()) or ["en"]
        settings.embed_thumbnail = self._embed_thumbnail.isChecked()
        settings.convert_thumbnail = self._convert_thumbnail.isChecked()
        settings.embed_metadata = self._embed_metadata.isChecked()
        settings.sponsorblock_enabled = self._sponsorblock.isChecked()
        settings.sponsorblock_categories = _split_list(self._sponsor_categories.text()) or [
            "sponsor",
            "selfpromo",
        ]

        settings.proxy = self._proxy.text().strip() or None
        settings.js_runtime_enabled = self._js_runtime.isChecked()
        settings.use_cookies = self._use_cookies.isChecked()
        settings.cookie_browser = self._cookie_browser.currentData()
        settings.cookie_file = self._cookie_file.text().strip() or None

        settings.notify_on_complete = self._notify.isChecked()
        settings.clipboard_watch = self._clipboard.isChecked()

        self._store.save()
        log.info("settings saved to %s", self._store.path)
