"""Centralised logging and global exception handling.

In the frozen ``--windowed`` build there is **no console**: ``sys.stdout`` and
``sys.stderr`` are ``None``. Everything the app wants to report must therefore
go through :func:`setup_logging`'s rotating file handler — a bare ``print`` in
that mode would raise. The console handler here is added only when a real
stream exists.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from pathlib import Path
from typing import Any

from vdl.paths import user_data_dir

LOGGER_NAME = "vdl"
_MAX_BYTES = 2 * 1024 * 1024  # rotate at 2 MB
_BACKUP_COUNT = 3
_LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s"

_configured = False


def log_file_path() -> Path:
    """Return the on-disk log file path (its parent directory may not exist yet)."""
    return user_data_dir() / "logs" / "vdl.log"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure and return the application logger (idempotent).

    Attaches a 2 MB rotating file handler and — only when ``sys.stdout`` exists
    — a console handler.
    """
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT)

    path = log_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Frozen --windowed builds have sys.stdout is None -> no console handler.
    if sys.stdout is not None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    _configured = True
    # State the resolved locations up front: the frozen --windowed build has no
    # console, so "where are my logs?" is answered by the log itself (leaf 10.6).
    logger.info("data directory: %s", user_data_dir())
    logger.info("log file: %s", path)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the app logger (or a child logger), configuring on first use."""
    setup_logging()
    if name is None:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def install_excepthook(app: Any | None = None) -> None:
    """Route unhandled exceptions to the log and a Qt error dialog.

    Wraps both :data:`sys.excepthook` (main thread) and
    :data:`threading.excepthook` (worker threads, e.g. the download engine), so
    a crash is logged with a full traceback and surfaced instead of silently
    killing the app. ``app`` may be ``None`` before a ``QApplication`` exists.
    """
    logger = setup_logging()

    def _log_and_report(exc_type: type[BaseException], exc_value, exc_tb) -> None:
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        _show_error_dialog(app, exc_type, exc_value)

    def _excepthook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _log_and_report(exc_type, exc_value, exc_tb)

    def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        _log_and_report(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


def _show_error_dialog(app: Any | None, exc_type: type[BaseException], exc_value) -> None:
    """Show a modal error dialog, if Qt is available and an app exists."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except Exception:  # pragma: no cover - Qt may be unavailable in headless use
        return
    if QApplication.instance() is None:
        return
    text = (
        f"{exc_type.__name__}: {exc_value}\n\nThe full traceback was written to:\n{log_file_path()}"
    )
    try:
        QMessageBox.critical(None, "VideoDownloader — Unexpected error", text)
    except Exception:  # pragma: no cover - the handler must never crash the app
        pass
