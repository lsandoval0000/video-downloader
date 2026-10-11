# VideoDownloader — Usage Guide

This guide walks through every feature of VideoDownloader (`0.1.0`), the portable
Windows video/audio downloader built on `yt-dlp`, `ffmpeg` and an embedded
`libmpv` player.

> **Screenshot placeholders.** Every section has an image placeholder under
> `docs/images/`. Those images are not captured yet — replace each placeholder
> with a real screenshot of that panel. The steps themselves describe the
> current UI, which is grounded in the source.

> **What is verified vs. not.** The UI wiring and layouts described here were
> verified with offscreen harnesses. A handful of behaviours need a **real
> Windows desktop with an interactive session** to confirm visually — those are
> called out per section and listed in
> [README → Not yet verified](../README.md#not-yet-verified).

---

## Contents

- [The window at a glance](#the-window-at-a-glance)
- [1. Format / quality picker](#1-format--quality-picker)
- [2. Audio-only extraction (mp3 / m4a)](#2-audio-only-extraction-mp3--m4a)
- [3. Playlist / channel download](#3-playlist--channel-download)
- [4. Batch / multi-URL input](#4-batch--multi-url-input)
- [5. Download queue with pause / resume / cancel](#5-download-queue-with-pause--resume--cancel)
- [6. Progress + speed / ETA](#6-progress--speed--eta)
- [7. Clipboard auto-detect](#7-clipboard-auto-detect)
- [8. Subtitles: download and/or embed](#8-subtitles-download-andor-embed)
- [9. Thumbnail + metadata embedding](#9-thumbnail--metadata-embedding)
- [10. SponsorBlock removal](#10-sponsorblock-removal)
- [11. Cookies / browser import](#11-cookies--browser-import)
- [12. Format conversion](#12-format-conversion)
- [13. Scheduler](#13-scheduler)
- [14. History and the download archive](#14-history-and-the-download-archive)
- [15. Presets](#15-presets)
- [16. Notifications](#16-notifications)
- [17. Embedded player (libmpv)](#17-embedded-player-libmpv)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Where settings and data live](#where-settings-and-data-live)

---

## The window at a glance

- **Left:** the **download panel** — URL box, Quality, Download options, Playlist,
  the preset row, and the **Download** button.
- **Right (top):** the **queue** table with per-row controls.
- **Right (bottom):** the **embedded player** with a transport bar beneath it.

The menu bar / toolbar provide **File** (Add URLs, Open file, Quit), **View**
(Show player, Reset layout), **History**, **Presets**, **Scheduler**,
**Settings** (Preferences, Do not disturb, Notify even while focused) and
**Help** (About). A system-tray icon mirrors the key actions.

> _[Screenshot placeholder: `docs/images/00-main-window.png` — the main window.]_

---

## 1. Format / quality picker

List every format a URL offers and pick one, or use a named quality preset.

**Steps**

1. Paste a URL into the **URLs (one per line)** box.
2. In the **Quality** combo, choose a preset — *Best available*, *1080p*, *720p*,
   *Audio only*, *Smallest*, or *Default (from settings)*.
3. To choose a specific stream, click **Fetch formats…**. A table opens with
   `id`, `ext`, `resolution`, `fps`, `vcodec`, `acodec`, `filesize` and a note;
   select a row and accept. The chosen selector is shown under the combo
   (e.g. `Selected format selector: 137+bestaudio/best`).
4. Click **Download**.

Selecting a video-only row automatically appends an audio fallback
(`<id>+bestaudio/best`); a muxed row is used as-is; an audio-only row falls back
to `bestaudio/best`.

_Preset selectors used under the hood:_ Best `bv*+ba/b`; 1080p
`bv*[height<=1080]+ba/…`; 720p `bv*[height<=720]+ba/…`; Audio only
`bestaudio/best`; Smallest `wv*+wa/w`.

> _[Screenshot placeholder: `docs/images/01-format-dialog.png` — the format table.]_

## 2. Audio-only extraction (mp3 / m4a)

**Steps**

1. In the **Quality** combo choose **Audio only**.
2. Set the target codec in **Settings → Processing → Audio codec** (`mp3` or
   `m4a`).
3. Click **Download**. The output is a `.mp3` or `.m4a` file (audio stream only).

Selecting *Audio only* also sets the `audio_only` setting, so the extraction
post-processor (`FFmpegExtractAudio`) is applied.

> _[Screenshot placeholder: `docs/images/02-audio-only.png` — Audio only selected.]_

## 3. Playlist / channel download

**Steps**

1. Paste a playlist or channel URL.
2. Tick **Download whole playlist / channel** in the **Playlist** group.
3. Optionally enter an item range in **Items** (e.g. `1-10`; blank = all).
4. Click **Download**. Each entry is queued.

Leave the box unticked to download only the single video at the URL
(`noplaylist` is sent to `yt-dlp`).

> _[Screenshot placeholder: `docs/images/03-playlist.png` — the Playlist group.]_

## 4. Batch / multi-URL input

**Steps**

1. Paste **one URL per line** into the **URLs** box (comments/blank lines are
   ignored; exact duplicates are collapsed).
2. Click **Download**. Every valid URL becomes a queue row.

Lines that contain no URL at all are dropped silently. For tokens that *look*
like a URL but fail validation (e.g. no dot in the host), the status line reports
how many were skipped. If no valid URL is found the panel says so and enqueues
nothing.

> _[Screenshot placeholder: `docs/images/04-batch.png` — several URLs enqueued.]_

## 5. Download queue with pause / resume / cancel

**Steps**

1. Enqueue one or more downloads.
2. At most **Max concurrent downloads** (Settings → Downloads) run at once; the
   rest show **Queued**.
3. Select a row and use the buttons under the table:
   - **Pause** — stops the active transfer but **keeps the `.part` file** so it
     can be resumed.
   - **Resume** — continues a paused job from where it stopped.
   - **Cancel** — aborts a job (and discards its partial file).
   - **Remove** — drops the row from the list.
   - **Open** — plays a finished file, or opens its folder.

The same actions are on the row’s right-click context menu, and double-clicking a
finished row opens it in the player.

> _[Screenshot placeholder: `docs/images/05-queue.png` — queue with controls.]_

## 6. Progress + speed / ETA

While a job runs, its row shows **Status**, a **Progress** bar, **Size**
(downloaded / total), **Speed** (MB/s) and **ETA** (mm:ss). Post-processing shows
as a distinct status label instead of the percentage, e.g. **Merging**,
**Extracting audio**, **Converting video**, **Embedding subtitles**,
**Embedding thumbnail**, **Writing metadata**, **Applying SponsorBlock**.

> The >4 updates/second refresh rate has only been verified in principle
> (signal path); confirm visually on a live download.

> _[Screenshot placeholder: `docs/images/06-progress.png` — a live download row.]_

## 7. Clipboard auto-detect

**Steps**

1. Ensure **Settings → Behaviour → Watch the clipboard for video URLs** is on
   (default: on).
2. Copy a video URL in your browser.
3. If the URL box is **empty**, the app fills it and shows
   *“URL detected on the clipboard — press Download.”* If you are already typing,
   it does **not** touch the box.
4. Click **Download**.

Only a clipboard whose entire content is a single valid `http(s)` URL triggers
the fill; prose or multi-URL selections are ignored.

> Real browser copy → auto-fill has **not yet been verified** on a live desktop
> (the detection predicate and signal wiring were verified offscreen).

> _[Screenshot placeholder: `docs/images/07-clipboard.png` — the detected-URL hint.]_

## 8. Subtitles: download and/or embed

**Steps**

1. In **Download options**:
   - tick **Write subtitle files** to save `.srt` sidecar files, and/or
   - tick **Embed subtitles** to mux subtitles into the container.
2. Set the languages in **Settings → Processing → Subtitle languages**
   (comma-separated, e.g. `en, es`, or `all`).
3. Download.

Embedding works for containers that support it (mp4, mov, m4a, webm, mkv, mka).
If the requested languages are not available, or the container cannot hold a
subtitle stream, the app surfaces a message instead of silently producing a file
with no subtitle track.

> _[Screenshot placeholder: `docs/images/08-subtitles.png` — subtitle options.]_

## 9. Thumbnail + metadata embedding

**Steps**

1. In **Download options** tick **Embed thumbnail** and/or **Embed metadata**
   (both on by default).
2. Optionally tick **Convert thumbnail to jpg first** (Settings → Processing) for
   containers where a webp cover is fragile (e.g. mp4-family).
3. Download — the cover image and title/artist/date tags are written into the
   output file.

> _[Screenshot placeholder: `docs/images/09-thumbnail-metadata.png` — embedding options.]_

## 10. SponsorBlock removal

**Steps**

1. In **Download options** tick **Remove sponsor segments**.
2. Set the categories in **Settings → Processing → SponsorBlock categories**
   (comma-separated; default `sponsor, selfpromo`). `default` expands to
   `all, -filler` (everything except filler).
3. Download a marked video — the selected segments are cut.

`poi_highlight` and `chapter` are never removed (they are markers, not segments).
If the video has no matching segments the download still succeeds unchanged.

> _[Screenshot placeholder: `docs/images/10-sponsorblock.png` — SponsorBlock options.]_

## 11. Cookies / browser import

Use this for login-walled, age-restricted or private videos.

**Steps**

1. In **Download options** tick **Use cookies** and pick your browser from the
   dropdown (Chrome, Edge, Firefox, Brave, Opera, Vivaldi, …).
2. Download.

Alternatively set a plain-text cookie file in **Settings → Network & access →
Cookie file** (a `cookies.txt` exported by a browser extension).

> **Chrome-family browsers lock their cookie database while running.** If the
> import fails, close the browser completely (check Task Manager for background
> processes) and retry — or use a `cookies.txt` file. The app shows this
> guidance instead of a raw error. See
> [TROUBLESHOOTING.md](TROUBLESHOOTING.md#3-chrome--edge--brave-cookie-database-is-locked).

> _[Screenshot placeholder: `docs/images/11-cookies.png` — cookie options.]_

## 12. Format conversion

**Steps**

1. In **Download options**, set **Container** to `mp4`, `mkv`, `webm`, `mov`,
   `avi` or `flv`.
2. Tick **Remux only (no re-encode)** to stream-copy (fast) instead of
   re-encoding.
3. Download — the output container matches your choice.

Incompatible combinations (e.g. audio-only *and* a video container) are rejected
**before** the download starts, with a clear message.

> _[Screenshot placeholder: `docs/images/12-conversion.png` — container + remux.]_

## 13. Scheduler

**Steps**

1. Open **Scheduler → Open scheduler…** (menu or toolbar).
2. Enter one URL, choose a date/time (defaults to five minutes from now) and a
   repeat (**Once** or **Daily**).
3. Click **Schedule**. The item appears in the table with status **Scheduled**.
4. At the scheduled moment the job is enqueued and runs. Use **Cancel selected**
   to remove a pending item and **Clear finished** to tidy up.

Scheduled items persist across restarts. A one-shot item whose time passed while
the app was closed is marked **Missed** on the next launch and is **never** fired
late; a daily item simply advances to its next occurrence.

> A live firing across a real app restart has **not yet been verified** on a
> desktop (the due-computation and persistence were verified offscreen).

> _[Screenshot placeholder: `docs/images/13-scheduler.png` — the scheduler dialog.]_

## 14. History and the download archive

**Steps**

1. Open **History → Open history…**.
2. The table lists past downloads (Title, Site, Quality, Size, Date, Status).
   - **Open in player** (or double-click a row) replays a file that still exists.
   - **Open folder** reveals the file’s location.
   - **Refresh** / **Clear history** manage the list (clearing history does not
     delete files).
3. When you paste a URL that was already downloaded, the URL box shows an
   *“Already downloaded: …”* hint.

Two stores are involved: `yt-dlp`’s append-only `archive.txt` (what makes
re-downloads skip) and the SQLite `history.db` (what the table reads). See
[User data & portable mode](../README.md#user-data--portable-mode).

> _[Screenshot placeholder: `docs/images/14-history.png` — the history table.]_

## 15. Presets

**Steps**

1. Configure the download options as you like.
2. In the preset row, click **Save preset…** and name it.
3. To reuse it: pick it from the **Preset** dropdown, or open **Presets →
   Manage presets…**, select a preset and click **Load** (double-click also
   loads). Loading repopulates every option control.
4. **Delete** removes the selected preset (with a confirmation).

Presets are stored in `config.json` and persist across restarts. A preset
captures the quality, audio-only, container/remux, subtitle, thumbnail, metadata,
SponsorBlock, cookie and playlist-range options.

> _[Screenshot placeholder: `docs/images/15-presets.png` — the preset row / dialog.]_

## 16. Notifications

**Steps**

1. Keep **Settings → Behaviour → Notify when a download finishes** enabled.
2. When a download completes (or fails) a Windows tray balloon appears with the
   file name; **clicking the balloon plays the file**.
3. To silence notifications, toggle **Settings → Do not disturb** (persisted), or
   **Notify even while focused** to control whether balloons show when the window
   is in the foreground.

> Actual balloon visibility and the click-to-play action have **not yet been
> verified** on a live desktop (the notification path was verified offscreen).

> _[Screenshot placeholder: `docs/images/16-notification.png` — a tray balloon.]_

## 17. Embedded player (libmpv)

A finished download plays **inside the app**, in the lower-right pane, with a
transport bar.

**Steps**

1. Open media via any of: double-click a finished queue row; **Open** in the
   queue; a History row; **File → Open file…**; or clicking a completion balloon.
2. Use the transport bar: **▶ / ⏸**, the seek slider, the time read-out, **mute**,
   the **volume** slider, the **speed** combo (0.5×–2×) and the **fullscreen**
   button.

The player supports audio/subtitle track selection and loading an external
subtitle file (used by the app when you play media with sidecar subtitles).

> Rendering **inside the widget** was proven on Windows during development
> (`vo-configured=True`, `video-format=h264`). Note the app lets libmpv pick its
> default video output; it deliberately does **not** force `vo=libmpv` (which
> does not render into an embedded native window).

> _[Screenshot placeholder: `docs/images/17-player.png` — media playing in-app.]_

## Keyboard shortcuts

Player shortcuts work at the window level and are suppressed while you are typing
in a text box, so they never hijack text entry:

| Key | Action |
|-----|--------|
| `Space` | Play / pause |
| `←` / `→` | Seek −5 s / +5 s |
| `F` | Toggle fullscreen |
| `M` | Toggle mute |

App-wide: `Ctrl+N` Add URLs, `Ctrl+O` Open file, `Ctrl+,` Preferences,
`Ctrl+Q` Quit.

## Where settings and data live

Most options are edited in **Settings** (Downloads / Processing / Network &
access / Behaviour tabs) and persisted to `config.json` in the user-data
directory. The Settings dialog footer always shows the active **Mode**
(*Portable* or *Installed*) and **Data directory**, with an **Open data folder**
button. For the full list of files and the portable-mode marker (`portable.txt`),
see [README → User data & portable mode](../README.md#user-data--portable-mode).
