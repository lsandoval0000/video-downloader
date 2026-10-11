"""Application bootstrap and the single, global startup-ordering guarantee.

Qt **must** be imported before ``locale.setlocale(locale.LC_NUMERIC, 'C')`` is
applied, and that locale call **must** run before the first ``mpv.MPV()`` is
constructed (leaf 5.x). libmpv parses floats using ``LC_NUMERIC``; if Qt clobbers
the locale after we set it — or if we set it after mpv has started — libmpv
silently misbehaves. Enforcing this order here, exactly once, is the whole point
of this module (see the plan's "libmpv locale ordering" gotcha).

Only one ``QApplication`` may exist per process (required by Qt and by libmpv).
"""

from __future__ import annotations

import locale
import sys


def run(argv: list[str] | None = None) -> int:
    """Create the ``QApplication``, wire logging/exceptions, show the window."""
    from vdl import __version__, logging_setup
    from vdl.paths import _sanitize_dll_search

    # 1) Undo PyInstaller's leaked DLL search dir before any DLL/subprocess runs.
    _sanitize_dll_search()

    # 2) Logging + global (main + worker thread) exception handling.
    logger = logging_setup.setup_logging()

    # 3) Import Qt FIRST...
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("VideoDownloader")
    app.setOrganizationName("VideoDownloader")
    app.setApplicationVersion(__version__)

    logging_setup.install_excepthook(app)

    # 4) ...THEN force the C numeric locale, before the first MPV() is ever made.
    locale.setlocale(locale.LC_NUMERIC, "C")

    if sys.stdout is not None:
        print("vdl imports OK — starting VideoDownloader")

    # 5) Build the window. Branch 6 replaces the MainWindow internals.
    from vdl.ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    logger.info("VideoDownloader %s started", __version__)
    return app.exec()
