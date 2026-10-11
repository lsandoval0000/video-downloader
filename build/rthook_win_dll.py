"""PyInstaller Windows runtime hook — sanitize the process DLL search path.

Executed by the PyInstaller bootloader immediately after interpreter start-up
and *before* the bundled application's own code runs (plan leaf 7.3).

Why this exists
---------------
PyInstaller's Windows bootstrap sets a process-wide DLL search directory
(``SetDllDirectoryW(<_MEIPASS>)``) and prepends ``<_MEIPASS>`` to ``PATH``.
Both settings are inherited by child processes, so a spawned ``ffmpeg.exe`` /
``ffprobe.exe`` / ``deno.exe`` can resolve the wrong — or a stale — DLL, or fail
to start at all. Clearing the DLL directory and stripping ``<_MEIPASS>`` from
``PATH`` restores the default search order.

This mirrors :func:`vdl.paths._sanitize_dll_search` so dev and frozen runs behave
identically. It is deliberately self-contained (only stdlib, no package imports)
because runtime hooks run very early and must not depend on import order.
Idempotent; a safe no-op on non-Windows platforms.
"""

from __future__ import annotations

import os
import sys


def sanitize_dll_search() -> None:
    """Undo PyInstaller's process-wide DLL-search-directory leak.

    * Clears the process DLL directory (``SetDllDirectoryW(None)``) so it is not
      inherited by spawned sidecar processes.
    * Strips every ``sys._MEIPASS`` entry from ``PATH`` (case-/separator-
      insensitively) so child processes never search the removed bundle dir.
    """
    if os.name != "nt":
        return

    try:
        import ctypes

        ctypes.windll.kernel32.SetDllDirectoryW(None)
    except Exception:  # pragma: no cover - defensive; must never break startup
        pass

    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return

    meipass_norm = os.path.normcase(os.path.normpath(meipass))
    entries = [
        entry
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry and os.path.normcase(os.path.normpath(entry)) != meipass_norm
    ]
    os.environ["PATH"] = os.pathsep.join(entries)


# Run at import: runtime hooks are executed top-to-bottom, so this fires before
# the frozen application's ``__main__`` is entered.
sanitize_dll_search()
