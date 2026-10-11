# VideoDownloader — Build Guide

How to build the portable Windows folder from source. This covers the sidecar
fetch script, the PyInstaller spec (and how it maps binaries), the exclusions,
and the exact build/launch commands.

The build produces a **PyInstaller `--onedir`** folder. **No `--onefile` artifact
is produced** — onedir only, by project decision.

---

## Contents

- [Prerequisites](#prerequisites)
- [Step 1 — Environment](#step-1--environment)
- [Step 2 — Fetch the sidecar binaries](#step-2--fetch-the-sidecar-binaries)
- [Step 3 — The PyInstaller spec](#step-3--the-pyinstaller-spec)
- [Step 4 — Build](#step-4--build)
- [Step 5 — Launch and verify](#step-5--launch-and-verify)
- [Size & budget](#size--budget)
- [Development checks](#development-checks)
- [Binary provenance & licences](#binary-provenance--licences)
- [Troubleshooting the build](#troubleshooting-the-build)

---

## Prerequisites

- **Windows x86_64** with **PowerShell 5.1+** (or PowerShell 7+).
- **Python 3.12–3.14** (verified on **3.14.6**). Do not use `uv` — this project
  uses `venv` + `pip`, and PyInstaller is invoked as a module.
- **Network access** at build time (to download the sidecars).
- Optional: **7-Zip** (`7z`) to extract the libmpv `.7z` archive. If it is absent,
  the fetch script falls back to `tar` (libarchive), then `winget install
  7zip.7zip`, then the Python `py7zr` package.

## Step 1 — Environment

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt` pins the runtime stack (`yt-dlp`, `yt-dlp-ejs`, `mpv==1.0.8`,
`PySide6-Essentials`, `platformdirs`); `requirements-dev.txt` adds
`pyinstaller>=6.15`, `pytest`, `pytest-qt`, `ruff` and `mypy`.

> Use `.\.venv\Scripts\python.exe` for build commands if the venv is not
> activated — the global `python` may lack the dependencies.

## Step 2 — Fetch the sidecar binaries

```powershell
powershell -ExecutionPolicy Bypass -File .\build\fetch_binaries.ps1
```

This downloads, extracts and verifies the native binaries the bundle needs,
into `vendor/`:

| Output | Upstream |
|--------|----------|
| `vendor/bin/ffmpeg.exe` | `yt-dlp/FFmpeg-Builds` static **GPL** Windows x64 |
| `vendor/bin/ffprobe.exe` | same archive |
| `vendor/bin/deno.exe` | `denoland/deno` release **≥ 2.3.0** (the `deno` binary, not `denort`) |
| `vendor/libmpv/libmpv-2.dll` | `shinchiro/mpv-winbuild-cmake` (`mpv-dev`, **non-v3** x86_64) |

Details:

- **Idempotent.** A binary already present and passing a lightweight PE check is
  skipped. Pass `-Force` to re-download, `-VendorDir <path>` to override the
  output directory.
- **Verification.** ffmpeg (`checksums.sha256`) and deno (`…zip.sha256sum`) are
  checksum-verified. shinchiro publishes **no** checksum for libmpv, so the script
  records the archive SHA-256 and applies a PE-header (`MZ`) sanity check.
- **Resolved versions are printed** at the end (and, for deno, checked against the
  ≥ 2.3.0 minimum).

Last observed run resolved: `ffmpeg N-127276-g8e9db1f152-20261010`,
`deno 2.9.7`, `libmpv v0.41.0-1122-gaccb7b282`.

> The `vendor/` folder is **never committed** — it is gitignored and re-fetched at
> build time.

## Step 3 — The PyInstaller spec

`build/vdl.spec` builds a **onedir, windowed** app:

- **`console=False`** — windowed. In this mode there is no console (`stdout`/
  `stderr` are `None`), so all app logging goes through the rotating file handler
  at `<user-data>\logs\vdl.log`.
- **Entry point** — `build/entry_vdl.py`, a dedicated launcher that defers to
  `vdl.__main__.main` (avoids PyInstaller’s `__main__` name-clash and calls
  `multiprocessing.freeze_support()`).
- **`COLLECT`** — emits the onedir folder; there is no `EXE(..., onefile=True)`.

### Binary mapping (ruling R-006)

The spec maps the `vendor/` sidecars to the **same sub-paths**
`vdl.paths.resource_path` resolves at run time:

| Source (`vendor/…`) | Destination in the bundle |
|---------------------|----------------------------|
| `bin/ffmpeg.exe` | `_internal\bin\ffmpeg.exe` |
| `bin/ffprobe.exe` | `_internal\bin\ffprobe.exe` |
| `bin/deno.exe` | `_internal\bin\deno.exe` |
| `libmpv/libmpv-2.dll` | `_internal\libmpv\libmpv-2.dll` |

> **R-006.** This supersedes an earlier plan snippet that placed the binaries at
> the `_internal\` root. The `bin/` / `libmpv/` subdirectories match
> `paths.ffmpeg_exe()` / `paths.libmpv_dll()` in both dev (`vendor/…`) and frozen
> (`<_MEIPASS>/…`) modes, and the vendored `player/mpv.py` derives the DLL
> directory from `paths.libmpv_dll()`.

Packaged resources (`src/vdl/resources`) are mapped to `_internal\resources`,
matching `paths.resource_path('resources', …)` in frozen mode.

### `yt-dlp-ejs` (YouTube JS challenges)

`yt-dlp-ejs` is **JavaScript data only** — import analysis cannot discover it. The
spec calls `collect_all("yt_dlp_ejs")` and adds `yt_dlp_ejs` to the hidden
imports, so the challenge-solver scripts land in `_internal\yt_dlp_ejs\`. Without
this, YouTube downloads fail with “JS runtime missing”.

### Exclusions

To keep the bundle light, the spec excludes heavy modules the app never imports:

- **Qt:** `QtWebEngineCore`, `QtWebEngineWidgets`, `QtWebEngineQuick`,
  `QtWebChannel`, `QtWebSockets`, `Qt3D*`, `QtCharts`, `QtQuick`, `QtQuick3D`,
  `QtQml`, `QtDesigner`, `QtMultimedia`, `QtMultimediaWidgets`.
- **Other heavyweights:** `tkinter`, `matplotlib`, `numpy`, `scipy`, `pandas`.
- **Rival bindings:** `PyQt5`, `PyQt6`, `PySide2`, `shiboken2`.

Only `QtCore` / `QtGui` / `QtWidgets` are actually used.

### DLL-search runtime hook

`build/rthook_win_dll.py` runs at frozen start-up and:
- clears the process-wide DLL search directory (`SetDllDirectoryW(None)`), and
- strips `<_MEIPASS>` from `PATH`.

PyInstaller’s bootloader sets both process-wide; they are inherited by child
processes, so a spawned `ffmpeg.exe` / `ffprobe.exe` / `deno.exe` could otherwise
resolve the wrong (or a stale) DLL. The same logic is mirrored in
`vdl.paths._sanitize_dll_search()` so dev and frozen runs behave identically.

## Step 4 — Build

One-shot (recommended):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

`scripts\build.ps1` runs, in order: fetch (`fetch_binaries.ps1`) → clean previous
output → PyInstaller (`build\vdl.spec`) → assert artifacts → run the frozen
`--selftest` (must exit 0) → print the unpacked size.

Parameters: `-SkipFetch` (reuse an existing `vendor/`) and `-SkipSelftest`
(build + assertions only).

Or run the steps yourself:

```powershell
powershell -ExecutionPolicy Bypass -File .\build\fetch_binaries.ps1
python -m PyInstaller --clean --noconfirm build\vdl.spec
```

**Output:** `dist\VideoDownloader\VideoDownloader.exe` (the app EXE is ~8.7 MB)
alongside `_internal\`.

### Assert the bundle is complete

```powershell
Test-Path .\dist\VideoDownloader\VideoDownloader.exe                     # True
Test-Path .\dist\VideoDownloader\_internal\bin\ffmpeg.exe                # True
Test-Path .\dist\VideoDownloader\_internal\bin\ffprobe.exe               # True
Test-Path .\dist\VideoDownloader\_internal\bin\deno.exe                  # True
Test-Path .\dist\VideoDownloader\_internal\libmpv\libmpv-2.dll           # True
Test-Path .\dist\VideoDownloader\_internal\yt_dlp_ejs                    # True (EJS data)
Test-Path .\dist\VideoDownloader\_internal\PySide6\QtWebEngineCore.pyd   # False (excluded)
```

> These paths include the `bin\` / `libmpv\` subdirectories from **R-006**. An
> earlier plan snippet asserted the sidecars at the `_internal\` root; that is
> superseded.

> The `build.ps1` guard that checks “no EXE larger than 50 MB” is scoped to the
> **app’s own EXE** (and to the absence of any EXE at `dist\` root). The bundled
> sidecars `ffmpeg.exe` / `ffprobe.exe` / `deno.exe` legitimately exceed 50 MB and
> are expected; they are not onefile blobs.

## Step 5 — Launch and verify

```powershell
# Headless readiness probe (no window). Writes selftest.json, exits 0 on success.
Start-Process .\dist\VideoDownloader\VideoDownloader.exe --selftest -Wait -NoNewWindow
Get-Content .\selftest.json

# Full app
Start-Process .\dist\VideoDownloader\VideoDownloader.exe
```

`selftest.json` reports `ok`, `frozen`, `qt_import_ok`, the resolved
`libmpv` / `ffmpeg` / `ffprobe` / `deno` versions, the four resource paths, the
user-data directory, the log file, and `dll_search.meipass_in_path` (must be
`false`).

> **Windowed-exe caveat.** Because the app is a GUI-subsystem executable,
> PowerShell does not block when you launch it directly with `.\…\VideoDownloader.exe`
> — the prompt returns before the process exits. Use
> `Start-Process … -Wait` when you need the exit code (the build script does this).

> **Portability note.** The frozen app was **manually verified on a machine with
> no Python installed / not on `PATH`** (the true portability proof), confirming
> it launches on a Python-free box.

## Size & budget

The unpacked `dist\VideoDownloader\` folder was **measured at ~636 MB**:

- `_internal\bin\` ≈ 415 MB (ffmpeg ≈ 161 MB, ffprobe ≈ 161 MB, deno ≈ 93 MB)
- `_internal\libmpv\` ≈ 115 MB
- `_internal\PySide6\` ≈ 74 MB

This **exceeds** the original ≤350 MB design budget. The excess is inherent to
the static-GPL ffmpeg build plus the bundled deno runtime; no accept criterion
names a hard cap. The figure above is measured, not a target.

## Development checks

These do not require a build:

```powershell
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src
python -m pytest tests/unit -q
```

Integration tests are opt-in (network):

```powershell
$env:VDL_RUN_INTEGRATION = "1"
python -m pytest tests/integration -q -m integration
```

As last verified: unit suite **152 passed**; opt-in integration **3 passed**.

> Invoke pytest with `.\.venv\Scripts\python.exe` if the global interpreter lacks
> the deps. When capturing results, prefer `> $null 2>&1` to read the true exit
> code — piping pytest’s stderr through PowerShell can render a benign
> libmpv first-chance-exception line as a `NativeCommandError`.

## Binary provenance & licences

The bundled components and their upstream-declared licences:

| Component | Source | Licence |
|-----------|--------|---------|
| ffmpeg / ffprobe | `yt-dlp/FFmpeg-Builds` (`ffmpeg-master-latest-win64-gpl`) | **GPL** |
| libmpv-2.dll | `shinchiro/mpv-winbuild-cmake` (`mpv-dev`, non-v3) | **GPL** |
| yt-dlp | `yt-dlp/yt-dlp` | **Unlicense** |
| deno | `denoland/deno` | **MIT** |
| PySide6 (Essentials) | Qt for Python | **LGPL** |
| python-mpv (vendored) | `jaseg/python-mpv` 1.0.8 | GPLv2-or-later / LGPLv2.1-or-later (inherits libmpv) |

The GPL builds of ffmpeg and libmpv were accepted by project decision. If you
redistribute the portable folder, include the corresponding licence texts and
attribution. The vendored `python-mpv` (`src/vdl/player/mpv.py`) is byte-for-byte
upstream below its provenance header — do not edit it; re-copy it on upgrade.

## Troubleshooting the build

- **`fetch_binaries.ps1` fails on the libmpv `.7z`** — install 7-Zip, or ensure
  `tar`/`winget`/`py7zr` is available (the script tries them in order).
- **PyInstaller cannot find `build/entry_vdl.py`** — the launcher must be present
  and tracked; the spec references it explicitly.
- **The frozen app reports missing resources** — re-check the R-006 binary paths
  (`_internal\bin\*`, `_internal\libmpv\libmpv-2.dll`).
- For runtime problems (black player, YouTube JS runtime, cookie lock, DLL
  errors, antivirus), see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
