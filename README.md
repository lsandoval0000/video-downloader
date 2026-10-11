# VideoDownloader

A light, **portable, no-install** Windows desktop app to download video/audio from
any site that [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) supports, preview media
instantly, and manage a full workflow (queue, formats, subtitles, SponsorBlock,
history) — without an installer, a registry footprint, or a browser
plugin.

It ships as a **PyInstaller onedir folder** that runs offline: `yt-dlp` is used
in-process, `ffmpeg`/`ffprobe` do the post-processing, a bundled `deno` runtime
solves YouTube's JavaScript challenges, and a real **libmpv** player is embedded
in the window.

> **Package shape / status.** This is version `0.1.0`. The portable folder builds,
> the frozen `--selftest` passes (exit 0), and the embedded player has been proven
> to render on Windows during development. Launching the **frozen** window on a
> machine with **no Python installed / not on `PATH`** has **not yet been
> verified** — see [Not yet verified](#not-yet-verified). The unpacked portable
> folder currently measures **~636 MB** (this exceeds the original ≤350 MB design
> target; see [Size & budget](#size--budget)).

---

## Contents

- [What it is](#what-it-is)
- [Features](#features)
- [Requirements](#requirements)
- [Quick Start (run from source)](#quick-start-run-from-source)
- [Build the portable folder](#build-the-portable-folder)
- [User data & portable mode](#user-data--portable-mode)
- [Bundled third-party binaries & licences](#bundled-third-party-binaries--licences)
- [Testing](#testing)
- [Not yet verified](#not-yet-verified)
- [Documentation](#documentation)

---

## What it is

One folder you can zip, copy to a USB stick, unzip anywhere (including
`C:\Program Files` or a network share) and double-click. No registry writes, no
installer, no admin rights. All state — settings, presets, history, logs — lives
in a **portable user-data directory** (next to the app in portable mode, or under
`%LOCALAPPDATA%\VideoDownloader` otherwise).

| Piece | Role |
|-------|------|
| **GUI** | PySide6 (Qt 6, *Essentials* only) |
| **Download engine** | `yt-dlp` imported **in-process**, driven from a Qt worker thread |
| **Post-processing** | bundled static-GPL `ffmpeg` / `ffprobe` |
| **Player** | bundled `libmpv-2.dll` + vendored `python-mpv` |
| **YouTube JS challenges** | bundled `deno` + `yt-dlp-ejs` data |
| **Packaging** | PyInstaller **onedir**, windowed (`console=False`) |

## Features

16 of the 17 requested extras are implemented:

1. **Format / quality picker** — quality presets (Best, 1080p, 720p, Audio only,
   Smallest) plus a *Fetch formats…* dialog that lists every format for a URL.
2. **Audio-only extraction** — extract to **mp3** or **m4a**.
3. **Playlist / channel download** — download a whole playlist or channel, with
   an optional item range (e.g. `1-10`).
4. **Batch / multi-URL input** — paste one URL per line; every valid URL is
   enqueued, invalid lines are skipped with a reason.
5. **Download queue with pause / resume / cancel** — respecting a configurable
   max-concurrency; pause keeps the partial file so resume continues it.
6. **Progress + speed / ETA** — live percent, size, speed (MB/s) and ETA, plus a
   distinct status for post-processing stages (e.g. “Merging”).
7. **Clipboard auto-detect** — copying a video URL pre-fills the input (never
   steals focus, never overwrites what you are typing); toggleable in Settings.
8. **Subtitles download / embed** — write `.srt` sidecar files and/or mux
   subtitles into the container, with selectable languages. Subtitles are
   fetched in a **separate, non-fatal pass** after the media, so a subtitle
   failure (e.g. a YouTube caption rate-limit) never aborts the download.
9. **Thumbnail + metadata embedding** — embed the cover image and title/artist/
   date tags into the output file.
10. **SponsorBlock removal** — cut sponsor/self-promo/… segments from marked
    videos, with selectable categories.
11. **Cookies / browser import** — import cookies from Chrome, Edge, Firefox,
    Brave, Opera, Vivaldi (or a `cookies.txt` file) for login-walled videos.
12. **Format conversion** — target a container/codec (e.g. → mp4, mkv, webm,
    mp3, opus); remux-only (fast stream copy) is available instead of re-encode.
13. **History** — every download is recorded in a SQLite `history.db` that backs
    the History table (browse, reopen in the player, clear). Re-pasting a known
    URL shows a *“previously downloaded — will download again”* hint; it never
    skips the download.
14. **Presets** — save the current download options as a named preset, load it
    later, delete it; presets persist across restarts.
15. **Notifications** — a Windows tray balloon when a download finishes or fails,
    with a click-to-play action and a “Do not disturb” toggle.
16. **Embedded player (libmpv)** — the downloaded file plays **inside the app**
    (not an external player) with seek, volume, mute, speed and audio/subtitle
    track selection. The ⛶ button (or `F`) fullscreens the **video** — the
    surrounding chrome is hidden while the transport controls stay visible — and
    `Esc` returns to the windowed layout.

## Requirements

- **Windows x86_64** (only `win_amd64` artifacts are targeted).
- **To run from source:** Python **3.12–3.14** (developed and verified on
  **3.14.6**). No separate `ffmpeg`/`deno`/`mpv` install is needed — the build
  scripts fetch them into the project.
- **To run the portable folder:** nothing. No Python, no installs.
- **Network access at build time** (to fetch the bundled binaries) and,
  naturally, at run time for downloads.

## Quick Start (run from source)

From the repository root (`D:\Desarrollo\Repos\video-downloader`). This project
uses `venv` + `pip` (there is **no `uv`**).

```powershell
# 1. Create and activate a virtualenv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

# 2. Install runtime + dev dependencies
python -m pip install -r requirements.txt -r requirements-dev.txt

# 3. Fetch the bundled sidecar binaries into vendor/ (ffmpeg, ffprobe, deno, libmpv)
powershell -ExecutionPolicy Bypass -File .\build\fetch_binaries.ps1

# 4. Run the app
python -m vdl
```

Running from source resolves the native binaries under the repo’s `vendor/`
folder, so step 3 is required before step 4.

### Verify the installation headlessly

`--selftest` resolves every bundled resource, loads libmpv, imports Qt without a
display, and spawns `ffmpeg`/`ffprobe`/`deno`, then writes `selftest.json` to the
current directory. It exits `0` only when every check passes.

```powershell
python -m vdl --selftest
Get-Content .\selftest.json
```

> Tip: activate the venv (step 1) or call `.\.venv\Scripts\python.exe` explicitly
> — the global `python` may not have the project’s dependencies installed.

## Build the portable folder

The build needs the `vendor/` binaries to be present (the fetch script handles
that), then PyInstaller produces the `dist\VideoDownloader\` folder.

```powershell
# One-shot: fetch → clean → PyInstaller → artifact checks → frozen --selftest → size
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

Or run the two steps individually:

```powershell
powershell -ExecutionPolicy Bypass -File .\build\fetch_binaries.ps1
python -m PyInstaller --clean --noconfirm build\vdl.spec
```

**Output:** `dist\VideoDownloader\VideoDownloader.exe` next to an `_internal\`
folder. No `--onefile` artifact is produced (onedir only, by project decision).

The build script asserts every required artifact is present, confirms no onefile
blob was produced, runs the frozen `--selftest`, and prints the unpacked size.

### Launch the built app

```powershell
# Machine-readable readiness probe (no window, writes selftest.json, exit 0 on success)
Start-Process .\dist\VideoDownloader\VideoDownloader.exe --selftest -Wait -NoNewWindow

# Full app
Start-Process .\dist\VideoDownloader\VideoDownloader.exe
```

> Because the app is a GUI-subsystem (`--windowed`) executable, PowerShell does
> **not** block on `.\...\VideoDownloader.exe` when invoked directly. Use
> `Start-Process … -Wait` when you need a deterministic exit code (this is what
> `scripts\build.ps1` does).

See **[docs/BUILD.md](docs/BUILD.md)** for the full build details (the fetch
script, the spec, binary mapping, and the exact commands).

## User data & portable mode

All persistent state lives in a single **user-data directory**:

- **Portable mode** — active when a file named `portable.txt` sits **next to the
  executable**. Data goes to `<app folder>\data`. This keeps everything on the
  stick / in the copied folder.
- **Installed mode** (no `portable.txt`) — data goes to
  `%LOCALAPPDATA%\VideoDownloader` (the per-user *local* app-data folder, not
  `%APPDATA%`/Roaming). The rotating log is at
  `%LOCALAPPDATA%\VideoDownloader\logs\vdl.log`; the exact resolved directory is
  written to that log at every startup. On locked-down machines where the
  preferred location is not writable, the app falls back to `<app folder>\data`
  and then the OS temp dir, so it never fails to start.

You can see the active directory any time in **Settings → Data directory**
(which also shows a *Portable* / *Installed* indicator and an **Open data
folder** button).

Files inside the user-data directory:

| File | Purpose |
|------|---------|
| `config.json` | Settings + saved presets (written atomically; corrupt files fall back to defaults). |
| `history.db` | Rich **SQLite** index backing the History view (title, url, path, status, timestamp). It records what was downloaded; it never prevents a re-download. |
| `logs\vdl.log` | Rotating log (2 MB, 3 backups). The full traceback of any crash lands here. |

> There is **no “already downloaded” skip**: the same URL always downloads
> again. `history.db` only records what happened and is what the History view
> browses.

## Bundled third-party binaries & licences

The portable folder bundles these third-party components. They are **never
committed to git** — `build/fetch_binaries.ps1` downloads and verifies them into
`vendor/` at build time (see [docs/BUILD.md](docs/BUILD.md)).

| Component | Bundled as | Upstream source | Licence (as published upstream) |
|-----------|-----------|-----------------|----------------------------------|
| **ffmpeg** / **ffprobe** | `_internal\bin\ffmpeg.exe`, `ffprobe.exe` | `yt-dlp/FFmpeg-Builds` static **GPL** Windows x64 build | **GPL** |
| **libmpv** | `_internal\libmpv\libmpv-2.dll` | `shinchiro/mpv-winbuild-cmake` (`mpv-dev`, non-v3 x86_64) | **GPL** |
| **yt-dlp** | in-process Python package | `yt-dlp/yt-dlp` | **Unlicense** |
| **yt-dlp-ejs** | `_internal\yt_dlp_ejs\` (data) | `yt-dlp/yt-dlp` (EJS challenge solver) | ships with yt-dlp |
| **deno** | `_internal\bin\deno.exe` | `denoland/deno` | **MIT** |
| **PySide6 (Essentials)** | `_internal\PySide6\` | Qt for Python | **LGPL** |
| **python-mpv** | vendored at `src/vdl/player/mpv.py` | `jaseg/python-mpv` 1.0.8 | inherits libmpv: **GPLv2-or-later** / LGPLv2.1-or-later |

The GPL builds of ffmpeg and libmpv were accepted by project decision
(open-source distribution). If you redistribute the portable folder, include the
corresponding licence texts and attribution for the GPL/LGPL components. The
vendored `python-mpv` file records its upstream version and licence in its own
header and must not be edited (re-copy it on upgrade).

### Size & budget

The unpacked `dist\VideoDownloader\` folder was **measured at ~636 MB**
(ffmpeg + ffprobe ≈ 338 MB, libmpv ≈ 115 MB, deno ≈ 97 MB, Qt ≈ 74 MB). This is
**above** the original ≤350 MB design budget; the excess is inherent to the
static-GPL ffmpeg build plus the bundled deno runtime. The figure above is the
measured value, not a target.

## Testing

The test suite is headless by default (no network, no display):

```powershell
# Unit tests
python -m pytest tests/unit -q

# Integration tests (network) — opt-in
$env:VDL_RUN_INTEGRATION = "1"
python -m pytest tests/integration -q -m integration
```

As last verified, `pytest tests/unit -q` reports **152 passed**, and the opt-in
integration run reports **3 passed** (the integration suite covers a real
download and the frozen `--selftest` smoke check).

## Not yet verified

These are **not** asserted as working — they were not exercised at the time of
writing:

- **A full run on a machine with no Python installed / not on `PATH`** — the
  portability proof (launch the copied folder on a Python-free box) has not been
  done. The frozen `--selftest` passes, but that is not the same as launching
  the window on a clean machine.
- **Live tray-balloon visibility and click-to-play** on a real desktop — the
  wiring is verified, the visible balloon is not.
- **Clipboard auto-fill from a real browser copy** — the predicate and signal
  path are verified offscreen; a real browser copy has not been confirmed.
- **Video fullscreen on a real desktop** — the chrome-hiding, transport-stays-
  visible and `Esc`-to-exit logic is verified offscreen; the actual
  video-fills-the-screen visual has not been confirmed on a live desktop.

Each of these is a manual check on a real Windows desktop; see
[docs/USAGE.md](docs/USAGE.md) for the per-feature steps.

## Documentation

- **[docs/USAGE.md](docs/USAGE.md)** — how to use each feature, step by step.
- **[docs/BUILD.md](docs/BUILD.md)** — the fetch script, the PyInstaller spec, binary mapping and exact build commands.
- **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** — black player, YouTube “JS runtime missing”, Chrome cookie lock, subprocess DLL errors, antivirus false positives.
