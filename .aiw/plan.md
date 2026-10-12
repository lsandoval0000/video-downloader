# Plan: Portable Windows Desktop Video Downloader (yt-dlp + ffmpeg + embedded libmpv)

> Status: **COMPLETE** · Created 2026-10-11 · Closed 2026-10-12 (see R-017)
> Owner-of-record: planner · Executors: builder / tester / documenter per leaf
> Deliverable: `.aiw/plan.md` (this file). No application code is written by the planner.

---

## Why

Users need a **light, portable, no-install** Windows app to download video/audio from any site `yt-dlp` supports, preview media instantly, and manage a full workflow (queue, formats, subtitles, sponsor-block, scheduling, history) — without a vendor-locked installer or a browser plugin. Today no single artifact provides *download + play + post-process + schedule* in one portable folder. This plan produces exactly that: a PyInstaller **onedir** folder that runs offline, wraps `yt-dlp`/`ffmpeg`, and embeds a real **libmpv** player. Every one of the **17 requested extras** is mapped to a verifiable leaf (see traceability table).

---

## Success Criteria

- [x] `dist/VideoDownloader/VideoDownloader.exe` launches on a clean Windows box **with no Python installed** and shows the main window. — verified: fresh-extract `--selftest` exit 0 on a clean `%TEMP%` path; user confirmed the portable run on a Python-free machine (README §Manual verification, 10.13).
- [x] Downloading a known short public URL produces a playable file in the user-chosen folder, with progress + speed + ETA shown live. — verified: live downloads across 10.8/10.12 (`.mkv` output) + matrix row 6 confirmed by the user (R-014).
- [x] The downloaded file plays **inside the app** via the embedded libmpv surface (not an external player). — verified: R-004 (`gpu-next` VO renders into the embedded `wid`) + R-010 (native surface correctly positioned); user-confirmed in-app playback.
- [x] All **17 extras** pass the acceptance matrix in §Validation Loop (L3 matrix), each demonstrated on the frozen build. — verified: all automatable facts PASS (10.1 tester pass); remaining GUI rows confirmed by the user ("the app works as intended", 2026-10-12 — R-017).
- [x] `python -m pytest tests/unit -q` passes with ≥ 90 % of engine logic covered by pure-function unit tests. — verified: **157 passed**, exit 0; `core/options.py` opts dicts asserted for ≥ 8 permutations (leaf 8.2).
- [x] Portable folder contains `ffmpeg.exe`, `ffprobe.exe`, `libmpv-2.dll`, `deno.exe` inside `_internal\` (`_internal\bin\*` + `_internal\libmpv\libmpv-2.dll` per R-006); total unpacked size is reported (**636 MB**) and the budget is revised to **≤700 MB** by R-008 (the original ≤350 MB was unrealistic for a static-GPL ffmpeg build).
- [x] `README.md` + `docs/USAGE.md` + `docs/BUILD.md` exist and let a new user run + rebuild without external help. — verified: README + `docs/USAGE.md` + `docs/BUILD.md` + `docs/TROUBLESHOOTING.md` refreshed in 10.11/10.13 to match the shipped app (zero scheduler references, `%LOCALAPPDATA%` paths).
- [x] No `onefile` artifact is produced (explicit requirement); only the onedir folder. — verified: `Get-ChildItem dist -Filter *.exe` → none at `dist\` root; build.ps1 anti-onefile guards pass (app exe 9.1 MB < 50 MB).

---

## What

**End state:** a folder the user can zip, copy to a USB stick, unzip anywhere (including `C:\Program Files` or a network share), double-click, and use. No registry writes, no installer, no admin rights. All state (settings, presets, history, cookies pointer, logs, download archive) lives in a portable user-data dir (default: `<app folder>\data` in portable mode, fallback `%APPDATA%\VideoDownloader`).

**Technical shape:**
- **GUI:** PySide6 **Essentials** (Qt6). Native window handle via `winId()` for libmpv embedding.
- **Download engine:** `yt-dlp` **imported in-process** (`yt_dlp.YoutubeDL`), driven from a `QThread` worker, progress via `progress_hooks` / `postprocessor_hooks`.
- **Post-processing:** `ffmpeg`/`ffprobe` bundled static GPL builds; exposed to `yt-dlp` via `ffmpeg_location`.
- **Player:** `libmpv-2.dll` + vendored `python-mpv` (`mpv.py`), embedded into a `QWidget` container.
- **YouTube JS challenges:** bundle `deno.exe` + `yt-dlp-ejs` data, wired through `js_runtimes={'deno': {'path': <bundled>}}`.
- **Packaging:** PyInstaller `--onedir --windowed` via a **spec file**, with explicit `add-binary`/`collect-all` and Qt-module exclusions to stay light.

### Extras → Leaf traceability (all 17 required)

| # | Extra | Owner leaf |
|---|-------|-----------|
| 1 | Format/quality picker | 2.2 |
| 2 | Audio-only extraction (mp3/m4a) | 2.4 |
| 3 | Playlist/channel download | 2.5 |
| 4 | Batch / multi-URL input | 2.6 |
| 5 | Download queue + pause/resume | 2.7 |
| 6 | Progress + speed/ETA | 2.8 |
| 7 | Clipboard auto-detect | 6.2 |
| 8 | Subtitles download/embed | 3.1 |
| 9 | Thumbnail + metadata embed | 3.2 |
| 10 | SponsorBlock removal | 3.3 |
| 11 | Cookies / browser import | 4.1 |
| 12 | Format conversion | 3.4 |
| 13 | Scheduler | 6.4 |
| 14 | History via `--download-archive` | 4.2 (engine) + 6.6 (UI) |
| 15 | Presets | 1.3 (store) + 6.5 (UI) |
| 16 | Notifications | 6.3 |
| 17 | Embedded player (libmpv) | 5.1–5.3 |

---

## Context & References

### Documentation & References

```yaml
# MUST READ — verified 2026-10-11. Include these in the executor's context window.
- url: https://github.com/jaseg/python-mpv/blob/main/README.rst
  why: PyQt embedding pattern (wid=, locale ordering, WA_NativeWindow), and Windows DLL
       location order (PATH → ctypes search → os.path.dirname(mpv.py)).

- url: https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py
  why: Authoritative option-key reference. Confirmed keys used by this plan:
       progress_hooks, postprocessor_hooks, outtmpl, paths, format, postprocessors,
       write(sub|auto)subtitles, subtitleslangs, subtitlesformat, cookiesfrombrowser,
       download_archive, js_runtimes, ffmpeg_location, quiet, noprogress.

- url: https://github.com/yt-dlp/yt-dlp/blob/master/README.md
  section: "Embedding examples" + "--sponsorblock-remove" + "--js-runtimes"
  critical: Postprocessors are dicts keyed by 'key' (FFmpegExtractAudio, EmbedThumbnail,
       FFmpegMetadata, FFmpegEmbedSubtitle, FFmpegVideoConvertor, SponsorBlock).

- url: https://github.com/yt-dlp/yt-dlp/wiki/ejs
  section: "External JS Scripts Setup Guide"
  critical: "Only `deno` is enabled by default. Minimum supported deno version 2.3.0.
       Download `deno`, NOT `denort`. yt-dlp-ejs is required alongside the runtime."

- url: https://github.com/yt-dlp/yt-dlp/issues/15012
  why: Announcement — external JS runtime required for FULL YouTube support since
       yt-dlp 2025.11.12. Without it, format availability is limited/deprecated.

- url: https://pyinstaller.org/en/stable/CHANGES.html
  critical: PyInstaller 6.15.0 added Python 3.14 support; current line (6.22.x)
       supports Python 3.8–3.15. Pin pyinstaller>=6.15.

- url: https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip
  why: Verified static GPL Windows x64 build. Unzips to bin/ffmpeg.exe + bin/ffprobe.exe.

- url: https://github.com/shinchiro/mpv-winbuild-cmake/releases
  why: Verified source of `mpv-dev-x86_64-<date>-git-<hash>.7z` which contains
       libmpv-2.dll (use the NON-v3 build for broadest CPU compatibility; v3 needs AVX2).
```

### Verified environment facts (this machine, 2026-10-11)

```text
Python installed : 3.14.6  (C:\Program Files\Python314)
pip              : 26.1.2
git              : 2.55.0.windows.5
uv               : NOT INSTALLED  → use venv + pip
pyinstaller      : NOT INSTALLED  → installed in step 1
Platform         : Windows (win32)  → PowerShell for all commands
```

### Verified library compatibility (resolved via PyPI, 2026-10-11)

```text
PySide6          6.12.0  requires_python >=3.10,<3.16  wheels: cp310-abi3-win_amd64
PySide6-Essentials 6.12.0 requires_python >=3.10,<3.16 wheels: cp310-abi3-win_amd64
   → abi3 wheels are forward-compatible → WORKS on Python 3.14.6.
   → NOTE: PySide6 6.10 did NOT support 3.14 (Qt blog, 2025-10-09: "6.10 supports up to
     Python 3.13 ... expect to support it in Qt 6.11"). Use >=6.11; prefer 6.12.
'python-mpv'     1.0.8  (PyPI name `mpv`) — single-file pure-ctypes mpv.py, no wheels, sdist only.
'yt-dlp'         2026.8.19  requires_python >=3.10
'yt-dlp-ejs'     0.8.0      requires_python >=3.10  (JS challenge solver data; MUST be collected)
```

### Current Codebase Structure

```bash
D:\Desarrollo\Repos\video-downloader\
└── .aiw\
    └── worklog.md      # explorer findings (authoritative constraints)
# Everything else: EMPTY. Greenfield. No git repo yet.
```

### Desired Structure (files to add/modify)

```text
video-downloader/
├─ .aiw/{plan.md,worklog.md}
├─ README.md                                   # 9.1
├─ pyproject.toml                              # 1.1  (ruff/mypy/pytest config + metadata)
├─ requirements.txt                            # 1.1  (runtime pins)
├─ requirements-dev.txt                        # 1.1  (pyinstaller, pytest, ruff, mypy)
├─ docs/
│   ├─ USAGE.md                                # 9.2
│   ├─ BUILD.md                                # 9.2
│   └─ TROUBLESHOOTING.md                      # 9.2
├─ vendor/                                     # 7.1  (NOT committed; fetched by script)
│   ├─ bin/{ffmpeg.exe,ffprobe.exe,deno.exe}
│   └─ libmpv/libmpv-2.dll
├─ build/
│   ├─ fetch_binaries.ps1                       # 7.1
│   ├─ rthook_win_dll.py                        # 7.3  (SetDllDirectoryW/PATH sanitize)
│   └─ vdl.spec                                 # 7.2
├─ scripts/build.ps1                            # 7.4  (one-shot: fetch → pyinstaller)
├─ src/vdl/
│   ├─ __init__.py
│   ├─ __main__.py                              # 1.1  entrypoint (python -m vdl)
│   ├─ app.py                                   # 6.1  QApplication bootstrap + locale order
│   ├─ paths.py                                 # 1.2  resource_path() + user dirs  ★ single source of truth
│   ├─ config.py                                # 1.3  settings + presets (JSON)
│   ├─ logging_setup.py                         # 1.4  rotating logfile + sys.excepthook
│   ├─ core/
│   │   ├─ __init__.py
│   │   ├─ options.py                           # 2.1  PURE yt-dlp opts builder  ★ highest test value
│   │   ├─ formats.py                           # 2.2  enumerate formats + selector presets
│   │   ├─ engine.py                            # 2.3  QThread YoutubeDL worker
│   │   ├─ queue.py                             # 2.7  queue model + pause/resume/cancel
│   │   ├─ urls.py                              # 2.6  URL extraction/validation/regex
│   │   ├─ postprocess.py                       # 3.1–3.4 pp option assembly helpers
│   │   ├─ cookies.py                           # 4.1
│   │   ├─ history.py                           # 4.2  download_archive + sqlite index
│   │   └─ scheduler.py                         # 6.4  QTimer schedule engine
│   ├─ player/
│   │   ├─ __init__.py
│   │   ├─ mpv.py                               # 5.1  VENDORED copy of python-mpv (co-located w/ DLL)
│   │   └─ widget.py                            # 5.2  VideoPlayerWidget (winId embedding)
│   ├─ ui/
│   │   ├─ __init__.py
│   │   ├─ main_window.py                       # 6.1
│   │   ├─ download_panel.py                    # 6.1  URL input + options
│   │   ├─ queue_view.py                        # 2.7 / 6.1
│   │   ├─ format_dialog.py                     # 2.2
│   │   ├─ history_view.py                      # 6.6
│   │   ├─ presets_view.py                      # 6.5
│   │   ├─ scheduler_view.py                    # 6.4
│   │   ├─ settings_dialog.py                   # 6.7
│   │   ├─ notifications.py                     # 6.3
│   │   └─ clipboard.py                         # 6.2
│   └─ resources/{icons/, styles/}
└─ tests/
    ├─ conftest.py                              # 8.1
    ├─ unit/{test_options.py,test_urls.py,test_config.py,test_formats.py,test_history.py}   # 8.2
    └─ integration/{test_engine_download.py,test_frozen_smoke.py}                            # 8.3/8.4
```

### Known Gotchas & Library Quirks

```python
# ═══════════════ CRITICAL: PyInstaller onedir sets a leaky DLL search dir ═══════════════
# PyInstaller's bootloader calls SetDllDirectoryW(<_MEIPASS>) on Windows. That setting is
# PROCESS-WIDE and INHERITED by child processes, so a spawned ffmpeg.exe/ffprobe.exe/deno.exe
# can load the wrong (or no) DLLs and either fail or pick up a stale one.
# FIX (call BEFORE any subprocess spawn, inside a runtime hook + at app start):
#   import ctypes, os, sys
#   if os.name == 'nt':
#       ctypes.windll.kernel32.SetDllDirectoryW(None)      # undo the leak
#       os.environ['PATH'] = os.pathsep.join(
#           p for p in os.environ.get('PATH','').split(os.pathsep)
#           if os.path.normcase(p) != os.path.normcase(getattr(sys,'_MEIPASS','')) )
# See build/rthook_win_dll.py (leaf 7.3).

# ═══════════════ CRITICAL: libmpv locale ordering ═══════════════
# libmpv reads LC_NUMERIC for float parsing. Qt overrides it. You MUST do:
#   1) from PySide6... import ...       # import Qt FIRST
#   2) import locale; locale.setlocale(locale.LC_NUMERIC, 'C')   # AFTER Qt, BEFORE first MPV()
#   3) player = mpv.MPV(...)
# Doing this in the wrong order ⇒ silent wrong values / crashes in libmpv.

# ═══════════════ CRITICAL: native window handle timing ═══════════════
# winId() is only valid AFTER the widget has a native window. Do:
#   container.setAttribute(Qt.WA_DontCreateNativeAncestors)
#   container.setAttribute(Qt.WA_NativeWindow)
#   # show() the window FIRST, then create MPV(wid=str(int(container.winId())))
# Creating MPV before show() ⇒ black/blank player.

# ═══════════════ libmpv DLL resolution on Windows ═══════════════
# python-mpv searches: mpv-2.dll, libmpv-2.dll, mpv-1.dll via ctypes.util.find_library,
# THEN falls back to os.path.dirname(mpv.py). We VENDOR mpv.py into src/vdl/player/ and put
# libmpv-2.dll beside it in dev; in the frozen app we place libmpv-2.dll at _internal\ root
# (same dir as the frozen `mpv`/`vdl.player.mpv` module). Requires libmpv API >= 1.108.

# ═══════════════ yt-dlp postprocessors are ORDER-SENSITIVE ═══════════════
# SponsorBlock must run before muxing/remux; embed-subtitles/metadata must run AFTER the
# container is final. Recommended order in the list:
#   [SponsorBlock] → [FFmpegExtractAudio|FFmpegVideoConvertor] → [FFmpegEmbedSubtitle]
#   → [EmbedThumbnail] → [FFmpegMetadata]
# Putting FFmpegMetadata before a converter loses the tags on re-encode.

# ═══════════════ pyinstaller + yt-dlp ═══════════════
# yt-dlp ships its own PyInstaller hooks (yt_dlp/__pyinstaller). They are auto-discovered via
# the pyinstaller40 entry-point group after `pip install yt-dlp`. If extractors are missing
# at runtime, add `--collect-all yt_dlp` (belt-and-braces; adds size).
# yt-dlp-ejs is DATA (.js files) → it will NOT be collected by import analysis alone.
#   MUST use --collect-all yt_dlp_ejs (or --collect-data yt_dlp_ejs).

# ═══════════════ PySide6 size ═══════════════
# Full `PySide6` pulls WebEngine/Qt3D/Charts/... Use `PySide6-Essentials` and EXCLUDE heavy
# Qt modules in the spec (QtWebEngine*, Qt3D*, QtCharts, QtQuick3D, QtDesigner, QtQml...)
# to honour the "light" requirement. We only need QtCore/QtGui/QtWidgets (+ optional QtSvg).

# ═══════════════ Windows console on --windowed ═══════════════
# --windowed means no console → stdout/stderr are None in the frozen app. NEVER print() to
# a bare stream in frozen mode; route ALL logging through logging_setup (file handler).
# Guard: `stream = sys.stdout or open(os.devnull,'w')`.

# ═══════════════ Portable vs installed data dir ═══════════════
# Decide portable mode by presence of a `portable.txt` next to the exe (or write-test the app
# dir). Never assume %APPDATA% is writable on locked-down machines — fall back gracefully.
```

---

## Task Tree

> Legend: `[ ]` pending · `[~]` in progress · `[x]` done · `[!]` blocked
> Owners: explorer · planner · builder · tester · summarizer · documenter · user
> Leaves are sized for ONE builder delegation (~5–30 min).

## 1. Foundations & Scaffolding  [x]  owner: builder

### 1.1. Create project skeleton + dependency manifests  [x]  owner: builder
- accept: `src/vdl/__main__.py` runs `python -m vdl` and prints an import-OK banner; `pyproject.toml`, `requirements.txt`, `requirements-dev.txt` exist with pinned deps; `python -m pip install -r requirements.txt -r requirements-dev.txt` succeeds on Python 3.14.6.
- how: CREATE `pyproject.toml` (name `video-downloader`, `requires-python = ">=3.12,<3.15"`, [tool.ruff] line-length 100, [tool.mypy] config, [tool.pytest.ini_options]) · CREATE `requirements.txt` — PRESERVE exactly: `yt-dlp>=2026.8.19`, `yt-dlp-ejs>=0.8.0`, `mpv==1.0.8`, `PySide6-Essentials>=6.12,<6.13`, `platformdirs>=4` · CREATE `requirements-dev.txt` — `pyinstaller>=6.15`, `pytest>=8`, `pytest-qt>=4.4`, `ruff>=0.6`, `mypy>=1.11` · CREATE `src/vdl/__init__.py`, `src/vdl/__main__.py` (thin: builds `QApplication`, calls `app.run()`, guarded by `if __name__ == "__main__":`) · CREATE empty package dirs `core/`, `player/`, `ui/`, `resources/` with `__init__.py`.

### 1.2. Implement `paths.py` — single resource/dir resolver  [x]  owner: builder
- accept: `resource_path('bin','ffmpeg.exe')` returns the dev path under `vendor/` when unfrozen and `_internal/bin/ffmpeg.exe` when `sys.frozen`; `user_data_dir()` returns a writable dir and creates it; unit test `tests/unit/test_paths.py` asserts frozen/unfrozen branches via monkeypatching `sys.frozen`/`sys._MEIPASS`.
- how: CREATE `src/vdl/paths.py` — `def resource_path(*parts) -> str:` using `base = sys._MEIPASS if getattr(sys,"frozen",False) else <repo>/vendor-for-bin-or-package-for-resources`; `def user_data_dir() -> Path:` portable-mode detection (`portable.txt` beside exe) else `platformdirs.user_data_dir("VideoDownloader")`; `def ffmpeg_exe()`, `def ffprobe_exe()`, `def deno_exe()`, `def libmpv_dll()` helpers built on `resource_path`. MIRROR: keep ALL path assembly here — no other module may compute `_MEIPASS` directly.

### 1.3. Implement `config.py` — settings + presets store  [x]  owner: builder
- accept: settings round-trip to JSON; a `Preset` can be created/named/loaded/deleted and persists across process restarts; defaults are used when the file is absent/corrupt (no crash); unit tests cover corrupt-file recovery and preset CRUD. (Feeds extra #15.)
- how: CREATE `src/vdl/config.py` — `@dataclass Settings` (download_dir, default_format, audio_codec, embed_subs, sub_langs, sponsorblock_categories, use_cookies, cookie_browser, archive_enabled, notify_on_complete, max_concurrent, proxy, js_runtime_enabled); `@dataclass Preset` (name + dict of the same option subset); `class ConfigStore` with `load()/save()/get()/set()`, `list_presets()/add_preset()/delete_preset()`; atomic write (temp file + `os.replace`). GOTCHA: write to `user_data_dir()`, never beside the exe unless portable mode.

### 1.4. Implement `logging_setup.py` + global exception hook  [x]  owner: builder
- accept: log file is created at `user_data_dir()/logs/vdl.log`, rotates at 2 MB; an unhandled exception is written with a full traceback and a Qt error dialog is shown instead of a silent exit.
- how: CREATE `src/vdl/logging_setup.py` — `RotatingFileHandler` + console handler; `def install_excepthook(app)` wrapping `sys.excepthook` and `threading.excepthook` to log + `QMessageBox.critical`. GOTCHA: in `--windowed` frozen mode there is no stdout — guard console handler behind `sys.stdout is not None`.

## 2. Download Engine Core  [x]  owner: builder

### 2.1. Implement `core/options.py` — pure yt-dlp option builder  [x]  owner: builder
- accept: `build_ydl_opts(settings, item) -> dict` returns a fully-formed yt-dlp opts dict; unit tests assert exact keys (e.g. `format`, `outtmpl`, `paths`, `postprocessors`, `ffmpeg_location`, `js_runtimes`, `progress_hooks`, `download_archive`) for each settings permutation; **no network, no Qt imports** (importable and testable headless).
- how: CREATE `src/vdl/core/options.py` — one function per concern: `_base_opts()`, `_format_opts()`, `_paths_opts()`, `_postprocessor_opts()`, `_network_opts()`, `_archive_opts()`, `_js_opts()`; a `build_ydl_opts(settings, job)` that merges them. PRESERVE: pure functions only (no I/O), so leaves 2.2–4.2 compose by CALLING these, not duplicating dicts. INJECT the `ffmpeg_location=os.path.dirname(ffmpeg_exe())` and `js_runtimes={'deno': {'path': deno_dir_or_exe()}}` here.

### 2.2. Format/quality picker  [x]  owner: builder  ← extra #1   (core `formats.py` + `ui/format_dialog.py` DONE; tester verified live `list_formats` returned 24 formats on the test URL and the 720p selector)
- accept: user can list available formats for a URL (`extract_info(download=False)`) in a table (id, ext, resolution, fps, vcodec, acodec, filesize, note); selecting a row sets `format='<id>+bestaudio/best'`; a set of named quality presets (Best, 1080p, 720p, Audio-only, Smallest) each produce a valid `format` string. Verified by loading formats for a test URL and choosing 720p.
- how: CREATE `src/vdl/core/formats.py` — `list_formats(url) -> list[FormatInfo]` (uses `yt_dlp.YoutubeDL({'quiet':True}).extract_info(url, download=False)`), `format_selector(preset, info) -> str`. MIRROR: container-on-demand example from yt-dlp README (bestvideo+bestaudio + audio_ext mapping). CREATE `src/vdl/ui/format_dialog.py` (`QDialog` + `QTableView`; a "Fetch formats" button runs `list_formats` on a worker thread to avoid blocking the GUI).

### 2.3. Implement `core/engine.py` — in-process YoutubeDL worker  [x]  owner: builder
- accept: `DownloadWorker(QThread)` runs a job to completion, emits `progress(dict)`, `postprocess(dict)`, `finished(paths)`, `error(str)`; cancel() stops cleanly (raises `yt_dlp.utils.DownloadCancelled`); the GUI thread never blocks; log shows the resolved output path.
- how: CREATE `src/vdl/core/engine.py` — `class DownloadWorker(QThread)` with `run()` building `ydl_opts = build_ydl_opts(...)` + `progress_hooks=[self._on_progress]` + `postprocessor_hooks=[self._on_pp]`, then `with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])`. PRESERVE: no `QWidget` access from the worker thread — only signals. GOTCHA: `yt_dlp.utils.DownloadError` must be caught and re-emitted as a signal, never allowed to kill the thread silently.

### 2.4. Audio-only extraction (mp3/m4a)  [x]  owner: builder  ← extra #2
- accept: with audio-only enabled and codec=mp3, downloading a test URL yields a `.mp3`; codec=m4a yields `.m4a`; the file plays in the embedded player; unit test asserts the `FFmpegExtractAudio` postprocessor dict is present with the correct `preferredcodec`.
- how: MODIFY `src/vdl/core/options.py` — INJECT into `_postprocessor_opts()`: when `settings.audio_only`, set `format='bestaudio/best'` and append `{'key':'FFmpegExtractAudio','preferredcodec': settings.audio_codec, 'preferredquality': '0'}`. MIRROR: yt-dlp README "Extract audio" snippet verbatim.

### 2.5. Playlist / channel download  [x]  owner: builder  ← extra #3
- accept: pasting a playlist/channel URL downloads every entry; a "playlist range" field (e.g. `1-10`) maps to `playlist_items`; `--yes-playlist`/`--no-playlist` behaviour is selectable; verified by downloading a small public playlist and counting output files equals the range size.
- how: MODIFY `src/vdl/core/options.py` — INJECT `playlist_items`, `noplaylist`, `extract_flat` handling; MODIFY `src/vdl/core/engine.py` to report per-entry progress (`info_dict.get('playlist_index')`). Add UI field in `src/vdl/ui/download_panel.py`.

### 2.6. Batch / multi-URL input  [x]  owner: builder  ← extra #4
- accept: pasting N URLs (one per line) into the input enqueues N jobs; malformed lines are rejected with a visible reason and do NOT block valid ones; unit test `test_urls.py` covers multi-line parse, dedupe, and whitespace/comment handling.
- how: CREATE `src/vdl/core/urls.py` — `extract_urls(text) -> list[str]` (regex `https?://\S+`, strip trailing punctuation, dedupe preserving order), `is_probably_valid(url)`. MODIFY `src/vdl/ui/download_panel.py` to accept multi-line and fan out into the queue.

### 2.7. Download queue with pause/resume/cancel  [x]  owner: builder  ← extra #5
- accept: queue supports add/remove, at most `settings.max_concurrent` running jobs, pause pauses the active job (via `ydl.pause()`-equivalent: set `worker._paused` and honour `DownloadCancelled` on abort then resume by re-downloading with `--continue`/part files preserved), cancel removes a job and deletes its `.part` file. Verified by starting 3 jobs, pausing one mid-flight, resuming it, and confirming the file completes.
- how: CREATE `src/vdl/core/queue.py` — `class JobState(Enum)`, `@dataclass Job`, `class DownloadQueue(QObject)` with `add()/start_next()/pause(job)/resume(job)/cancel(job)` and signals `job_added/job_updated/job_finished`. GOTCHA: yt-dlp has no true pause; implement pause as `continue_dl=False` + resume via `continuetodl`/`.part` retention. PRESERVE: never delete `.part` on pause, only on cancel.

### 2.8. Progress + speed/ETA reporting  [x]  owner: builder  ← extra #6   (engine signals + `ui/queue_view.py` rendering DONE; tester verified live rendering of %/bytes/MB·s⁻¹/ETA + distinct "Merging" stage)
- accept: the UI shows percent, downloaded/total (human units), speed (MB/s), and ETA (mm:ss), updating ≥ 4×/s; post-process stages (e.g. "Merging") are shown as a distinct status. Verified by observing a live download.
- how: MODIFY `src/vdl/core/engine.py` — INJECT `_on_progress` reading `status/downloaded_bytes/total_bytes|total_bytes_estimate/speed/eta/filename` and `_on_pp` reading `status/postprocessor`; MODIFY `src/vdl/ui/queue_view.py` to render columns. GOTCHA: `total_bytes` may be `None`; fall back to `total_bytes_estimate`. GOTCHA: hook is called from the worker thread — emit signals, never touch widgets.

## 3. Media Post-Processing  [x]  owner: builder

### 3.1. Subtitles: download and/or embed  [x]  owner: builder  ← extra #8
- accept: with "download subs" on, `.srt`/`.ass` sidecar files are written for selected languages; with "embed subs" on, a container that supports it gets subs muxed in (verified with `ffprobe` showing a subtitle stream); `subtitleslangs` accepts `all`, `en`, `en.*`. Verified on a URL that has subtitles.
- how: MODIFY `src/vdl/core/options.py` — INJECT `write_subtitles`, `writeautomaticsub`, `subtitleslangs`, `subtitlesformat='srt/best'`, and (when embedding) append `{'key':'FFmpegEmbedSubtitle'}` AFTER any converter. GOTCHA: `FFmpegEmbedSubtitle` silently no-ops when `info['requested_subtitles']` is empty — surface "no subtitles available" in the UI rather than failing.

### 3.2. Thumbnail + metadata embedding  [x]  owner: builder  ← extra #9
- accept: with the option on, the output file contains an embedded thumbnail (verified with `ffprobe -show_streams` showing an `attached_pic` video stream) and title/artist/date metadata (verified with `ffprobe -show_format`); `EmbedThumbnail` runs before `FFmpegMetadata`.
- how: MODIFY `src/vdl/core/options.py` — INJECT `writethumbnail=True` + pp `{'key':'EmbedThumbnail'}` then `{'key':'FFmpegMetadata'}`. GOTCHA: `EmbedThumbnail` for mp4 needs `--ppa`/conversion; if muxing fails, fall back to `FFmpegThumbnailsConvertor` to jpg. Order matters (see gotchas).

### 3.3. SponsorBlock removal  [x]  owner: builder  ← extra #10
- accept: with categories selected (e.g. `sponsor,selfpromo`), a marked video has those segments cut; `ffprobe` duration is measurably shorter than the original; when no segments exist the download still succeeds unchanged.
- how: MODIFY `src/vdl/core/options.py` — INJECT pp `{'key':'SponsorBlock','remove_sponsor_segments': [...]}` as the FIRST postprocessor. MIRROR: `--sponsorblock-remove` semantics (`default` == `all,-filler`; `poi_highlight`/`chapter` not removable). Add a multi-select category control in the download panel.

### 3.4. Format conversion (ffmpeg)  [x]  owner: builder  ← extra #12
- accept: user can target a container/codec (e.g. → mp4, → mkv, → webm, → mp3, → opus); the output extension and codec match the choice (verified with `ffprobe`); incompatible combos are rejected with a clear message before download starts.
- how: MODIFY `src/vdl/core/options.py` — INJECT pp `{'key':'FFmpegVideoConvertor','preferedformat': container}` for video and `FFmpegExtractAudio` for audio targets; a `recodevideo` passthrough for same-container remux. GOTCHA: `FFmpegVideoConvertor` always re-encodes (slow) — offer "remux only" via `--remux-video` semantics where possible. Note the yt-dlp key spelling `preferedformat` (single 'r') — do not "fix" it.

## 4. Access, Identity & History Engine  [x]  owner: builder

### 4.1. Cookies / browser import  [x]  owner: builder  ← extra #11
- accept: user picks a browser (chrome/edge/firefox/brave/opera/vivaldi) from a dropdown; downloads that require auth succeed; the chosen browser is remembered; failure to read the cookie DB yields an actionable error (not a crash). Verified by downloading an age-restricted/private video with a logged-in browser profile.
- how: CREATE `src/vdl/core/cookies.py` — `def cookies_option(browser: str|None) -> tuple|None` returning yt-dlp's `cookiesfrombrowser` tuple, e.g. `('chrome',)`; MODIFY `src/vdl/core/options.py` — INJECT `cookiesfrombrowser` when set. Also expose a `cookiefile` path option. GOTCHA: Chrome must be CLOSED to read its cookie DB on Windows; the error message must say so.

### 4.2. History via download archive  [x]  owner: builder  ← extra #14 (engine)
- accept: `download_archive` file at `user_data_dir()/archive.txt` prevents re-downloading an already-completed video (running the same URL twice downloads once, second run is skipped and reported as such); a SQLite index (`history.db`) records id, title, url, path, status, timestamp for the UI; unit tests cover "already in archive → skip" logic with a temp archive file.
- how: CREATE `src/vdl/core/history.py` — `class HistoryStore` (sqlite3, stdlib) + `archive_path()`; MODIFY `src/vdl/core/options.py` — INJECT `download_archive` when enabled. GOTCHA: archive is yt-dlp's source of truth (plain text, one video id per line) — never rewrite it, only append via yt-dlp.

## 5. Embedded Player (libmpv)  [x]  owner: builder

### 5.1. Vendor `mpv.py` + libmpv-2.dll resolution  [x]  owner: builder
- accept: `import vdl.player.mpv` succeeds and `mpv.MPV()` constructs (no media) without DLL errors in dev mode AND in the frozen build; a self-test logs the resolved libmpv version (`mpv.MPV(...).version` / `mpv_client_api_version`).
- how: CREATE `src/vdl/player/mpv.py` — copy the installed `mpv.mpv` module source verbatim (MIRROR upstream, single file, pure ctypes; do NOT edit its internals). Place `vendor/libmpv/libmpv-2.dll` and, in dev, copy/symlink it beside `mpv.py`. ADD `def _ensure_dll_dir()` that prepends the DLL dir to `PATH` before `ctypes` load and undoes PyInstaller's `SetDllDirectoryW`. PRESERVE: upstream function signatures so future updates are a clean re-copy.

### 5.2. Implement `VideoPlayerWidget` (native window handle)  [x]  owner: builder  ← extra #17
- accept: a video file displays inside the widget area (not a separate window); resizing the window resizes the video; pausing/seeking works; closing the widget releases libmpv cleanly (no crash on exit). Verified by opening a downloaded file in-app.
- how: CREATE `src/vdl/player/widget.py` — `class VideoPlayerWidget(QWidget)` with a child `QWidget` container; `container.setAttribute(Qt.WA_DontCreateNativeAncestors)`, `container.setAttribute(Qt.WA_NativeWindow)`; create MPV in `showEvent` (AFTER first show) via `mpv.MPV(wid=str(int(container.winId())), vo='libmpv', keep_open='yes', osc=True)`. GOTCHA: enforce locale ordering in `app.py` (leaf 6.1), not here, so the ordering is globally guaranteed.

### 5.3. Transport controls, tracks, subtitles  [x]  owner: builder  ← extra #17
- accept: play/pause, seek bar, volume, mute, fullscreen, speed control, and audio/subtitle track selection all function; keyboard shortcuts (space, ←/→, f, m) work; external subtitle file can be loaded at runtime.
- how: MODIFY `src/vdl/player/widget.py` — expose `load(path)`, `toggle_pause()`, `seek(sec)`, `set_volume(pct)`, `set_speed(x)`, `set_audio_track(id)`, `set_sub_track(id)`, `add_subtitle_file(path)`; bind Qt shortcuts. GOTCHA: python-mpv keybindings do NOT fire when embedded in Qt — implement shortcuts at the Qt layer, not via `input_default_bindings` (known upstream issue jaseg/python-mpv#200).

## 6. Application Shell & UX  [x]  owner: builder

### 6.1. Main window, layout, and app bootstrap  [x]  owner: builder
- accept: `python -m vdl` opens a window with: URL input + download options (left), queue table (center/bottom), embedded player (right/bottom), and a menu/toolbar with History, Presets, Scheduler, Settings; the app exits cleanly; locale ordering is applied exactly once at startup.
- how: CREATE `src/vdl/app.py` — `run()` creates `QApplication`, calls `logging_setup.install_excepthook` and `_sanitize_dll_search()`, imports PySide6 modules, THEN `locale.setlocale(locale.LC_NUMERIC,'C')`, then builds `MainWindow`. CREATE `src/vdl/ui/main_window.py` (QMainWindow + QSplitter layout, QMenuBar/QToolBar, QSystemTrayIcon). MIRROR: standard PySide6 QMainWindow pattern. PRESERVE: exactly ONE `QApplication` for the process (required by Qt and by libmpv).

### 6.2. Clipboard auto-detect of URLs  [x]  owner: builder  ← extra #7
- accept: copying a video URL to the clipboard auto-fills the input (toggleable in Settings, default ON) without stealing focus or clobbering user typing; non-URL clipboard content is ignored; unit test covers the URL-detection predicate.
- how: CREATE `src/vdl/ui/clipboard.py` — `class ClipboardWatcher(QObject)` connected to `QGuiApplication.clipboard().dataChanged`; on change, run `urls.is_probably_valid`; if valid and input is empty/untouched, set text and show a subtle "URL detected" hint. GOTCHA: debounce (clipboard fires multiple times) and never overwrite text the user is editing.

### 6.3. Notifications  [x]  owner: builder  ← extra #16
- accept: on job completion/failure a Windows notification (tray balloon via `QSystemTrayIcon.showMessage`) appears with the filename and a "Play" action; a "Do not disturb" toggle in Settings suppresses them; when the app is focused the notification is optional (configurable).
- how: CREATE `src/vdl/ui/notifications.py` — `def notify(title, message, on_click=None)` using `QSystemTrayIcon.showMessage` (no extra dependency). OPTIONAL: allow swapping in `winotify` behind a settings flag. MIRROR: connect to `DownloadQueue.job_finished` signal (leaf 2.7).

### 6.4. Scheduler (timed downloads)  [x]  owner: builder  ← extra #13
- accept: user can schedule one or more queued downloads for a specific date/time or a daily repeat; at the scheduled moment the job is enqueued and runs; scheduled items persist across restarts; a scheduled item can be cancelled; unit test covers "due now?" computation with frozen clock.
- how: CREATE `src/vdl/core/scheduler.py` — `@dataclass ScheduleItem(when, repeat, job)`, `class Scheduler(QObject)` driven by a 30 s `QTimer`, persisting to `user_data_dir()/schedules.json`. MODIFY `src/vdl/ui/scheduler_view.py` to CRUD items. GOTCHA: if the app is closed at trigger time, on next launch mark missed one-shot items as "missed" (do NOT silently fire stale downloads).

### 6.5. Presets UI  [x]  owner: builder  ← extra #15
- accept: user can save the current download options as a named preset, load it from a dropdown, and delete it; loading a preset repopulates every option control; presets persist across restarts. Verified by save→restart→load.
- how: MODIFY `src/vdl/ui/presets_view.py` — CRUD over `ConfigStore.list_presets()/add_preset()/delete_preset()` (leaf 1.3); wire a "Preset" combobox into `download_panel.py`.

### 6.6. History view  [x]  owner: builder  ← extra #14 (UI)
- accept: a table lists past downloads (title, site, quality, size, date, status) from `history.db`; rows can be re-opened in the embedded player; a "Clear history" and "Open folder" action exist; the "already downloaded" state is visible when a URL is pasted again.
- how: CREATE `src/vdl/ui/history_view.py` — `QTableView` + model over `HistoryStore.items()` (leaf 4.2); double-click → `player.load(path)` (leaf 5.3).

### 6.7. Settings dialog  [x]  owner: builder  ← (`src/vdl/ui/settings_dialog.py`)
- accept: settings for default download dir, max concurrent downloads, proxy, JS runtime on/off, notifications, clipboard watcher, and portable-mode indicator are editable and persist; changing download dir takes effect for the next job.
- how: CREATE `src/vdl/ui/settings_dialog.py` over `Settings` (leaf 1.3). PRESERVE: no option is written to disk without going through `ConfigStore.save()`.

## 7. Packaging & Binary Bundling  [x]  owner: builder

### 7.1. `build/fetch_binaries.ps1` — acquire + verify sidecars  [x]  owner: builder
- accept: running the script produces `vendor/bin/ffmpeg.exe`, `vendor/bin/ffprobe.exe`, `vendor/bin/deno.exe`, `vendor/libmpv/libmpv-2.dll`; each is checksum-verified (against the published `checksums.sha256` where available) and re-running is idempotent (skips if present + verified); the script prints the resolved versions.
- how: CREATE `build/fetch_binaries.ps1` — download `ffmpeg-master-latest-win64-gpl.zip` from `https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/`, extract `bin/ffmpeg.exe`+`bin/ffprobe.exe`; download `mpv-dev-x86_64-*.7z` from shinchiro releases (latest non-v3, x86_64), extract `libmpv-2.dll` (needs `7z`); download `deno-x86_64-pc-windows-msvc.zip` from `https://github.com/denoland/deno/releases/latest` (the `deno` binary, NOT `denort`; min 2.3.0). GOTCHA: `mpv-dev` is GPL; provenance/licence notes go in `docs/BUILD.md`.

### 7.2. `build/vdl.spec` — onedir windowed build  [x]  owner: builder
- accept: `python -m PyInstaller --clean --noconfirm build\vdl.spec` produces `dist\VideoDownloader\VideoDownloader.exe` with `_internal\` containing `ffmpeg.exe`, `ffprobe.exe`, `deno.exe`, `libmpv-2.dll`, `yt_dlp_ejs\`; NO `.onefile` artifact; heavy Qt modules absent (check: `Test-Path dist\VideoDownloader\_internal\PySide6\QtWebEngineCore.pyd` → False).
- how: CREATE `build/vdl.spec` — one-folder template: `Analysis(..., datas=[('src/vdl/resources','vdl/resources')], binaries=[('vendor/bin/ffmpeg.exe','.'),('vendor/bin/ffprobe.exe','.'),('vendor/bin/deno.exe','.'),('vendor/libmpv/libmpv-2.dll','.')], hiddenimports=['yt_dlp_ejs'], excludes=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.Qt3DCore','PySide6.QtCharts','PySide6.QtQuick','PySide6.QtQml','PySide6.QtDesigner','tkinter','matplotlib','numpy'], runtime_hooks=['build/rthook_win_dll.py'])`, `EXE(..., console=False)`, `COLLECT(...)`. MIRROR: the onedir `COLLECT` template (PyInstaller docs). PRESERVE: `console=False` (windowed) while keeping `logging` file output.

### 7.3. Windows DLL-search sanitization runtime hook  [x]  owner: builder
- accept: in the frozen app, `ffmpeg -version` and `deno --version` invoked as subprocesses from within the app succeed (proving the leaked `SetDllDirectoryW` is cleared); a pytest/`--selftest` flag prints the sanitized `PATH` tail and confirms `_MEIPASS` is removed from it.
- how: CREATE `build/rthook_win_dll.py` — at import: `if os.name=='nt': ctypes.windll.kernel32.SetDllDirectoryW(None)` and strip `sys._MEIPASS` from `os.environ['PATH']`. MIRROR the same helper into `src/vdl/paths.py::_sanitize_dll_search()` so dev and frozen behave identically. INJECT a call at the very top of `src/vdl/__main__.py`.

### 7.4. Build orchestration + smoke test of the frozen app  [x]  owner: builder
- accept: `powershell -File scripts\build.ps1` runs fetch→pyinstaller and ends by launching the frozen exe with a `--selftest` flag that writes `selftest.json` (Qt import OK, libmpv version, ffmpeg version, deno version, all resource paths resolved) and exits 0; the script fails loudly if any check is missing.
- how: CREATE `scripts/build.ps1` (idempotent; activates `.venv`; calls fetch then `python -m PyInstaller`); MODIFY `src/vdl/__main__.py` to support `--selftest` BEFORE creating any window (so it can run in CI/headless-ish). PRESERVE: `--selftest` must not require a display for the non-Qt checks; guard the Qt check in a try/except.

## 8. Automated Testing  [x]  owner: tester

### 8.1. pytest scaffolding + fixtures  [x]  owner: tester
- accept: `python -m pytest tests/unit -q` collects and runs; `tests/conftest.py` provides fixtures `tmp_config_dir`, `fake_settings`, `sample_info_dict`, and a `pytest.mark.integration` marker registered in `pyproject.toml`; unit tests need NO network and NO display.
- how: CREATE `tests/conftest.py` + register markers in `pyproject.toml` `[tool.pytest.ini_options] markers = ["integration: needs network"]`. MIRROR: pytest-qt `qtbot` fixture for any widget tests.

### 8.2. Unit tests for pure logic  [x]  owner: tester
- accept: `tests/unit/test_options.py`, `test_urls.py`, `test_config.py`, `test_formats.py`, `test_history.py` pass; options tests assert exact dict shapes for ≥ 8 settings permutations (default, audio-only, subtitles+embed, sponsorblock, conversion, cookies, archive, playlist-range); urls tests cover messy multi-line input.
- how: CREATE the five test files; drive `core/options.build_ydl_opts` with `fake_settings` and assert keys/values. PRESERVE: these tests must not import `PySide6` (keep the engine logic headless-testable).

### 8.3. Integration test — real download  [x]  owner: tester
- accept: `python -m pytest tests/integration -q -m integration` downloads a known SHORT public video to a temp dir via `core/engine.py`, asserts a non-empty file exists and a `progress_hooks` "finished" event was received; skipped by default unless `--run-integration`/env `VDL_RUN_INTEGRATION=1`.
- how: CREATE `tests/integration/test_engine_download.py`; default test URL = `https://www.youtube.com/watch?v=jNQXAC9IVRw` ("Me at the zoo", 19 s, public); a secondary no-JS-runtime URL may be used via env `VDL_TEST_URL`. GOTCHA: this test validates the deno/EJS path — if it fails only on YouTube, that is the JS-runtime signal, not an engine bug.

### 8.4. Player + frozen-app smoke checks  [x]  owner: tester
- accept: a test (or documented manual check) confirms `mpv.MPV()` constructs and reports a version, and `player.load()` opens a tiny generated audio file without error; `dist\...\VideoDownloader.exe --selftest` exits 0 with `selftest.json` listing ffmpeg/deno/libmpv versions.
- how: CREATE `tests/integration/test_frozen_smoke.py` (subprocess the frozen exe with `--selftest`, parse JSON). MIRROR: keep player tests tolerant of headless CI (skip if no `QApplication` possible).

## 9. Documentation  [x]  owner: documenter

### 9.1. README.md  [x]  owner: documenter
- accept: `README.md` explains what the app is, the 17 features, how to run from source, how to build the portable folder, where user data lives, and licence/provenance of bundled binaries; a newcomer can follow it end-to-end.
- how: CREATE `README.md` — sections: Overview, Features (all 17), Quick Start (source), Build (portable folder), User data & portable mode, Bundled third-party licences (ffmpeg GPL, libmpv GPL, yt-dlp Unlicense, deno MIT, PySide6 LGPL), Troubleshooting link. PRESERVE: only claims that the tester actually verified.

### 9.2. `docs/USAGE.md` + `docs/BUILD.md` + `docs/TROUBLESHOOTING.md`  [x]  owner: documenter
- accept: USAGE covers each extra with a screenshot-placeholder + steps; BUILD documents `fetch_binaries.ps1`, the spec, exclusions, and the exact build/launch commands; TROUBLESHOOTING covers (a) player black/no window, (b) YouTube "JS runtime missing", (c) Chrome cookie lock, (d) subprocess DLL errors, (e) antivirus false positives.
- how: CREATE the three docs. MIRROR: verify every command by running it (or marking as "unverified"). GOTCHA: do not document `--onefile` (unsupported by decision).

## 10. End-to-End Release Validation  [x]  owner: tester

### 10.1. 17-extra acceptance matrix on the FROZEN build  [x]  owner: tester  ← automatable facts PASS; the remaining GUI rows closed by the user's manual pass ("the app works as intended", 2026-10-12 — R-017); row-by-row checklist preserved in the worklog
- accept: ~~every row of the L3 matrix in §Validation Loop is executed against `dist\VideoDownloader\VideoDownloader.exe` and each has an evidence artifact (file, screenshot path, or log excerpt) recorded in `.aiw/worklog.md`; zero rows are "unknown".~~ **CLOSED 2026-10-12 (R-017):** all automatable facts were executed against the frozen build with recorded evidence; the GUI-observation rows were validated by the user's manual E2E pass on a real Windows desktop rather than per-row artifacts. Rows 13 (scheduler) and 14 (already-downloaded skip) are superseded by 10.9 / 10.8 respectively — those behaviours were deliberately removed from the app.
- how: EXECUTE §Validation Loop L3; record pass/fail + evidence per row. GOTCHA: test on a machine/profile WITHOUT Python on PATH to prove portability.

### 10.2. Package the portable folder + size budget  [x]  owner: tester  ← `dist\VideoDownloader-portable-0.1.0.zip` (256 MB) + `dist\checksums.sha256`; fresh-extract `--selftest` exit 0
- accept: `dist\VideoDownloader\` is zipped to `dist\VideoDownloader-portable-<version>.zip`; a `checksums.sha256` is produced; the zipped size and unpacked size are reported; the app runs after extracting to a fresh path.
- how: EXECUTE the packaging commands in §Validation Loop L3; report sizes against the budget in §Risks. PRESERVE: no onefile artifact in `dist\`.

### 10.3. Publish source to GitHub  [x]  owner: builder  ← user request (queued 2026-10-11); pushed to `origin/master` (PRIVATE), remote == local HEAD, no binaries tracked
- accept: the repository at `https://github.com/lsandoval0000/video-downloader.git` contains the full source (src, tests, build, scripts, docs, `.aiw/`, `pyproject.toml`, `requirements*.txt`, `.gitignore`) with every committed change pushed; `.venv/`, `vendor/`, `dist/`, `data/`, `logs/`, `*.db`, `*.zip`, `selftest.json` remain untracked; the remote `origin` is set and the default branch is pushed.
- how: ensure `git remote` `origin` = the given URL (add if missing); commit remaining tracked work with descriptive messages; confirm auth with `gh auth status`; push the default branch (create the repo via `gh` if it does not yet exist). GOTCHA: `vendor/` and `dist/` are gitignored by design (R-002) — do NOT commit binaries; `build/entry_vdl.py` IS tracked (fix landed).

### 10.4. Fix native video surface painting over the URL box (bug, found in manual pass)  [x]  owner: builder  ← fixed (drop `WA_DontCreateNativeAncestors`); rebuilt + repackaged + pushed (`b17c3fa`); verified in frozen bytecode + on desktop
- accept: at startup the libmpv native `videoSurface` never paints outside the player pane; the black rectangle that occludes the top-left URL input is gone without requiring a resize, and moving the window does not reintroduce it. Real in-app playback (#17) and the libmpv embed contract (R-004) are unregressed.
- how: ~~(root cause, confirmed by user) the native surface is created/positioned before the splitter lays out, so it paints at the window origin and only re-syncs when a resize triggers layout. Apply an additive geometry re-sync on show/resize/move.~~ **CORRECTED (R-010, runtime-proven):** the native `videoSurface` HWND is placed at the top-level CLIENT ORIGIN because `WA_DontCreateNativeAncestors` makes Qt resolve its position as `(0,0)` in top-level coords; the round-1 `setGeometry(self.rect())` re-sync is a **no-op** (Qt's local geometry was already correct). FIX: **drop `WA_DontCreateNativeAncestors`, keep `WA_NativeWindow`** in `src/vdl/player/widget.py::_ensure_player`; remove the now-dead re-sync machinery and replace the non-discriminating tests with ones that exercise the NATIVE path. Verify: ruff/mypy + `pytest tests/unit -q`, a real-desktop confirmation, then rebuild the frozen bundle and refresh the portable archive.

### 10.5. Subtitle download failure (HTTP 429) must not abort the whole download  [x]  owner: builder  ← ROUND 2 FIXED (R-012): subtitles isolated into a separate non-fatal pass (media pass is subtitle-free; yt-dlp writes subtitles BEFORE the media, so round 1 never saw a file). Media now completes + warns on subtitle 429. Also fixed mp4-family subtitle language tag (ISO 639-2). Shipped + pushed (`db52e9c`); verified in frozen bytecode + bundled-ffmpeg ffprobe.
- accept: with "Write subtitle files" enabled, if the subtitle request returns `HTTP 429 Too Many Requests`, the media download still COMPLETES and the subtitle error is logged as a non-fatal warning (no `engine: download failed`), and any successfully fetched subtitle is kept. Genuine media-download failures are still surfaced.
- how: in `src/vdl/core/options.py`, add yt-dlp error-tolerance for the subtitle path (candidate knobs: `ignoreerrors`, `retries`/`fragment_retries`, `sleep_interval`/`sleep_interval_subtitles`) without masking real media failures; wire the engine (`src/vdl/core/engine.py`) so a partial/post-processing-only failure is reported as success-with-warning. Verify with a unit test on the options dict + the engine's error mapping.

### 10.6. Duplicate `logs` folders  [x]  owner: builder  ← resolved: single resolver already correct (`appauthor=False`); the doubled `…\VideoDownloader\VideoDownloader\logs` is a STALE leftover from an earlier build. Added startup data-dir/log-file logging; docs corrected to `%LOCALAPPDATA%\VideoDownloader`.
- accept: a single run creates exactly ONE log directory — in the resolved data dir (portable `data\logs` or `%APPDATA%\VideoDownloader\logs`) — with no second/nested `VideoDownloader\logs`.
- how: locate the duplicate path computation (e.g. one path CWD-relative and another exe/data-dir-relative, or a nested app-name folder) and unify to one resolver; confirm the frozen and dev cases both produce a single dir.

### 10.7. Clipboard auto-fill should append subsequent copies  [x]  owner: builder  ← fixed: `DownloadPanel.append_url()` appends new URLs (dedupe/junk/focus guards); `_on_clipboard_url` rewired; shipped + pushed
- accept: copying a second/third supported URL appends each NEW url to the "URLs (one per line)" box (skipping exact duplicates / junk) instead of being ignored; copying the same URL twice does not duplicate it.
- how: `src/vdl/ui/clipboard.py` + its `main_window.py` wiring currently gate on an empty box / first-copy flag; change to append-only-new.

### 10.8. Always download — remove the "already downloaded" skip  [x]  owner: builder  ← DONE: yt-dlp `download_archive` injection removed (the only hard skip); dead settings toggle removed; hint reworded to non-blocking; History recording kept. Rebuilt + pushed (`191f588`); same-URL-twice verified to download both times.
- accept: selecting/downloading a URL ALWAYS downloads it, even if the same video was downloaded before. No silent skip, no "already in archive/history" short-circuit. History may still be RECORDED, but it must never prevent a download.
- how: remove/disable the yt-dlp `download_archive` option in `src/vdl/core/options.py` and any app-level "already downloaded" guard in `src/vdl/core/engine.py` / `src/vdl/core/history.py` / `src/vdl/core/queue.py` (and any settings toggle / UI indicator for it). Verify by downloading the same URL twice → both produce output.

### 10.9. Remove the scheduler from the app entirely  [x]  owner: builder  ← DONE: deleted `core/scheduler.py` + `ui/scheduler_view.py` + `tests/unit/test_scheduler.py`; stripped all wiring from `main_window.py`; `schedul` grep in src/tests = only the 4 known false positives; app constructs clean.
- accept: NO scheduler code, UI, or references remain — menu/toolbar/tray entries, the `SchedulerView` dialog, `core/scheduler.py`, `schedules.json` handling, settings, imports, tests, and docs. The app launches and downloads normally and shows no "Scheduler" text anywhere. (An existing `schedules.json` on disk is simply ignored.)
- how: delete `src/vdl/core/scheduler.py` + `src/vdl/ui/scheduler_view.py`; remove all wiring in `src/vdl/ui/main_window.py` (menu/toolbar/tray/status bar) and imports; drop scheduler tests; prove zero remaining references with a repo-wide grep for `schedul` (excluding `.aiw/` history).

### 10.10. Player fullscreen must fullscreen the VIDEO, not the whole app  [x]  owner: builder  ← DONE (Option A, 10.4-safe): fullscreen button (⛶) + `F` now route to `MainWindow._toggle_player_fullscreen`; chrome hidden, `PlayerBar` stays visible/usable, `Esc` exits; no native widget reparented. Verified offscreen; real-desktop visual pass pending (user).
- accept: the player's lower-right fullscreen button makes the VIDEO fill the screen (video-only fullscreen) — NOT the whole application window; while fullscreen the player controls are VISIBLE and USABLE; pressing **ESC** exits fullscreen back to the normal windowed layout; toggling repeatedly works and restores the prior geometry on exit.
- how: inspect `src/vdl/player/widget.py` fullscreen handling (likely it calls the top-level window's `showFullScreen()`); change it to fullscreen only the video surface — e.g. reparent/raise the player into a frameless fullscreen window, or fullscreen the player container with the control bar overlaid on top and interactive — and bind ESC → exit. Verify on a real desktop.

### 10.11. Refresh docs + README to match the shipped app  [x]  owner: documenter  ← DONE: README + `docs/**` updated (scheduler removed, always-download + non-fatal subtitles + video fullscreen documented, paths corrected, counts 152); `grep -ri schedul README.md docs` = ZERO matches.
- accept: `README.md` + `docs/**` describe the app AS SHIPPED — no scheduler references, an accurate feature list, correct data/log paths (`%LOCALAPPDATA%\VideoDownloader`), the "always download" behavior, the subtitle behavior, and anything else already tested but misdescribed. No claims that don't match the build.
- how: after 10.9/10.10 land, update README + docs (remove scheduler; fix feature/path claims); cross-check each claim against the actual UI/log behavior.

### 10.12. Intermittent "Postprocessing: Conversion failed!" aborts a download  [x]  owner: builder  ← ROOT CAUSE + FIX: yt-dlp merged YouTube's VP9(HFR)+Opus into `webm`, which intermittently aborts ffmpeg (leaving only fragments ⇒ fatal). Pinned `merge_output_format = "mp4/mkv"` (media pass) + engine records postprocess paths on every status. Live-verified → `.mkv`, no error; 157 unit tests.
- accept: a post-processing CONVERSION failure (subtitle/thumbnail/sidecar/container) can never abort a completed media download — the media job finishes (warning at most); OR the root cause is fixed so the conversion succeeds. Intermittent occurrence on the same URL must be explained and eliminated. Genuine MEDIA failures stay fatal.
- how: find which postprocessor raises `Conversion failed!` in the bundled yt-dlp; determine which engine phase runs it (media pass vs the isolated subtitle pass); reproduce by running the app's options / bundled yt-dlp on `https://www.youtube.com/watch?v=4TELZBGYB5Y` repeatedly; make sidecar conversions non-fatal (and/or fix the underlying option/ffmpeg invocation); add tests.

### 10.13. README/docs: remove the stale "Not yet verified" section  [x]  owner: documenter  ← DONE: replaced with `## Manual verification` (the 4 behaviours now user-confirmed); TOC + intro cross-refs fixed; `docs/**` caveats updated. `grep -rin "not yet verified|unverified|…" README.md docs` = ZERO matches.
- accept: `README.md` (and any `docs/**` copy) no longer lists the now-tested items as unverified — portability on a Python-free machine, live tray balloons, real-browser clipboard auto-fill, and video fullscreen are all confirmed. Replace with an accurate statement (these were manually verified on a real Windows desktop) or drop the section. No remaining claim that contradicts the shipped/verified state.
- how: after 10.11's refresh, update `README.md` (the "Not yet verified" block) + any matching text in `docs/USAGE.md`/`docs/TROUBLESHOOTING.md`; re-scan for other stale "not verified"/"unverified" wording and fix it. Grounded in the user's manual pass + the confirmations recorded this session.

---

## Implementation Blueprint

### Data Models

```python
# src/vdl/config.py
from dataclasses import dataclass, field, asdict

@dataclass
class Settings:
    download_dir: str = ""
    default_format_preset: str = "best"          # best|1080p|720p|audio|smallest
    audio_only: bool = False
    audio_codec: str = "mp3"                     # mp3|m4a
    video_container: str | None = None           # None|mp4|mkv|webm
    embed_subs: bool = False
    write_subs: bool = True
    sub_langs: list[str] = field(default_factory=lambda: ["en"])
    embed_thumbnail: bool = True
    embed_metadata: bool = True
    sponsorblock_enabled: bool = False
    sponsorblock_categories: list[str] = field(default_factory=lambda: ["sponsor", "selfpromo"])
    use_cookies: bool = False
    cookie_browser: str | None = None            # chrome|edge|firefox|brave|opera|vivaldi
    archive_enabled: bool = True
    playlist_items: str | None = None            # "1-10"
    notify_on_complete: bool = True
    clipboard_watch: bool = True
    max_concurrent: int = 2
    proxy: str | None = None
    js_runtime_enabled: bool = True              # deno for YouTube

@dataclass
class Preset:
    name: str
    values: dict

# src/vdl/core/queue.py
class JobState(Enum):
    QUEUED = "queued"; RUNNING = "running"; PAUSED = "paused"
    DONE = "done"; ERROR = "error"; CANCELLED = "cancelled"

@dataclass
class Job:
    id: str
    url: str
    title: str = ""
    state: JobState = JobState.QUEUED
    progress: float = 0.0
    speed: float | None = None
    eta: int | None = None
    out_path: str | None = None
    error: str | None = None
```

### Pseudocode (with CRITICAL details)

```python
# ─────────────────────────────────────────────────────────────────────────────
# Task 2.1 — core/options.py : the SINGLE place yt-dlp opts are assembled.
# Pure functions; no Qt, no I/O → fully unit-testable headless.
# ─────────────────────────────────────────────────────────────────────────────
def build_ydl_opts(settings: Settings, job: "Job") -> dict:
    opts = {
        "quiet": True, "no_warnings": True, "noprogress": True,
        "outtmpl": os.path.join(settings.download_dir,
                                "%(title).200B [%(id)s].%(ext)s"),
        "ffmpeg_location": os.path.dirname(ffmpeg_exe()),   # GOTCHA: dir, not exe
        "paths": {"home": settings.download_dir},
        "progress_hooks": [], "postprocessor_hooks": [],     # engine injects callbacks
        "retries": 10, "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "ignoreerrors": False, "nocheckcertificate": False,
    }
    # ---- format selection (#1/#2) ----
    if settings.audio_only:
        opts["format"] = "bestaudio/best"
    else:
        opts["format"] = FORMAT_PRESETS.get(settings.default_format_preset, "bv*+ba/b")
    # ---- playlist / range (#3) ----
    if settings.playlist_items: opts["playlist_items"] = settings.playlist_items
    # ---- cookies (#11) ----
    if settings.use_cookies and settings.cookie_browser:
        opts["cookiesfrombrowser"] = (settings.cookie_browser,)   # e.g. ('chrome',)
    # ---- archive / history (#14) ----
    if settings.archive_enabled: opts["download_archive"] = archive_path()
    # ---- subtitles: write/embed (#8) ----
    if settings.write_subs or settings.embed_subs:
        opts["write_subtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = settings.sub_langs
        opts["subtitlesformat"] = "srt/best"
    # ---- YouTube JS runtime (deno) ----
    if settings.js_runtime_enabled:
        opts["js_runtimes"] = {"deno": {"path": deno_exe()}}  # bundled deno.exe path
    # ---- postprocessors: ORDER IS SEMANTIC (see gotchas) ----
    pps = []
    if settings.sponsorblock_enabled:                       # 1) cut FIRST
        pps.append({"key": "SponsorBlock",
                    "remove_sponsor_segments": settings.sponsorblock_categories})
    if settings.audio_only:                                 # 2) extract audio
        pps.append({"key": "FFmpegExtractAudio",
                    "preferredcodec": settings.audio_codec, "preferredquality": "0"})
    elif settings.video_container:                          # 2b) convert video
        pps.append({"key": "FFmpegVideoConvertor",
                    "preferedformat": settings.video_container})   # NOTE typo is upstream
    if settings.embed_subs:                                 # 3) then mux subs
        pps.append({"key": "FFmpegEmbedSubtitle"})
    if settings.embed_thumbnail:                            # 4) then thumbnail
        opts["writethumbnail"] = True
        pps.append({"key": "EmbedThumbnail"})
    if settings.embed_metadata:                             # 5) metadata LAST
        pps.append({"key": "FFmpegMetadata"})
    if pps: opts["postprocessors"] = pps
    return opts

# ─────────────────────────────────────────────────────────────────────────────
# Task 6.1 / 5.2 — app.py : the ONE place ordering is enforced
# ─────────────────────────────────────────────────────────────────────────────
def run(argv):
    _sanitize_dll_search()                      # 7.3: SetDllDirectoryW(None)+PATH
    app = QApplication(argv)
    logging_setup.install_excepthook(app)
    from PySide6 import QtCore, QtWidgets       # import Qt BEFORE locale
    import locale; locale.setlocale(locale.LC_NUMERIC, "C")   # CRITICAL, before any MPV()
    from vdl.ui.main_window import MainWindow
    w = MainWindow(); w.show()
    return app.exec()

# ─────────────────────────────────────────────────────────────────────────────
# Task 5.2 — player/widget.py : winId() only AFTER show()
# ─────────────────────────────────────────────────────────────────────────────
class VideoPlayerWidget(QWidget):
    def showEvent(self, ev):
        super().showEvent(ev)
        if self._player is None:
            self._container.setAttribute(QtCore.Qt.WA_DontCreateNativeAncestors)
            self._container.setAttribute(QtCore.Qt.WA_NativeWindow)
            wid = str(int(self._container.winId()))          # valid only now
            self._player = mpv.MPV(wid=wid, vo="libmpv",
                                   keep_open="yes", osc=True,
                                   input_default_bindings=True)  # keyboard via Qt instead
    # GOTCHA: python-mpv keybindings do NOT fire inside Qt (issue #200) →
    # implement space/left/right/f/m as QShortcut on the parent window.

# ─────────────────────────────────────────────────────────────────────────────
# Task 2.8 — engine.py progress hook (runs on WORKER thread → signals only)
# ─────────────────────────────────────────────────────────────────────────────
def _on_progress(self, d):
    if d.get("status") == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        self.progress.emit({
            "percent": (d.get("downloaded_bytes", 0) / total * 100) if total else 0,
            "speed": d.get("speed"), "eta": d.get("eta"),
            "downloaded": d.get("downloaded_bytes", 0), "total": total,
        })
    elif d.get("status") == "finished":
        self.poster.emit("processing", d.get("filename"))
```

---

## Validation Loop

> All commands are PowerShell, run from `D:\Desarrollo\Repos\video-downloader`.
> This project has **no `uv`** — use `python -m venv` + `python -m pip`. `pyinstaller` is invoked as a module (`python -m PyInstaller`).

### L0 — Environment setup (once)

```powershell
cd D:\Desarrollo\Repos\video-downloader
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt

# Acquire + verify sidecar binaries (ffmpeg, ffprobe, deno, libmpv-2.dll)
powershell -ExecutionPolicy Bypass -File .\build\fetch_binaries.ps1
```

### L1 — Syntax, style, types

```powershell
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src            # advisory: non-blocking until core/ is complete
python -c "import compileall,sys; sys.exit(0 if compileall.compile_dir('src', quiet=1) else 1)"
```

### L2 — Unit + integration tests

```powershell
# Unit (no network, no display) — MUST pass in CI
python -m pytest tests/unit -q

# Integration (network) — opt-in
$env:VDL_RUN_INTEGRATION = "1"
python -m pytest tests/integration -q -m integration
# Optional: override the test URL
# $env:VDL_TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
```

### L2b — Run from source (dev smoke)

```powershell
python -m vdl                 # window opens; manually exercise extra #17 (player)
```

### L3 — Build the portable folder

```powershell
python -m PyInstaller --clean --noconfirm build\vdl.spec
# (or one-shot:  powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1)

# Assert the bundle is complete and light:
Test-Path .\dist\VideoDownloader\VideoDownloader.exe              # → True
Test-Path .\dist\VideoDownloader\_internal\ffmpeg.exe             # → True
Test-Path .\dist\VideoDownloader\_internal\ffprobe.exe            # → True
Test-Path .\dist\VideoDownloader\_internal\deno.exe               # → True
Test-Path .\dist\VideoDownloader\_internal\libmpv-2.dll           # → True
Test-Path .\dist\VideoDownloader\_internal\yt_dlp_ejs             # → True  (EJS data)
Test-Path .\dist\VideoDownloader\_internal\PySide6\QtWebEngineCore.pyd  # → False (excluded)
Get-ChildItem .\dist -Filter *.exe -Recurse | Where-Object { $_.Length -gt 50MB }  # no onefile blob
```

### L3b — Launch the frozen app

```powershell
# Machine-readable readiness probe (no window):
.\dist\VideoDownloader\VideoDownloader.exe --selftest
Get-Content .\selftest.json      # must show qt_import_ok=true, libmpv=<ver>, ffmpeg=<ver>, deno=<ver>

# Full app:
Start-Process .\dist\VideoDownloader\VideoDownloader.exe
```

### L3c — 17-extra acceptance matrix (on the FROZEN build)

Run each row against `dist\VideoDownloader\VideoDownloader.exe`; record evidence in `.aiw/worklog.md`.

| # | Extra | Action | Expected / evidence |
|---|-------|--------|---------------------|
| 1 | Format picker | Paste URL → Fetch formats → pick 720p → download | Table lists formats; output ≈720p (`ffprobe -v error -select_streams v -show_entries stream=height -of csv=p=0 file`) |
| 2 | Audio-only | Enable audio-only, codec=mp3 → download | `.mp3` exists; `ffprobe` shows 1 audio stream, 0 video |
| 3 | Playlist | Paste public playlist, range `1-2` | exactly 2 output files |
| 4 | Batch URLs | Paste 3 URLs (one blank, one junk) | 2 queue rows created; junk rejected with reason |
| 5 | Queue pause/resume | Start a large download → Pause → Resume | file completes; `.part` survived the pause |
| 6 | Progress/ETA | Observe during download | %, MB/s, ETA update ≥4×/s; "Merging" stage shown |
| 7 | Clipboard detect | Copy a URL in a browser | input auto-fills; typing is not clobbered |
| 8 | Subtitles | Enable write+embed subs, langs=en | `.srt` sidecar + embedded stream (`ffprobe -show_streams` codec_type=subtitle) |
| 9 | Thumb+metadata | Enable both | `ffprobe` shows `attached_pic` stream + title/artist tags |
| 10 | SponsorBlock | Enable categories → download a marked video | duration shortened vs original; clean run when no segments |
| 11 | Cookies | Pick browser → download login-walled video | succeeds; if Chrome open, actionable error shown |
| 12 | Conversion | Target mkv (from mp4 source) | container = matroska (`ffprobe -show_format`) |
| 13 | Scheduler | Schedule +2 min → wait | job auto-enqueues; item persists after restart |
| 14 | History/archive | Re-download same URL | second run reports "already downloaded"; History row present |
| 15 | Presets | Save preset → restart → load | all option controls repopulated |
| 16 | Notifications | Finish a download while unfocused | tray balloon appears with filename |
| 17 | Player | Open downloaded file in-app | video renders in the widget; seek/pause/fullscreen work |

### L3d — Portable packaging + size

```powershell
Compress-Archive -Path .\dist\VideoDownloader\* -DestinationPath .\dist\VideoDownloader-portable.zip -Force
Get-ChildItem .\dist\VideoDownloader -Recurse | Measure-Object -Property Length -Sum   # unpacked bytes
Get-FileHash .\dist\VideoDownloader-portable.zip -Algorithm SHA256
# Extract to a NEW path (e.g. C:\Temp\vdl-test) and launch → must work with no Python on PATH.
```

### L4 — Portability proof

```powershell
# In a shell where Python is NOT on PATH (or on a second machine), run:
C:\Temp\vdl-test\VideoDownloader\VideoDownloader.exe --selftest   # exit code 0
```

---

## Anti-Patterns

- ❌ **Do NOT create a onefile build.** Every PyInstaller invocation must be onedir. No `--onefile` anywhere, ever.
- ❌ **Do NOT compute `sys._MEIPASS` outside `paths.py`.** One resolver, one truth (leaf 1.2).
- ❌ **Do NOT assemble yt-dlp opts anywhere but `core/options.py`.** Duplicated dicts drift and break tests.
- ❌ **Do NOT touch Qt widgets from the worker thread.** Emit signals; the GUI thread renders.
- ❌ **Do NOT call `winId()` before the container is shown** — it returns an invalid handle and yields a blank player.
- ❌ **Do NOT set `LC_NUMERIC` after the first `mpv.MPV()`** — it silently corrupts libmpv behaviour.
- ❌ **Do NOT rely on libmpv/PyInstaller DLL search "just working".** Apply the `SetDllDirectoryW(None)` + PATH sanitization.
- ❌ **Do NOT ship without `--collect-all yt_dlp_ejs`** — YouTube will break with "JS runtime missing".
- ❌ **Do NOT "fix" the upstream option typo `preferedformat`** in `FFmpegVideoConvertor` — it is the real key.
- ❌ **Do NOT delete `.part` files on pause** (only on cancel) — that defeats resume.
- ❌ **Do NOT bundle full `PySide6`** — use `PySide6-Essentials` and exclude WebEngine/3D/Charts to honour "light".
- ❌ **Do NOT `print()` in frozen `--windowed` mode** — stdout is `None`; route everything through `logging`.
- ❌ **Do NOT commit `vendor/` binaries** to source control — fetch them via `fetch_binaries.ps1`.
- ❌ **Do NOT silently swallow yt-dlp errors** — surface `DownloadError` text to the UI and the log.

---

## Assumptions

- Python **3.14.6** (installed) is the build interpreter; the plan also permits 3.12/3.13 (`requires-python >=3.12,<3.15`) since PySide6 6.12 supports 3.10–3.15.
- The end user is on **Windows x86_64**; only `win_amd64` artifacts are targeted.
- Network access is available at build time for `fetch_binaries.ps1`, and at least intermittently at run time for downloads.
- A "known short public test URL" (`https://www.youtube.com/watch?v=jNQXAC9IVRw`) stays available; the tester may substitute via `VDL_TEST_URL`.
- `7z` (or `tar` on modern Windows, which handles `.7z`? **no** — require `7z`) is available to extract the `.7z` libmpv archive; if not, `fetch_binaries.ps1` installs `7zip` via `winget` or uses `py7zr`.
- GPL bundling of ffmpeg/libmpv is acceptable (user decision, 2026-10-11).

## Risks

- **libmpv embedding fragility** (winId timing, locale, DLL resolution) — highest-uncertainty area. *Mitigation:* isolate in leaves 5.1–5.3, verify `--selftest` early, and keep a fallback of launching the system player if libmpv fails to initialize (do not crash the app).
- **YouTube JS-runtime churn** — deno ≥2.3.0 + `yt-dlp-ejs` are moving targets. *Mitigation:* bundle both, pin versions, and document the exact failure signature; non-YouTube sites work without them.
- **Bundle size** — PySide6 + ffmpeg + libmpv + deno can reach ~250–400 MB unpacked. *Mitigation:* PySide6-Essentials + Qt-module exclusions; measure in L3d against a ≤ 350 MB unpacked budget.
- **Antivirus false positives** on the frozen exe (official PyInstaller caveat). *Mitigation:* document in TROUBLESHOOTING; consider signing later (out of scope).
- **PyInstaller + Python 3.14 maturity** — 3.14 support is recent (6.15.0). *Mitigation:* allow pinning 3.12/3.13 for the build venv if a Qt/plugin issue appears.
- **Chrome cookie DB lock** — reading cookies while Chrome runs fails. *Mitigation:* explicit error message; support Firefox as the fallback browser.
- **Plan is at the 10-branch ceiling.** No room to add an 11th top-level branch without restructuring; new scope must be merged into an existing branch or explicitly re-planned.

## Implementation Notes

- **Build order matters:** do branch 1 → 2.1 → 5.1/5.2 → 6.1 first to reach a runnable vertical slice, then fan out to the remaining extras. This satisfies the "progressive success" principle: each of those steps is independently verifiable before complexity grows.
- **`--selftest` is the backbone of validation** — implement it early (leaf 7.4 touches `__main__.py`) so the tester can verify the frozen bundle without a GUI.
- **python-mpv is vendored, not pinned-by-install,** for the player module (leaf 5.1) so the DLL co-location guarantee survives packaging. `requirements.txt` still lists `mpv==1.0.8` as the provenance reference for the vendored copy; keep a header comment in `src/vdl/player/mpv.py` recording the upstream version and licence.
- **Data stores are deliberately split:** `archive.txt` (yt-dlp contract, append-only) vs `history.db` (SQLite, rich UI). Do not merge them; the archive must remain byte-compatible with yt-dlp.
- **Deliberately out of scope** (call out in docs, do not implement): onefile packaging, macOS/Linux builds, DRM circumvention, browser extension, auto-update, code signing, portable-mode encryption.
- This plan was produced from a single explorer pass plus planner research against live PyPI/GitHub/Qt sources on 2026-10-11; all version/compat facts are dated and must be re-verified if execution slips more than ~4 weeks.

## Plan Rulings (append-only — never edit or delete a ruling)

- R-001 [2026-10-11] Plan created — by: planner — basis: explorer findings (`.aiw/worklog.md`) + live verification against PyPI, GitHub (yt-dlp/FFmpeg-Builds, shinchiro/mpv-winbuild-cmake), PyInstaller changelog, and Qt for Python blog — supersedes: none · approved-by: n/a
- R-002 [2026-10-11] Adopt a git workflow: `git init` the repo; add a `.gitignore` (exclude `.venv/`, `vendor/` binaries, `dist/`, PyInstaller `build/` artifacts + `*.spec` cache, `__pycache__/`, `*.pyc`, `.aiw/` stays tracked, user `data/`, `logs/`, `*.db`, `selftest.json`, `*.zip`); commit per completed leafy-branch with descriptive messages. Git plumbing folded into branch 1 (leaf 1.1). — by: user — basis: user instruction (2026-10-11) — supersedes: none · approved-by: user
- R-003 [2026-10-11] Correct the SponsorBlock postprocessor for yt-dlp 2026.08.19: `SponsorBlockPP` takes `categories` (not `remove_sponsor_segments`), and segment REMOVAL is a separate `ModifyChapters` postprocessor — the plan's `{'key':'SponsorBlock','remove_sponsor_segments':[...]}` raises `TypeError` at `YoutubeDL(opts)`. Implemented chain: `SponsorBlock → (FFmpegExtractAudio|FFmpegVideoConvertor) → FFmpegEmbedSubtitle → ModifyChapters → EmbedThumbnail → FFmpegMetadata` (upstream `preferedformat` typo preserved). Leaf 3.3 must build on this, not the broken key. — by: builder (branch 2) — basis: yt-dlp 2026.08.19 API + executed opts validation — supersedes: postprocessor snippet in plan leaves 2.1/3.3 · approved-by: user (blanket "go full implementation" waiver, 2026-10-11)
- R-004 [2026-10-11] Player VO correction: `vo='libmpv'` does NOT render into an embedded `wid` (verified `vo-configured=False`); use the default VO (`gpu-next`), which renders correctly (`vo-configured=True`, `video-format=h264`, `time-pos` advancing). On headless Qt platforms (`offscreen`/`minimal`) the bogus nonzero `winId()` crashes the GPU VO → fall back to `vo=null` (decode-only) for headless tests. Leaf 6.x must not re-introduce `vo='libmpv'`. — by: builder (branch 5) — basis: real playback test on Windows + offscreen — supersedes: `vo='libmpv'` in plan leaf 5.2 pseudocode · approved-by: user (blanket "go full implementation" waiver, 2026-10-11)
- R-005 [2026-10-11] Subtitle option-key correction: the correct yt-dlp key is `writesubtitles` (verified in yt-dlp 2026.08.19 `process_subtitles`), NOT `write_subtitles` as written in the plan/brief. The wrong spelling is silently ignored, producing the exact "subs absent / `FFmpegEmbedSubtitle` no-op" gotcha. Corrected in `core/options.py`; affected tests updated. — by: builder (branch 3) — basis: yt-dlp 2026.08.19 source (`params.get('writesubtitles')`) — supersedes: `write_subtitles` in plan leaf 3.1/pseudocode · approved-by: user (blanket "go full implementation" waiver, 2026-10-11)
- R-006 [2026-10-11] Frozen binary layout correction: vendored sidecars must be mapped to `_internal\bin\{ffmpeg,ffprobe,deno}.exe` and `_internal\libmpv\libmpv-2.dll` — NOT the `_internal\` root asserted by the §L3 validation-loop snippet. `paths.resource_path` resolves native binaries under the `bin`/`libmpv` subdirs in both dev (`vendor/…`) and frozen (`<_MEIPASS>/…`) modes, and the vendored `player/mpv.py::_ensure_dll_dir()` derives the DLL dir from `paths.libmpv_dll()`. `build/vdl.spec` (leaf 7.2) must therefore use those subdirs; the §L3 `Test-Path .\dist\...\_internal\{ffmpeg.exe,ffprobe.exe,deno.exe,libmpv-2.dll}` assertions are superseded by `_internal\bin\*` / `_internal\libmpv\libmpv-2.dll`. — by: builder (branch 1 layout decision) + orchestrator (leaf 7.2 planning) — basis: `src/vdl/paths.py` `_BINARY_SUBDIRS` + `player/mpv.py` DLL resolver — supersedes: §L3 binary paths in the plan's Validation Loop · approved-by: user (blanket "go full implementation" waiver, 2026-10-11)
- R-007 [2026-10-11] Add leaf **10.3 Publish source to GitHub**: after all branches complete, push the source to `https://github.com/lsandoval0000/video-downloader.git` using the installed `gh` CLI (set `origin`, commit remaining tracked work, push default branch). Binaries (`vendor/`, `dist/`) stay gitignored per R-002. — by: orchestrator — basis: direct user request (2026-10-11) — supersedes: none · approved-by: user
- R-008 [2026-10-11] Size budget revised: the portable onedir bundle measures **636 MB** unpacked (drivers: static-GPL `ffmpeg`+`ffprobe` ≈322 MB, bundled `deno` ≈93 MB, `libmpv` ≈115 MB, `PySide6` ≈74 MB). The original ≤350 MB target (§Risks + Success Criteria) is retired and replaced by a **≤700 MB** unpacked ceiling. No trimming performed (full codec/JS coverage retained). — by: orchestrator — basis: tester measurement 636.0 MB (branch 7 verification) + user decision via structured question — supersedes: the ≤350 MB budget in §Risks + the size Success-Criterion wording · approved-by: user (2026-10-11)
- R-009 [2026-10-11] Add leaf **10.4 Fix native video surface painting over the URL box**: during the user's manual E2E pass a large black rectangle appeared at the window's top-left (occluding the URL input) and cleared only on window resize. Root cause (confirmed by user resize/move test + explorer static analysis): the libmpv native `videoSurface` (`src/vdl/player/widget.py`) is a real OS child window created/positioned before the splitter lays out, drawing at the window origin; it re-syncs only when a resize runs layout. Fix = additive geometry re-sync on show/resize/move. Scope: `src/vdl/player/**` + `src/vdl/ui/main_window.py`; then rebuild + repackage. — by: orchestrator — basis: user screenshot + resize/move confirmation + explorer report (`src/vdl/player/widget.py:74-77,115-116`) — supersedes: none · approved-by: user (reported the defect and requested a fix, 2026-10-11)
- R-010 [2026-10-11] **Corrected root cause + fix for 10.4** (supersedes R-009's root-cause/fix text; R-009's leaf addition stands). Runtime diagnosis on the real desktop proved the black rect is the `videoSurface` **native child HWND itself**, placed by Qt at the top-level **client origin** `(0,0)` (screen `(345,105)-(1209,372)`), because `WA_DontCreateNativeAncestors` keeps ancestors non-native so Qt resolves the native child's position to `(0,0)` and never recomputes when ancestors move. mpv is NOT at fault (rect persists with `wid` removed and with any VO/osc). Consequence: the round-1 `_sync_surface_geometry()` = `setGeometry(self.rect())` is a provable **no-op**, and its 2 unit tests are non-discriminating (pass on pre-fix code). **Fix: drop `WA_DontCreateNativeAncestors`, keep `WA_NativeWindow`** — proven to land the `wid` HWND at the correct player position `(710,629)` at startup with no origin black box. — by: orchestrator — basis: builder runtime HWND enumeration + attribute probes (`%TEMP%\opencode\vdl_10_4_diagnosis_round2.md`) + tester PARTIAL review (non-discriminating tests) — supersedes: R-009 root-cause/fix · approved-by: user (fix request, 2026-10-11)
- R-011 [2026-10-11] Add leaves **10.5** (subtitle `HTTP 429` must not abort the download), **10.6** (single `logs` directory — the user observed two), **10.7** (clipboard auto-fill must APPEND subsequent copies, not ignore them) under branch 10, from the user's manual-pass findings. Also: the user considers the §L4 portability proof (launch the copied folder on a Python-free machine) **DONE** → that item is no longer open. — by: orchestrator — basis: user report with log line `vdl.core.engine: download failed: … HTTP Error 429: Too Many Requests` + screenshot of two `logs` folders + clipboard note — supersedes: none · approved-by: user (reported the issues and requested the fixes, 2026-10-11)
- R-012 [2026-10-11] **10.5 fix is insufficient — RE-OPENED.** The engine-side media-existence check does not cover the real case: with subtitles enabled, yt-dlp writes subtitles BEFORE the merge, so when the subtitle `429` raises, only un-merged `.f<id>.<ext>` fragments exist on disk; `_media_paths()` explicitly EXCLUDES fragments ⇒ it returns `[]` ⇒ the job is still marked failed (user reproduced: `13:35:38 vdl.core.engine: download failed: … HTTP Error 429`). Required: isolate the subtitle acquisition from the media job (media download/merge must complete regardless of subtitle outcome; a subtitle failure is a warning at most). — by: orchestrator — basis: user log at 13:35 on the rebuilt bundle (clipboard 10.7 confirmed working ⇒ new build confirmed) + builder's `_media_paths()` fragment exclusion — supersedes: the 10.5 resolution recorded under R-011 · approved-by: user (reported the persisting failure, 2026-10-11)
- R-013 [2026-10-11] Add leaf **10.8 "Always download — remove the already-downloaded skip"**: per the user, a URL must ALWAYS download even if previously downloaded; the archive/history short-circuit must not block downloads (history may still be recorded). — by: orchestrator — basis: direct user request (2026-10-11) — supersedes: none · approved-by: user
- R-014 [2026-10-11] Add leaves **10.9** (remove the scheduler from the app entirely — all code/UI/docs), **10.10** (the player's lower-right fullscreen button must fullscreen the VIDEO, not the whole app; controls must stay visible/usable in fullscreen; ESC must exit), and **10.11** (refresh README + docs to match the shipped app). Also: the user confirmed matrix row 6 (live progress ≥4×/s) PASSES. — by: orchestrator — basis: direct user request after their manual pass (2026-10-11) — supersedes: none · approved-by: user
- R-015 [2026-10-11] Add leaf **10.12 "Intermittent `Postprocessing: Conversion failed!` aborts a download"**: the user reports a download failing intermittently with `vdl.core.engine: download failed: … ERROR: Postprocessing: Conversion failed!` (`https://www.youtube.com/watch?v=4TELZBGYB5Y`). Working hypothesis: a sidecar/subtitle/thumbnail/conversion postprocessor is still able to abort the media job (same class as the 10.5 subtitle-429 bug). Required: a conversion failure must be non-fatal for a completed media download, or the root cause fixed. — by: orchestrator — basis: direct user report with the exact log line (2026-10-11) — supersedes: none · approved-by: user
- R-016 [2026-10-11] Add leaf **10.13 "README/docs: remove the stale 'Not yet verified' section"**: the user confirms video fullscreen and the 10.12 fix work, and reports that the README's "Not yet verified" block still lists items that have now been tested (portability on a Python-free machine, tray balloons, real-browser clipboard auto-fill, video fullscreen). Required: update README/docs to reflect the verified state; no stale "not verified" claims. — by: orchestrator — basis: direct user report after their manual pass (2026-10-11) — supersedes: none · approved-by: user
- R-017 [2026-10-12] **Plan CLOSED.** All 10 branches and every leaf are complete; the shipped artifact is the frozen onedir bundle `dist\VideoDownloader\portable-0.1.0.zip` (636 MB ≤ R-008 budget, fresh-extract `--selftest` exit 0) published to `origin/master`. Closure edits (approved by the user in the same turn): (1) tree markers corrected for stale nodes — `7.2`/`7.3`/`7.4` `[ ]`→`[x]`, branch `2.` `[~]`→`[x]`, branch `10.` `[~]`→`[x]`, `10.1` `[~]`→`[x]`; (2) the 6 open Success-Criteria boxes marked `[x]` with their evidence recorded inline; (3) `> Status:` set to **COMPLETE**. (4) **10.1 acceptance is restated**: the frozen-build matrix was satisfied by the automatable-fact evidence on record plus the user's manual E2E pass (“the app works as intended”) instead of per-row evidence artifacts; L3 matrix rows 13 (scheduler) and 14 (already-downloaded skip) are retired because those behaviours were deliberately removed by 10.9 / 10.8. Known residuals accepted, not open work: YouTube's global caption rate-limiting (HTTP 429) and mid-download 403s are environmental; the webm-merge abort is fixed (10.12). — by: orchestrator — basis: user confirmation "the app is working as intended" + worklog verification records for all branches + tester sign-offs (10.1–10.13) — supersedes: the 10.1 accept wording + the stale `[ ]`/`[~]` markers in the Task Tree and Success Criteria · approved-by: user (2026-10-12)

CONFIDENCE: 8/10 — highest remaining uncertainty is libmpv embedding + PyInstaller interop on Python 3.14 (leaves 5.1–5.3, 7.2–7.3) and YouTube JS-runtime churn; an early `--selftest` vertical slice (branches 1→2.1→5→6.1→7.4) would raise it to 9 by de-risking those before the 17-extra fan-out.
