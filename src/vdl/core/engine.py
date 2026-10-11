"""In-process yt-dlp download worker (extra #6).

A :class:`DownloadWorker` is a :class:`~PySide6.QtCore.QThread` that runs one
job through ``yt_dlp.YoutubeDL`` in-process. yt-dlp's ``progress_hooks`` /
``postprocessor_hooks`` fire **on this worker thread**, so the hooks only ever
emit Qt signals — they must never touch widgets (plan anti-pattern). The GUI
thread stays responsive and renders from the signals.

Cancellation / pausing: yt-dlp has no true pause. Both pause and cancel work by
raising :class:`yt_dlp.utils.DownloadCancelled` from the progress hook at the
next tick, which aborts cleanly while leaving the ``.part`` file in place. The
queue decides the final state (paused keeps ``.part``; cancel deletes it).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from typing import TYPE_CHECKING, Any

import yt_dlp
from PySide6.QtCore import QThread, Signal
from yt_dlp.utils import ISO639Utils

from vdl.core.options import build_subtitle_opts, build_ydl_opts, embed_subtitles_supported
from vdl.paths import ffmpeg_exe

if TYPE_CHECKING:
    from vdl.config import Settings
    from vdl.core.queue import Job

logger = logging.getLogger("vdl.core.engine")

#: Output suffixes that are sidecar artefacts, not the media deliverable. A
#: ``DownloadError`` reported *after* one of these landed — e.g. a subtitle write
#: returning ``HTTP Error 429`` — must not fail a job whose media already
#: downloaded (leaf 10.5).
_SIDECAR_SUFFIXES = frozenset(
    {
        ".part",
        ".ytdl",
        ".tmp",
        ".srt",
        ".vtt",
        ".ass",
        ".ssa",
        ".lrc",
        ".json3",
        ".srv1",
        ".srv2",
        ".srv3",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }
)

#: yt-dlp names un-merged per-format intermediates ``<stem>.f<id>.<ext>``; those
#: are NOT the finished media, so a merge failure that leaves only fragments is
#: still treated as a genuine (fatal) failure.
_FRAGMENT_RE = re.compile(r"\.f\d+\.[^.]+$", re.IGNORECASE)

#: Subtitle sidecar extensions that can be muxed into a container with ffmpeg.
#: ``json3``/``json`` are deliberately absent — they are timed-text JSON, not
#: real subtitle streams, and ffmpeg cannot embed them (yt-dlp skips them too).
_EMBEDDABLE_SUBTITLE_EXTS = frozenset({".srt", ".vtt", ".ass", ".ssa"})

#: Containers that require the ``mov_text`` subtitle codec when stream-copying
#: (mirrors yt-dlp's ``FFmpegPostProcessor.stream_copy_opts``).
_MOV_TEXT_CONTAINERS = frozenset({"mp4", "mov", "m4a"})

#: Name reported on the ``postprocess`` signal while subtitles are embedded, so
#: the queue view keeps showing its "Embedding subtitles" stage (leaf 10.5).
_EMBED_PP_NAME = "FFmpegEmbedSubtitle"


def _silent_remove(path: str) -> None:
    """Best-effort file removal; never raises."""
    try:
        os.remove(path)
    except OSError:
        pass


def _subtitle_language(media_path: str, subtitle_path: str) -> str | None:
    """The language code encoded in ``<media_stem>.<lang>.<ext>`` (else ``None``)."""
    stem = os.path.splitext(os.path.basename(media_path))[0]
    name = os.path.basename(subtitle_path)
    if not name.startswith(stem + "."):
        return None
    middle = name[len(stem) + 1 :]
    ext = os.path.splitext(middle)[1]
    return (middle[: -len(ext)] if ext else middle) or None


def _subtitle_language_tag(language: str | None, container: str) -> str | None:
    """The ffmpeg ``language=`` value for a subtitle stream in ``container``.

    Only the ``mov_text`` family (mp4/mov/m4a) is remapped to the ISO 639-2/T
    3-letter code — its muxer SILENTLY DROPS a 2-letter tag (so ``ffprobe`` then
    shows ``tags={}``); mkv/webm keep the code verbatim (their muxers accept the
    2-letter form, so behaviour there is unchanged). The mapping is yt-dlp's own
    (``ISO639Utils.short2long`` — the exact call its ``FFmpegEmbedSubtitlePP``
    makes for this same metadata line); a region-qualified code (``en-US``) maps
    via its primary subtag, and an unknown code falls back to the original value.
    """
    if not language:
        return language
    if container not in _MOV_TEXT_CONTAINERS:
        return language
    return ISO639Utils.short2long(language.lower()) or language


class DownloadWorker(QThread):
    """Runs a single :class:`~vdl.core.queue.Job` to completion off the GUI thread.

    Signals
    -------
    progress(dict): ``status`` is ``"downloading"`` or ``"finished"`` with
        ``percent``/``downloaded``/``total``/``speed``/``eta``/``filename``.
    postprocess(dict): ``status`` (``"started"``/``"finished"``),
        ``postprocessor`` (e.g. ``"EmbedThumbnail"``), and ``filename``.
    finished(list): the resolved output path(s); emitted on success *and* on a
        clean stop (cancel/pause) so the queue always learns the thread ended.
    error(str): human-readable failure text (never lets the thread die silently).

    Subtitles are acquired in an **isolated, non-fatal** second pass after the
    media is finalised (leaf 10.5): a subtitle ``HTTP 429`` is only a warning and
    can never abort the media job. See :meth:`_acquire_subtitles`.
    """

    progress = Signal(dict)
    postprocess = Signal(dict)
    finished = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        settings: Settings,
        job: Job,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._job = job
        self._stopped = False
        self._ydl: yt_dlp.YoutubeDL | None = None
        self._output_paths: list[str] = []
        self._current_filename: str | None = None

    # ── control (called from the GUI thread) ─────────────────────────────────
    def request_stop(self) -> None:
        """Ask the worker to abort cleanly at the next progress tick.

        The abort preserves the ``.part`` file so a later resume can continue.
        """
        self._stopped = True

    # Alias kept for the queue/plan vocabulary ("cancel() stops cleanly").
    def cancel(self) -> None:
        self.request_stop()

    @property
    def current_filename(self) -> str | None:
        """Last filename reported by yt-dlp (used to locate the ``.part`` file)."""
        return self._current_filename

    # ── hooks: run on the WORKER thread -> emit signals only ─────────────────
    def _on_progress(self, d: dict[str, Any]) -> None:
        self._check_stop()
        status = d.get("status")
        filename = d.get("filename")
        if filename:
            self._current_filename = filename

        if status == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            # GOTCHA: total_bytes may be None -> fall back to the estimate.
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            self.progress.emit(
                {
                    "status": "downloading",
                    "percent": (downloaded / total * 100.0) if total else 0.0,
                    "downloaded": downloaded,
                    "total": total,
                    "speed": d.get("speed"),
                    "eta": d.get("eta"),
                    "filename": filename,
                }
            )
        elif status == "finished":
            if filename:
                self._remember(filename)
            total = d.get("total_bytes") or d.get("downloaded_bytes") or 0
            self.progress.emit(
                {
                    "status": "finished",
                    "percent": 100.0,
                    "downloaded": d.get("downloaded_bytes") or total,
                    "total": total,
                    "speed": None,
                    "eta": 0,
                    "filename": filename,
                }
            )

    def _on_postprocess(self, d: dict[str, Any]) -> None:
        info = d.get("info_dict") or {}
        filename = info.get("filepath") or info.get("filename")
        self.postprocess.emit(
            {
                "status": d.get("status"),
                "postprocessor": d.get("postprocessor"),
                "filename": filename,
            }
        )
        if d.get("status") == "finished" and filename:
            self._remember(filename)

    # ── internals ────────────────────────────────────────────────────────────
    def _check_stop(self) -> None:
        if self._stopped:
            raise yt_dlp.utils.DownloadCancelled("cancelled by user")

    def _remember(self, path: str | None) -> None:
        if path and path not in self._output_paths:
            self._output_paths.append(path)

    def _existing_paths(self) -> list[str]:
        """Only paths that actually exist on disk (post-processed intermediates
        may have been deleted/replaced by a later postprocessor)."""
        return [p for p in self._output_paths if p and os.path.exists(p)]

    def _media_paths(self) -> list[str]:
        """Existing outputs that are the media deliverable, not a sidecar.

        Filters :meth:`_existing_paths` down to files that are neither subtitle/
        thumbnail/temp sidecars nor un-merged ``.f<id>`` format fragments, so the
        error handler can tell "the media downloaded" apart from "only extras (or
        raw fragments) did" (leaf 10.5).
        """
        deliverable: list[str] = []
        for path in self._existing_paths():
            if os.path.splitext(path)[1].lower() in _SIDECAR_SUFFIXES:
                continue
            if _FRAGMENT_RE.search(path):
                continue
            deliverable.append(path)
        return deliverable

    @staticmethod
    def _mentions_subtitles(message: str) -> bool:
        """Whether a yt-dlp error message refers to a subtitle download."""
        return "subtitle" in message.lower()

    # ── thread entry point ───────────────────────────────────────────────────
    def run(self) -> None:  # noqa: D102 - documented on the class
        opts = build_ydl_opts(self._settings, self._job)
        opts["progress_hooks"] = [self._on_progress]
        opts["postprocessor_hooks"] = [self._on_postprocess]
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                self._ydl = ydl
                ydl.download([self._job.url])
        except yt_dlp.utils.DownloadCancelled:
            logger.info("download stopped (cancel/pause): %s", self._job.url)
            self.finished.emit(self._existing_paths())
            return
        except yt_dlp.utils.DownloadError as exc:
            message = str(exc)
            # The media pass writes NO subtitles, so a subtitle 429 can no longer
            # reach here. A DownloadError is still tolerated if the media
            # deliverable actually landed (e.g. a late post-processor hiccup):
            # finish the job (DONE) with a warning; only an error with no media
            # output is a genuine failure.
            media = self._media_paths()
            if media:
                detail = (
                    "download reported an error after the media was written"
                    if not self._mentions_subtitles(message)
                    else "subtitles failed but the media is present"
                )
                logger.warning("%s, keeping it: %s — %s", detail, self._job.url, message)
                self._finish_with_subtitles()
                return
            logger.error("download failed: %s — %s", self._job.url, message)
            self.error.emit(message)
            return
        except Exception as exc:  # noqa: BLE001 - never let the thread die silently
            logger.exception("unexpected download error for %s", self._job.url)
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        finally:
            self._ydl = None
        self._finish_with_subtitles()

    # ── subtitles: isolated, NON-FATAL second pass (leaf 10.5) ───────────────
    def _finish_with_subtitles(self) -> None:
        """Acquire subtitles (best-effort) then announce the finished media paths."""
        try:
            self._acquire_subtitles()
        except Exception:  # noqa: BLE001 - the media job must finish regardless
            logger.exception("subtitle acquisition raised (non-fatal) for %s", self._job.url)
        self.finished.emit(self._existing_paths())

    def _acquire_subtitles(self) -> None:
        """Phase 2/3: fetch + optionally embed subtitles without ever failing.

        Runs only when the user requested subtitles, the job was not stopped, and
        the media deliverable is on disk. Every failure in here is logged as a
        warning; the media job still reports ``finished``.
        """
        if self._stopped:
            return
        settings = self._settings
        if not (settings.write_subs or settings.embed_subs):
            return
        media = self._media_paths()
        if not media:
            return
        self._download_subtitles()
        if settings.embed_subs:
            for media_path in media:
                self._embed_subtitles(media_path)

    def _download_subtitles(self) -> None:
        """Run the isolated subtitle-only yt-dlp pass; any failure is a warning."""
        try:
            opts = build_subtitle_opts(self._settings, self._job)
            if not opts:
                return
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([self._job.url])
        except yt_dlp.utils.DownloadCancelled:
            logger.info("subtitle pass cancelled: %s", self._job.url)
        except yt_dlp.utils.DownloadError as exc:
            logger.warning(
                "subtitles unavailable, keeping the media (non-fatal): %s — %s",
                self._job.url,
                exc,
            )
        except Exception as exc:  # noqa: BLE001 - the subtitle step must never be fatal
            logger.warning(
                "unexpected subtitle error, keeping the media (non-fatal): %s — %s: %s",
                self._job.url,
                type(exc).__name__,
                exc,
            )

    def _embed_subtitles(self, media_path: str) -> None:
        """Phase 3: mux subtitle sidecars into the finalised media (non-fatal)."""
        container = os.path.splitext(media_path)[1].lstrip(".").lower()
        if not embed_subtitles_supported(container):
            logger.warning(
                "cannot embed subtitles into .%s files (non-fatal): %s", container, media_path
            )
            return
        subs = self._subtitle_sidecars(media_path)
        if not subs:
            logger.info("no subtitle files to embed for %s", media_path)
            return

        self.postprocess.emit(
            {"status": "started", "postprocessor": _EMBED_PP_NAME, "filename": media_path}
        )
        try:
            self._mux_subtitles(media_path, subs, container)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            logger.warning("subtitle embedding failed (non-fatal): %s — %s", media_path, exc)
            return
        finally:
            self.postprocess.emit(
                {"status": "finished", "postprocessor": _EMBED_PP_NAME, "filename": media_path}
            )
        logger.info("embedded %d subtitle(s) into %s", len(subs), media_path)
        # yt-dlp deletes sidecar subtitles after embedding unless the user also
        # asked to keep them ("Write subtitle files").
        if not self._settings.write_subs:
            for sub in subs:
                _silent_remove(sub)

    @staticmethod
    def _subtitle_sidecars(media_path: str) -> list[str]:
        """Embeddable subtitle sidecars sitting next to ``media_path``.

        yt-dlp names them ``<media_stem>.<lang>.<ext>`` in the same directory, so
        match on the media stem rather than relying on the subtitle pass's internal
        filename computation (which may pick a different container extension).
        """
        stem = os.path.splitext(media_path)[0]
        directory = os.path.dirname(media_path) or "."
        base = os.path.basename(stem)
        try:
            names = os.listdir(directory)
        except OSError:
            return []
        found = [
            os.path.join(directory, name)
            for name in names
            if name.startswith(base + ".")
            and os.path.splitext(name)[1].lower() in _EMBEDDABLE_SUBTITLE_EXTS
        ]
        return sorted(found)

    @staticmethod
    def _mux_subtitles(media_path: str, subtitles: list[str], container: str) -> None:
        """Stream-copy ``media_path`` with ``subtitles`` muxed in (in place).

        Mirrors yt-dlp's ``FFmpegEmbedSubtitlePP`` argument order / codec choice
        (``-c copy`` + ``mov_text`` for the mp4 family); ``webm`` only carries
        WebVTT, so non-VTT sidecars are dropped for that container. The
        ``language=`` tag is the ISO 639-2/T 3-letter code for the mp4 family
        (the 2-letter form is dropped by its muxer) and verbatim otherwise.
        """
        if container == "webm":
            subtitles = [s for s in subtitles if os.path.splitext(s)[1].lower() == ".vtt"]
            if not subtitles:
                raise ValueError("webm can only embed WebVTT subtitles")
        directory = os.path.dirname(media_path) or "."
        ext = os.path.splitext(media_path)[1]
        fd, temp_path = tempfile.mkstemp(prefix=".vdl-subs-", suffix=ext, dir=directory)
        os.close(fd)

        cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", media_path]
        for sub in subtitles:
            cmd += ["-i", sub]
        cmd += ["-map", "0", "-dn", "-ignore_unknown", "-c", "copy"]
        if container in _MOV_TEXT_CONTAINERS:
            cmd += ["-c:s", "mov_text"]
        cmd += ["-map", "-0:s"]  # drop any pre-existing subtitle streams
        for index, sub in enumerate(subtitles):
            cmd += ["-map", f"{index + 1}:0"]
            language = _subtitle_language_tag(_subtitle_language(media_path, sub), container)
            if language:
                cmd += [f"-metadata:s:s:{index}", f"language={language}"]
        cmd.append(temp_path)

        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except BaseException:
            _silent_remove(temp_path)
            raise
        os.replace(temp_path, media_path)
