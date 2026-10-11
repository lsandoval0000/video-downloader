"""Frozen entry-point launcher for the PyInstaller bundle (plan leaf 7.2).

A dedicated launcher module — rather than freezing ``vdl/__main__.py`` directly
— avoids PyInstaller's ``__main__`` name-clash pitfalls (the bundled script would
otherwise shadow the stdlib ``__main__`` semantics during analysis). It simply
defers to :func:`vdl.__main__.main`, preserving the exact same entry contract as
``python -m vdl`` and the ``video-downloader`` console script.

``multiprocessing.freeze_support()`` is called first so any frozen
multiprocessing use (in yt-dlp or a future component) cannot re-launch the GUI.
"""

from __future__ import annotations

import multiprocessing


def _run() -> int:
    from vdl.__main__ import main

    return main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(_run())
