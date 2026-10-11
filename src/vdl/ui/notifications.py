"""Completion/failure notifications via the system tray (extra #16, leaf 6.3).

Uses :meth:`QSystemTrayIcon.showMessage` — a native Windows balloon — so no new
third-party dependency (e.g. ``winotify``) is required. The "Play" affordance is
implemented the way Windows balloons allow: clicking the balloon emits
``messageClicked``, which invokes the callback supplied with the notification.

Toggles
-------
* **Do not disturb** honours ``Settings.notify_on_complete`` (persisted): when a
  completion notification is off, :meth:`notify` is a no-op. This is exactly the
  "suppress toggle" the acceptance criteria ask for.
* ``suppress_when_focused`` makes balloons optional while the app has focus;
  it defaults to ``False`` so a finished download is always surfaced.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from vdl.config import ConfigStore

log = logging.getLogger("vdl.ui.notifications")

#: How long a balloon stays up (ms). Clicking it still fires ``messageClicked``.
_CLICK_TIMEOUT_MS = 12_000


class Notifier:
    """Shows tray balloons for terminal jobs; honours the do-not-disturb toggle."""

    def __init__(
        self,
        tray: QSystemTrayIcon | None,
        config: ConfigStore,
        parent: QObject | None = None,
        *,
        suppress_when_focused: bool = False,
    ) -> None:
        self._tray = tray
        self._config = config
        self._parent = parent
        self.suppress_when_focused = bool(suppress_when_focused)
        self._on_click: Callable[[], None] | None = None
        if tray is not None:
            tray.messageClicked.connect(self._on_message_clicked)

    # ── toggles ──────────────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        """Whether completion notifications are allowed (do-not-disturb off)."""
        return bool(getattr(self._config.settings, "notify_on_complete", True))

    def set_enabled(self, enabled: bool) -> None:
        """Persist the do-not-disturb toggle back into ``Settings``."""
        self._config.settings.notify_on_complete = bool(enabled)
        self._config.save()

    # ── notifications ────────────────────────────────────────────────────────
    def notify(
        self,
        title: str,
        message: str,
        *,
        on_click: Callable[[], None] | None = None,
        urgent: bool = False,
    ) -> bool:
        """Show a balloon; returns ``True`` if it was actually shown.

        ``on_click`` (e.g. open the finished file in the player) runs when the
        user clicks the balloon.
        """
        if not self.enabled:
            log.info("notification suppressed (do-not-disturb): %s", title)
            return False
        if self._tray is None:
            log.info("notification skipped (no system tray): %s", title)
            return False
        if self.suppress_when_focused and self._app_focused():
            log.info("notification suppressed (window focused): %s", title)
            return False

        self._on_click = on_click
        icon = (
            QSystemTrayIcon.MessageIcon.Critical
            if urgent
            else QSystemTrayIcon.MessageIcon.Information
        )
        try:
            self._tray.showMessage(title, message, icon, _CLICK_TIMEOUT_MS)
        except Exception:  # pragma: no cover - a failed balloon must never crash the app
            log.exception("failed to show notification: %s", title)
            return False
        return True

    # ── internals ────────────────────────────────────────────────────────────
    def _on_message_clicked(self) -> None:
        callback, self._on_click = self._on_click, None
        if callback is None:
            return
        try:
            callback()
        except Exception:  # pragma: no cover - user callback is best-effort
            log.exception("notification click handler failed")

    @staticmethod
    def _app_focused() -> bool:
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return False
        return any(widget.isActiveWindow() for widget in QApplication.topLevelWidgets())
