"""Download panel: multi-URL input + per-download options (part of leaf 6.1).

Collects one or more URLs (batch input, extra #4), lets the user pick a quality
preset or a concrete format from :class:`~vdl.ui.format_dialog.FormatDialog`
(extra #1), and enqueues each URL on the shared
:class:`~vdl.core.queue.DownloadQueue`.

Download options that the queue reads from the *shared* ``Settings`` (container,
subtitles, thumbnails, SponsorBlock, cookies, playlist range) are edited here and
persisted through :meth:`vdl.config.ConfigStore.save`, so they apply to every
subsequent job. The per-job format selector and playlist toggle are passed as
job overrides, exactly as the queue's ``add()`` API intends.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vdl.config import ConfigStore, Preset
from vdl.core.cookies import browser_choices
from vdl.core.formats import FORMAT_PRESETS
from vdl.core.options import CONVERTIBLE_VIDEO_EXTS
from vdl.core.queue import DownloadQueue
from vdl.core.urls import extract_urls, is_probably_valid
from vdl.paths import user_data_dir
from vdl.ui.format_dialog import FormatDialog

log = logging.getLogger("vdl.ui.download_panel")

_DEFAULT = "__default__"
_CUSTOM = "__custom__"

#: Format combo entries (label shown -> preset key or sentinel).
_FORMAT_CHOICES: tuple[tuple[str, str], ...] = (
    ("Default (from settings)", _DEFAULT),
    ("Best available", "best"),
    ("1080p", "1080p"),
    ("720p", "720p"),
    ("Audio only", "audio"),
    ("Smallest", "smallest"),
    ("Custom\u2026", _CUSTOM),
)

#: Settings keys a named preset captures from this panel.
_PRESET_KEYS: tuple[str, ...] = (
    "default_format_preset",
    "audio_only",
    "video_container",
    "video_remux",
    "write_subs",
    "embed_subs",
    "embed_thumbnail",
    "convert_thumbnail",
    "embed_metadata",
    "sponsorblock_enabled",
    "use_cookies",
    "cookie_browser",
    "playlist_items",
)


class DownloadPanel(QWidget):
    """The left-hand URL + options panel."""

    #: Emitted after options are written+persisted (views may refresh).
    settings_changed = Signal()

    def __init__(
        self,
        config: ConfigStore,
        queue: DownloadQueue,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._queue = queue
        self._loading = False
        self._format_key = _DEFAULT
        self._custom_selector: str | None = None
        #: Optional predicate: "has this URL already been downloaded?" (extra #14).
        self._known_checker: Callable[[str], bool] | None = None
        self._known_timer = QTimer(self)
        self._known_timer.setSingleShot(True)
        self._known_timer.setInterval(350)
        self._known_timer.timeout.connect(self._check_known)

        self._build_url_group()
        self._build_format_group()
        self._build_options_group()
        self._build_playlist_group()
        self._build_preset_row()

        self._download_button = QPushButton("Download", self)
        self._download_button.setDefault(True)
        self._download_button.clicked.connect(self._on_download)
        open_folder = QPushButton("Open downloads folder", self)
        open_folder.clicked.connect(self._open_downloads_folder)

        actions = QHBoxLayout()
        actions.addWidget(self._download_button, 1)
        actions.addWidget(open_folder)

        self._status = QLabel("", self)
        self._status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self._urls_group, 2)
        layout.addWidget(self._format_group)
        layout.addWidget(self._options_group)
        layout.addWidget(self._playlist_group)
        layout.addLayout(self._preset_row)
        layout.addLayout(actions)
        layout.addWidget(self._status)
        layout.addStretch(1)
        self.setMinimumWidth(320)

        self._reload_from_settings()

    # ── construction ─────────────────────────────────────────────────────────
    def _build_url_group(self) -> None:
        self._urls_group = QGroupBox("URLs (one per line)", self)
        self._urls = QPlainTextEdit(self._urls_group)
        self._urls.setPlaceholderText("https://\u2026\nhttps://\u2026")
        self._urls.setMinimumHeight(90)
        self._urls.textChanged.connect(self._on_urls_changed)
        self._hint = QLabel("", self._urls_group)
        self._hint.setWordWrap(True)
        self._hint.setObjectName("subtleHint")
        layout = QVBoxLayout(self._urls_group)
        layout.addWidget(self._urls)
        layout.addWidget(self._hint)

    def _build_format_group(self) -> None:
        self._format_group = QGroupBox("Quality", self)
        self._format = QComboBox(self._format_group)
        for label, key in _FORMAT_CHOICES:
            self._format.addItem(label, key)
        self._format.currentIndexChanged.connect(self._on_format_changed)
        fetch = QPushButton("Fetch formats\u2026", self._format_group)
        fetch.clicked.connect(self._prompt_custom_format)
        self._selector_label = QLabel("", self._format_group)
        self._selector_label.setWordWrap(True)

        row = QHBoxLayout()
        row.addWidget(self._format, 1)
        row.addWidget(fetch)
        layout = QVBoxLayout(self._format_group)
        layout.addLayout(row)
        layout.addWidget(self._selector_label)

    def _build_options_group(self) -> None:
        self._options_group = QGroupBox("Download options", self)
        form = QFormLayout(self._options_group)

        self._container = QComboBox(self._options_group)
        self._container.addItem("(keep source)", None)
        for ext in sorted(CONVERTIBLE_VIDEO_EXTS):
            self._container.addItem(ext, ext)
        self._container.currentIndexChanged.connect(self._apply_to_settings)
        form.addRow("Container", self._container)

        self._remux = QCheckBox("Remux only (no re-encode)", self._options_group)
        self._remux.toggled.connect(self._apply_to_settings)
        form.addRow("", self._remux)

        self._write_subs = QCheckBox("Write subtitle files", self._options_group)
        self._write_subs.toggled.connect(self._apply_to_settings)
        form.addRow("Subtitles", self._write_subs)

        self._embed_subs = QCheckBox("Embed subtitles", self._options_group)
        self._embed_subs.toggled.connect(self._apply_to_settings)
        form.addRow("", self._embed_subs)

        self._embed_thumbnail = QCheckBox("Embed thumbnail", self._options_group)
        self._embed_thumbnail.toggled.connect(self._apply_to_settings)
        form.addRow("Thumbnail", self._embed_thumbnail)

        self._embed_metadata = QCheckBox("Embed metadata", self._options_group)
        self._embed_metadata.toggled.connect(self._apply_to_settings)
        form.addRow("", self._embed_metadata)

        self._sponsorblock = QCheckBox("Remove sponsor segments", self._options_group)
        self._sponsorblock.toggled.connect(self._apply_to_settings)
        form.addRow("SponsorBlock", self._sponsorblock)

        cookie_row = QHBoxLayout()
        self._use_cookies = QCheckBox("Use cookies", self._options_group)
        self._use_cookies.toggled.connect(self._apply_to_settings)
        self._cookie_browser = QComboBox(self._options_group)
        self._cookie_browser.addItem("(none)", None)
        for browser in browser_choices():
            self._cookie_browser.addItem(browser, browser)
        self._cookie_browser.currentIndexChanged.connect(self._apply_to_settings)
        cookie_row.addWidget(self._use_cookies)
        cookie_row.addWidget(self._cookie_browser, 1)
        form.addRow("Cookies", cookie_row)

    def _build_playlist_group(self) -> None:
        self._playlist_group = QGroupBox("Playlist", self)
        form = QFormLayout(self._playlist_group)

        self._download_playlist = QCheckBox(
            "Download whole playlist / channel", self._playlist_group
        )
        self._download_playlist.setChecked(False)
        form.addRow("", self._download_playlist)

        self._playlist_items = QLineEdit(self._playlist_group)
        self._playlist_items.setPlaceholderText("Items, e.g. 1-10 (blank = all)")
        self._playlist_items.editingFinished.connect(self._apply_to_settings)
        form.addRow("Items", self._playlist_items)

    def _build_preset_row(self) -> None:
        self._preset_row = QHBoxLayout()
        self._preset = QComboBox(self)
        self._preset.setToolTip("Load a saved preset")
        self._preset.activated.connect(self._on_preset_selected)
        save = QPushButton("Save preset\u2026", self)
        save.clicked.connect(self._save_preset)
        delete = QPushButton("Delete", self)
        delete.clicked.connect(self._delete_preset)
        self._preset_row.addWidget(QLabel("Preset:", self))
        self._preset_row.addWidget(self._preset, 1)
        self._preset_row.addWidget(save)
        self._preset_row.addWidget(delete)

    # ── settings sync ────────────────────────────────────────────────────────
    def focus_input(self) -> None:
        """Give keyboard focus to the URL input (used by the toolbar action)."""
        self._urls.setFocus()

    # ── clipboard / "already downloaded" (extras #7, #14) ─────────────────────
    def is_input_empty(self) -> bool:
        """Whether the URL box currently holds no (non-blank) text."""
        return not self._urls.toPlainText().strip()

    def set_url(self, url: str) -> bool:
        """Insert ``url`` **only** when the input is empty; return whether we did.

        Never steals focus and never overwrites text the user is editing — the
        clipboard watcher calls this and stays hands-off otherwise.
        """
        if not self.is_input_empty():
            return False
        self._urls.setPlainText(url)
        return True

    def show_clipboard_hint(self) -> None:
        """Show a subtle "URL detected" hint under the input."""
        self._hint.setText("URL detected on the clipboard \u2014 press Download.")
        self._schedule_known_check()

    def set_known_checker(self, checker: Callable[[str], bool] | None) -> None:
        """Install the "already downloaded?" predicate and re-check the input."""
        self._known_checker = checker
        self._schedule_known_check()

    def _on_urls_changed(self) -> None:
        if self._loading:
            return
        self._schedule_known_check()

    def _schedule_known_check(self) -> None:
        if self._known_checker is not None:
            self._known_timer.start()

    def _check_known(self) -> None:
        if self._known_checker is None:
            return
        urls = extract_urls(self._urls.toPlainText())
        known = [url for url in urls if self._known_checker(url)]
        if known:
            self._hint.setText("Already downloaded: " + ", ".join(known))
        elif self._hint.text().startswith("Already downloaded"):
            self._hint.clear()

    def reload_from_settings(self) -> None:
        """Repopulate the option widgets from the shared settings (after edits)."""
        self._reload_from_settings()

    def _reload_from_settings(self) -> None:
        """Populate widgets from the shared settings (no signals fired back)."""
        self._loading = True
        try:
            settings = self._config.settings
            self._container.setCurrentIndex(
                max(0, self._container.findData(settings.video_container))
            )
            self._remux.setChecked(settings.video_remux)
            self._write_subs.setChecked(settings.write_subs)
            self._embed_subs.setChecked(settings.embed_subs)
            self._embed_thumbnail.setChecked(settings.embed_thumbnail)
            self._embed_metadata.setChecked(settings.embed_metadata)
            self._sponsorblock.setChecked(settings.sponsorblock_enabled)
            self._use_cookies.setChecked(settings.use_cookies)
            self._cookie_browser.setCurrentIndex(
                max(0, self._cookie_browser.findData(settings.cookie_browser))
            )
            self._playlist_items.setText(settings.playlist_items or "")

            if settings.audio_only:
                self._format.setCurrentIndex(self._format.findData("audio"))
                self._format_key = "audio"
                self._custom_selector = None
            elif self._format_key == "audio":
                self._format.setCurrentIndex(self._format.findData(_DEFAULT))
                self._format_key = _DEFAULT
                self._custom_selector = None
        finally:
            self._loading = False
        self._refresh_presets()
        self._update_selector_label()

    def _apply_to_settings(self) -> None:
        if self._loading:
            return
        settings = self._config.settings
        settings.video_container = self._container.currentData()
        settings.video_remux = self._remux.isChecked()
        settings.write_subs = self._write_subs.isChecked()
        settings.embed_subs = self._embed_subs.isChecked()
        settings.embed_thumbnail = self._embed_thumbnail.isChecked()
        settings.embed_metadata = self._embed_metadata.isChecked()
        settings.sponsorblock_enabled = self._sponsorblock.isChecked()
        settings.use_cookies = self._use_cookies.isChecked()
        settings.cookie_browser = self._cookie_browser.currentData()
        settings.playlist_items = self._playlist_items.text().strip() or None
        self._config.save()
        self.settings_changed.emit()

    # ── format handling ──────────────────────────────────────────────────────
    def _format_override(self) -> str | None:
        """The per-job ``format`` selector that overrides settings (or ``None``)."""
        if self._format_key == "audio":
            return None  # driven by settings.audio_only (extraction)
        if self._format_key == _CUSTOM:
            return self._custom_selector
        if self._format_key in FORMAT_PRESETS:
            return FORMAT_PRESETS[self._format_key]
        return None

    def _on_format_changed(self, index: int) -> None:
        if self._loading:
            return
        key = self._format.itemData(index)
        if key == _CUSTOM:
            selector = self._prompt_custom_format()
            if selector is None:
                self._format.blockSignals(True)
                self._format.setCurrentIndex(self._format.findData(self._format_key))
                self._format.blockSignals(False)
                return
            self._format_key = _CUSTOM
            self._custom_selector = selector
        else:
            self._format_key = str(key)
            self._custom_selector = None
            self._set_audio_only(self._format_key == "audio")
        self._update_selector_label()

    def _set_audio_only(self, enabled: bool) -> None:
        if self._config.settings.audio_only != enabled:
            self._config.set("audio_only", enabled)
            self._config.save()
            self.settings_changed.emit()

    def _prompt_custom_format(self) -> str | None:
        valid, _ = self._collect_urls()
        if not valid:
            QMessageBox.information(
                self, "Fetch formats", "Enter a valid URL first, then fetch its formats."
            )
            return None
        dialog = FormatDialog(valid[0], self, selector=self._custom_selector)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.chosen_selector()
        return None

    def _update_selector_label(self) -> None:
        selector = self._format_override()
        if self._format_key == "audio":
            codec = self._config.settings.audio_codec
            text = f"Selected: audio only (extract to {codec})"
        elif selector:
            text = f"Selected format selector: {selector}"
        else:
            preset = self._config.settings.default_format_preset
            text = f"Selected: default preset ({preset})"
        self._selector_label.setText(text)

    # ── download ─────────────────────────────────────────────────────────────
    def _collect_urls(self) -> tuple[list[str], list[str]]:
        urls = extract_urls(self._urls.toPlainText())
        valid: list[str] = []
        rejected: list[str] = []
        for url in urls:
            (valid if is_probably_valid(url) else rejected).append(url)
        return valid, rejected

    def _on_download(self) -> None:
        valid, rejected = self._collect_urls()
        if not valid:
            self._status.setText("No valid URLs found \u2014 paste one http(s) URL per line.")
            return
        self._apply_to_settings()
        selector = self._format_override()
        noplaylist = not self._download_playlist.isChecked()
        for url in valid:
            overrides: dict[str, Any] = {"noplaylist": noplaylist}
            if selector:
                overrides["format_selector"] = selector
            self._queue.add(url, **overrides)
        message = f"Queued {len(valid)} URL(s)."
        if rejected:
            message += f" Skipped {len(rejected)} invalid URL(s)."
        self._status.setText(message)
        log.info("queued %d url(s) (selector=%s, noplaylist=%s)", len(valid), selector, noplaylist)
        self._urls.clear()

    def _open_downloads_folder(self) -> None:
        target = self._config.settings.download_dir or str(user_data_dir())
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    # ── presets ──────────────────────────────────────────────────────────────
    def _refresh_presets(self) -> None:
        current = self._preset.currentText()
        self._preset.blockSignals(True)
        self._preset.clear()
        self._preset.addItem("(none)", None)
        for preset in self._config.list_presets():
            self._preset.addItem(preset.name, preset.name)
        index = self._preset.findText(current)
        self._preset.setCurrentIndex(index if index >= 0 else 0)
        self._preset.blockSignals(False)

    def _on_preset_selected(self, index: int) -> None:
        name = self._preset.itemData(index)
        if not name:
            return
        self.load_preset(str(name))

    def load_preset(self, name: str) -> bool:
        """Apply a saved preset to the shared settings and repopulate the panel."""
        preset = self._config.get_preset(name)
        if preset is None:
            return False
        for key, value in preset.values.items():
            try:
                self._config.set(key, value)
            except KeyError:
                log.warning("preset %r has unknown setting %r; ignored", name, key)
        self._config.save()
        self._reload_from_settings()
        self.settings_changed.emit()
        self._status.setText(f"Loaded preset \u201c{name}\u201d.")
        return True

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        name = name.strip()
        if not ok or not name:
            return
        values = {key: self._config.get(key) for key in _PRESET_KEYS}
        self._config.add_preset(Preset(name=name, values=values))
        self._refresh_presets()
        self._preset.setCurrentIndex(self._preset.findText(name))
        self._status.setText(f"Saved preset \u201c{name}\u201d.")

    def _delete_preset(self) -> None:
        name = self._preset.currentData()
        if not name:
            self._status.setText("No preset selected to delete.")
            return
        if self._config.delete_preset(str(name)):
            self._refresh_presets()
            self._status.setText(f"Deleted preset \u201c{name}\u201d.")
