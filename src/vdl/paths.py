"""Single source of truth for filesystem locations.

**Every** ``sys._MEIPASS`` / frozen-vs-dev decision lives in this module — no
other module may compute resource paths (see the plan's anti-patterns).

Layout this module resolves:

* Dev checkout: native binaries under ``<repo>/vendor/`` (``bin/`` and
  ``libmpv/``); packaged resources under the ``vdl`` package dir.
* Frozen app: both resolved under ``sys._MEIPASS`` (PyInstaller's ``_internal``
  directory), populated by ``build/vdl.spec``.

It also owns :func:`_sanitize_dll_search`, which undoes PyInstaller's
process-wide DLL-search-directory leak (plan leaf 7.3).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import platformdirs

_PACKAGE_DIR = Path(__file__).resolve().parent  # .../src/vdl
_REPO_ROOT = _PACKAGE_DIR.parent.parent  # repo root in a dev checkout

# Subdirectories that hold native binaries. In a dev checkout these live under
# <repo>/vendor/; when frozen they live under <_MEIPASS>/.
_BINARY_SUBDIRS = frozenset({"bin", "libmpv"})

_APP_NAME = "VideoDownloader"


def is_frozen() -> bool:
    """Return ``True`` when running inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_path(*parts: str) -> str:
    """Resolve a bundled resource to an absolute path.

    Frozen: joined onto ``sys._MEIPASS`` (the ``_internal`` dir), e.g.
    ``resource_path('bin', 'ffmpeg.exe')`` -> ``<_MEIPASS>/bin/ffmpeg.exe``.

    Dev: native binaries resolve under ``<repo>/vendor/``; everything else
    resolves under the ``vdl`` package directory.
    """
    if is_frozen():
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
    elif parts and parts[0] in _BINARY_SUBDIRS:
        base = str(_REPO_ROOT / "vendor")
    else:
        base = str(_PACKAGE_DIR)
    return os.path.join(base, *parts)


def ffmpeg_exe() -> str:
    """Absolute path to the bundled ``ffmpeg`` executable."""
    return resource_path("bin", "ffmpeg.exe")


def ffprobe_exe() -> str:
    """Absolute path to the bundled ``ffprobe`` executable."""
    return resource_path("bin", "ffprobe.exe")


def deno_exe() -> str:
    """Absolute path to the bundled ``deno`` runtime (yt-dlp JS challenges)."""
    return resource_path("bin", "deno.exe")


def libmpv_dll() -> str:
    """Absolute path to the bundled ``libmpv-2.dll``."""
    return resource_path("libmpv", "libmpv-2.dll")


def app_dir() -> Path:
    """Directory the application "lives" in.

    Frozen: the folder containing the executable. Dev: the repository root.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _REPO_ROOT


def is_portable() -> bool:
    """Portable mode is signalled by a ``portable.txt`` file next to the exe."""
    try:
        return (app_dir() / "portable.txt").is_file()
    except OSError:
        return False


def user_data_dir() -> Path:
    """Return (creating if needed) the writable application-data directory.

    Portable mode -> ``<app>/data``; otherwise the OS user-data dir via
    ``platformdirs``. On locked-down machines the preferred location may not be
    writable, so we fall back to the app folder, then the OS temp dir — this
    function never raises.
    """
    if is_portable():
        candidates = [app_dir() / "data"]
    else:
        candidates = [
            # appauthor=False -> "<...>/VideoDownloader", not the redundant
            # "<...>/VideoDownloader/VideoDownloader" platformdirs would build
            # by default (it mirrors appauthor=appname when unset).
            Path(platformdirs.user_data_dir(_APP_NAME, appauthor=False)),
            app_dir() / "data",
            Path(tempfile.gettempdir()) / _APP_NAME,
        ]
    last_error: OSError | None = None
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError as exc:
            last_error = exc
    raise RuntimeError(f"no writable data directory could be created: {last_error}")


def _sanitize_dll_search() -> None:
    """Undo PyInstaller's process-wide DLL-search-directory leak (leaf 7.3).

    PyInstaller's bootloader calls ``SetDllDirectoryW(<_MEIPASS>)`` on Windows.
    That setting is process-wide and inherited by child processes, so a spawned
    ``ffmpeg.exe`` / ``ffprobe.exe`` / ``deno.exe`` can resolve the wrong (or a
    stale) DLL. Clearing it and stripping ``_MEIPASS`` from ``PATH`` restores the
    default search order.

    Idempotent; a safe no-op on non-Windows platforms.

    Mirrored by ``build/rthook_win_dll.py`` so dev and frozen behave identically.
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
