# VideoDownloader — Troubleshooting

Fixes for the most common problems. Most of them can be diagnosed from the app’s
log file.

**First stop: the log.** Every process writes to a rotating log at
`<user-data-dir>\logs\vdl.log` — see
[User data & portable mode](../README.md#user-data--portable-mode) for where the
user-data directory is (next to the app when `portable.txt` is present, otherwise
`%LOCALAPPDATA%\VideoDownloader`). The exact resolved directory is logged at the
top of every run. An unhandled crash’s full traceback lands there and
is also shown in an error dialog.

**Second stop: the self-test.** The built app can probe itself without a window:

```powershell
Start-Process .\dist\VideoDownloader\VideoDownloader.exe --selftest -Wait -NoNewWindow
Get-Content .\selftest.json
```

It reports the resolved `libmpv` / `ffmpeg` / `ffprobe` / `deno` versions, the
four resource paths, and `dll_search.meipass_in_path`.

---

## Contents

1. [The player is black / shows no window](#1-the-player-is-black--shows-no-window)
2. [YouTube: “JS runtime missing”](#2-youtube-js-runtime-missing)
3. [Chrome / Edge / Brave cookie database is locked](#3-chrome--edge--brave-cookie-database-is-locked)
4. [Subprocess DLL errors (ffmpeg / ffprobe / deno fail to start)](#4-subprocess-dll-errors-ffmpeg--ffprobe--deno-fail-to-start)
5. [Antivirus false positives](#5-antivirus-false-positives)

---

## 1. The player is black / shows no window

**Symptoms.** The player pane is black, the video never appears, or playback
starts but nothing renders in the widget.

**Background.** Video renders inside the widget by handing libmpv the container’s
native window handle (`wid`). That handle is only valid **after** the widget has
been shown, so the app creates libmpv on first show, not at construction. The app
also lets libmpv pick its **default** video output; it deliberately does **not**
force `vo=libmpv`, which is the render-API output and does **not** draw into an
embedded `wid`.

**Things to check**

1. **Give the window a moment.** libmpv is created lazily on the first show; a
   file loaded before the player exists is queued and loaded once the player is
   ready (see `logs\vdl.log` — look for “queued media until player exists”).
2. **Resize the window** once, then reopen the file. A stale/zero-sized native
   surface can leave the buffer black.
3. **Confirm libmpv loaded at all.** Run `--selftest`; `libmpv_version` must be a
   real string (e.g. `mpv v0.41.0-…`) and `libmpv.ok` must be `true`. If it is
   `false`, the bundle is missing `_internal\libmpv\libmpv-2.dll`.
4. **Known benign noise.** Under `pytest`/`faulthandler`, libmpv’s event thread
   can log a first-chance Windows exception (`0xe24c4a02`) that faulthandler
   renders as “Windows fatal exception”. This is a libmpv artefact, not a crash —
   the process exits `0` and playback works. Do not treat it as a failure.
5. **Remote-desktop / offscreen platforms.** On a headless Qt platform
   (`offscreen`/`minimal`) or a session with no real GPU surface, the widget
   falls back to a decode-only video output (`vo=null`): media loads and decodes,
   but nothing is drawn. Real rendering requires a real desktop session.

If none of the above helps, capture the tail of `logs\vdl.log` (look for
`libmpv ready:` / `libmpv terminated`) when reporting the issue.

## 2. YouTube: “JS runtime missing”

**Symptoms.** Downloads from YouTube fail (or only offer limited/legacy formats)
with an error mentioning a missing JS runtime. Non-YouTube sites work fine.

**Background.** Since yt-dlp 2025.11.12, full YouTube support requires an external
JavaScript runtime plus the `yt-dlp-ejs` challenge-solver data. VideoDownloader
bundles both: `deno` at `_internal\bin\deno.exe` and the EJS data at
`_internal\yt_dlp_ejs\`, wired in through `js_runtimes={'deno': {...}}`.

**Things to check**

1. **The bundle is complete.** Run `--selftest` and confirm:
   - `deno_version` is a real string (deno **≥ 2.3.0** is required), and
   - `_internal\yt_dlp_ejs\` exists next to `VideoDownloader.exe`.
2. **The JS runtime is enabled.** In **Settings → Network & access**, ensure
   *Enable bundled deno JS runtime (YouTube)* is checked (default: on). If you
   disabled it, YouTube format availability will be reduced.
3. **The EJS data was collected.** If you built the bundle yourself, make sure
   `yt-dlp-ejs` is installed in the build venv (`pip install -r requirements.txt`)
   — the spec collects it via `collect_all("yt_dlp_ejs")`. Without it the bundle
   will be missing the `.js` solver files.
4. **It is not an engine bug if only YouTube fails.** A failure isolated to
   YouTube is the JS-runtime signal; other sites do not need it.

## 3. Chrome / Edge / Brave cookie database is locked

**Symptoms.** Importing cookies from Chrome (or another Chromium browser) fails
with a “failed to load cookies” error, so login-walled / age-restricted / private
videos won’t download.

**Cause.** Chromium-family browsers **lock their cookie database while running**,
so yt-dlp cannot read it. The app turns the opaque error into an actionable
message that says so.

**Fixes**

1. **Close the browser completely** — including background processes. Check Task
   Manager for lingering `chrome.exe` / `msedge.exe` / `brave.exe` processes, then
   retry the download.
2. **Use a `cookies.txt` file instead.** Export cookies with a browser extension,
   then set the path in **Settings → Network & access → Cookie file**. With
   *Use cookies* enabled, yt-dlp can read a cookie file without touching the live
   database.
3. **Prefer Firefox** if it is an option — it does not lock its cookie store the
   way Chromium browsers do.

## 4. Subprocess DLL errors (ffmpeg / ffprobe / deno fail to start)

**Symptoms.** Post-processing fails, downloads “finish” without a playable file,
or the log shows `ffmpeg`/`ffprobe`/`deno` failing to launch — sometimes with a
missing-DLL error.

**Cause.** PyInstaller’s Windows bootloader sets a **process-wide** DLL search
directory (`SetDllDirectoryW(<_MEIPASS>)`) and prepends `<_MEIPASS>` to `PATH`.
Both are inherited by child processes, so a spawned `ffmpeg.exe` / `ffprobe.exe` /
`deno.exe` can resolve the wrong (or a stale) DLL, or fail to start. The app ships
a runtime hook that clears the DLL directory and strips `<_MEIPASS>` from `PATH`
before any subprocess runs.

**Things to check**

1. **Verify the hook ran.** Run `--selftest`; `dll_search.meipass_in_path` must be
   `false`. If it is `true`, the runtime hook did not run — rebuild with the
   current `build/vdl.spec` (it lists `build/rthook_win_dll.py` as a runtime hook).
2. **Confirm the sidecars exist** at `_internal\bin\{ffmpeg,ffprobe,deno}.exe` and
   `_internal\libmpv\libmpv-2.dll`. If any is missing the bundle is incomplete —
   re-run `build\fetch_binaries.ps1` and rebuild.
3. **The self-test already spawns the sidecars** (`ffmpeg -version`,
   `ffprobe -version`, `deno --version`) as subprocesses; if those pass in
   `selftest.json` (`ffmpeg.ok`, `ffprobe.ok`, `deno.ok` all `true`), the
   subprocess path is healthy.
4. **Antivirus quarantine of a sidecar** can look like a missing DLL — see
   [Antivirus false positives](#5-antivirus-false-positives).

## 5. Antivirus false positives

**Symptoms.** Windows Defender or a third-party antivirus flags, quarantines or
blocks `VideoDownloader.exe` (or one of the bundled binaries), or the app
“disappears” after a scan.

**Cause.** PyInstaller-frozen executables are a well-known source of false
positives; the bundle also contains `ffmpeg`/`deno`/`libmpv`, which security tools
commonly inspect. The build is **not code-signed**.

**Fixes**

1. **Add an exclusion** for the app folder in Microsoft Defender
   (**Windows Security → Virus & threat protection → Manage settings →
   Exclusions**), or in your antivirus.
2. **Restore any quarantined files** (`ffmpeg.exe`, `ffprobe.exe`, `deno.exe`,
   `libmpv-2.dll`, or the app EXE). If a sidecar was removed, `--selftest` will
   report the corresponding resource as missing — re-fetch and rebuild.
3. **Verify you have a genuine build.** The unpacked folder should contain
   `_internal\bin\ffmpeg.exe` etc. per the build guide; if you received the folder
   from an untrusted source, rebuild it yourself from source.

> Code signing is out of scope for this project; if false positives are a
> recurring problem, signing the executable is the durable fix.
