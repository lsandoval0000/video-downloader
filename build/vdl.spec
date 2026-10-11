# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec — VideoDownloader, **onedir + windowed** (plan leaf 7.2).

Build (from the repository root):

    python -m PyInstaller --clean --noconfirm build/vdl.spec

Produces ``dist/VideoDownloader/VideoDownloader.exe`` alongside an ``_internal/``
folder. This spec **only** ever emits an onedir ``COLLECT`` — no ``--onefile``
artifact is produced (explicit project decision; see .aiw/plan.md).

Native sidecars are mapped to the SAME sub-paths ``vdl.paths.resource_path``
resolves at runtime (RULING R-006 — the earlier plan snippet that placed the
binaries at the ``_internal`` root is superseded):

    vendor/bin/ffmpeg.exe       -> _internal/bin/ffmpeg.exe
    vendor/bin/ffprobe.exe      -> _internal/bin/ffprobe.exe
    vendor/bin/deno.exe         -> _internal/bin/deno.exe
    vendor/libmpv/libmpv-2.dll  -> _internal/libmpv/libmpv-2.dll

This matches ``paths.ffmpeg_exe()`` / ``paths.libmpv_dll()`` and the frozen
``player/mpv.py::_ensure_dll_dir`` contract (it prepends the DLL dir derived from
``paths.libmpv_dll()`` before the upstream ``CDLL`` load).

``yt-dlp-ejs`` is DATA ONLY (JavaScript challenge-solver scripts consumed by the
bundled ``deno`` runtime). Import analysis cannot discover it, so it MUST be
collected explicitly — otherwise YouTube downloads break with
"JS runtime missing".
"""

from __future__ import annotations

import os

from PyInstaller.utils.hooks import collect_all

# ``SPECPATH`` is injected by PyInstaller and points at this spec's directory
# (``build/``). Deriving every path from it makes the build independent of the
# current working directory (idempotent + re-runnable from anywhere).
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 - injected global


def _p(*parts: str) -> str:
    """Absolute path under the repository root."""
    return os.path.join(ROOT, *parts)


# ── yt-dlp-ejs: JavaScript challenge-solver DATA (must be collected) ──────────
ejs_datas, ejs_binaries, ejs_hiddenimports = collect_all("yt_dlp_ejs")

# ── native sidecars -> _internal/<subdir>/* (R-006) ──────────────────────────
binaries = ejs_binaries + [
    (_p("vendor", "bin", "ffmpeg.exe"), "bin"),
    (_p("vendor", "bin", "ffprobe.exe"), "bin"),
    (_p("vendor", "bin", "deno.exe"), "bin"),
    (_p("vendor", "libmpv", "libmpv-2.dll"), "libmpv"),
]

# Packaged resources resolve under <_MEIPASS>/resources via paths.resource_path.
datas = ejs_datas + [
    (_p("src", "vdl", "resources"), "resources"),
]

hiddenimports = ejs_hiddenimports + ["yt_dlp_ejs"]

# Heavy / unused modules — excluded to honour the "light" bundling requirement.
excludes = [
    # Qt modules we never import (only QtCore/QtGui/QtWidgets are used).
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.QtCharts",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.QtDesigner",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    # Non-Qt heavyweights that are never imported.
    "tkinter",
    "matplotlib",
    "numpy",
    "scipy",
    "pandas",
    # Rival bindings that must never be pulled in alongside PySide6.
    "PyQt5",
    "PyQt6",
    "PySide2",
    "shiboken2",
]

a = Analysis(
    [_p("build", "entry_vdl.py")],
    pathex=[_p("src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[_p("build", "rthook_win_dll.py")],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed — logging goes to the rotating file handler
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory="_internal",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VideoDownloader",
)
