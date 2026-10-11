"""Clipboard URL auto-detection (extra #7, leaf 6.2).

Watches the system clipboard and surfaces a single valid URL, so copying a video
link in a browser can pre-fill the download panel. It is deliberately
conservative:

* reads are **debounced** (``QClipboard.dataChanged`` fires repeatedly per copy);
* only a clipboard whose *entire* content is one http(s) URL is accepted, so
  prose or a multi-URL selection is ignored rather than pasted as noise;
* the same URL is never emitted twice in a row;
* the owner (the download panel) decides whether to insert it, and only does so
  when the input is empty — the watcher never touches focus or overwrites text.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from vdl.core.urls import extract_urls, is_probably_valid

log = logging.getLogger("vdl.ui.clipboard")

#: Milliseconds to coalesce the burst of ``dataChanged`` emissions per copy.
DEFAULT_DEBOUNCE_MS = 300


class ClipboardWatcher(QObject):
    """Emits :attr:`url_detected` when the clipboard holds a single valid URL.

    ``enabled_getter`` is consulted on every event, so a settings toggle takes
    effect immediately without re-wiring signals (the watcher stays connected).
    """

    #: Emitted with the detected URL (from the GUI thread).
    url_detected = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        enabled_getter: Callable[[], bool] | None = None,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
    ) -> None:
        super().__init__(parent)
        self._enabled_getter: Callable[[], bool] = enabled_getter or (lambda: True)
        self._enabled_override: bool | None = None
        self._last_url: str | None = None

        self._clipboard = QGuiApplication.clipboard()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(0, int(debounce_ms)))
        self._timer.timeout.connect(self._inspect)

        if self._clipboard is not None:
            self._clipboard.dataChanged.connect(self._on_data_changed)

    # ── public API ───────────────────────────────────────────────────────────
    def set_enabled(self, enabled: bool | None) -> None:
        """Force watching on/off, overriding ``enabled_getter`` (``None`` = auto).

        An in-flight debounce is cancelled when disabled.
        """
        self._enabled_override = None if enabled is None else bool(enabled)
        if self._enabled_override is False:
            self._timer.stop()

    @property
    def enabled(self) -> bool:
        return self._is_enabled()

    # ── internals ────────────────────────────────────────────────────────────
    def _is_enabled(self) -> bool:
        if self._enabled_override is not None:
            return self._enabled_override
        try:
            return bool(self._enabled_getter())
        except Exception:  # pragma: no cover - a settings read must never crash us
            return True

    def _on_data_changed(self) -> None:
        if self._is_enabled():
            self._timer.start()

    def _inspect(self) -> None:
        if not self._is_enabled() or self._clipboard is None:
            return
        text = (self._clipboard.text() or "").strip()
        if not text:
            return
        urls = extract_urls(text)
        if len(urls) != 1:
            return
        url = urls[0]
        # The whole clipboard must be essentially the URL — ignore surrounding prose.
        if text != url or not is_probably_valid(url):
            return
        if url == self._last_url:
            return
        self._last_url = url
        log.info("clipboard URL detected: %s", url)
        self.url_detected.emit(url)
