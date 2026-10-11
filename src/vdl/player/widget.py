"""Embedded libmpv player widget (plan leaves 5.2 + 5.3).

``VideoPlayerWidget`` hosts a child ``QWidget`` container whose *native* window
handle is handed to libmpv via ``wid=`` so video renders *inside* the widget
area (not in a separate window). It exposes transport controls, track selection
and runtime subtitle loading, plus Qt-layer keyboard shortcuts.

Critical constraints honoured here (see ``.aiw/plan.md`` "Known Gotchas"):

* **Native-window timing** — ``winId()`` is only valid once the container has a
  native window. We set ``WA_NativeWindow`` on the container and call ``winId()``
  from :meth:`showEvent`, i.e. only *after* the first show. We deliberately do
  **not** set ``WA_DontCreateNativeAncestors``: keeping the ancestors native lets
  Qt resolve the native child's position relative to real ancestors, so it lands
  on the player pane instead of being parked at the top-level window origin (the
  "black rectangle over the URL box" bug — leaf 10.4).
* **Locale ordering** — ``locale.setlocale(LC_NUMERIC, 'C')`` is enforced globally
  in :mod:`vdl.app` before the first ``mpv.MPV()``; this widget does **not** touch
  the locale, so the ordering guarantee stays in exactly one place.
* **Keyboard shortcuts** — python-mpv's keybindings do **not** fire when embedded
  in Qt (jaseg/python-mpv#200), so space/←/→/f/m are implemented as ``QShortcut``
  objects at the Qt layer instead of via mpv's ``input_default_bindings``.
* **Clean shutdown** — :meth:`closeEvent` (and ``QApplication.aboutToQuit``)
  terminate libmpv explicitly so the process never crashes on exit.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from vdl.player import mpv

log = logging.getLogger(__name__)

#: Seconds moved by the Left/Right arrow-key shortcuts.
_SEEK_STEP = 5.0

#: Qt platform plugins that have no real native surface. Embedding via ``wid``
#: on these yields a bogus handle and crashes the GPU video output, so we fall
#: back to a decode-only video output instead.
_HEADLESS_PLATFORMS = frozenset({"offscreen", "minimal"})


class VideoPlayerWidget(QWidget):
    """A widget that plays media with an embedded libmpv instance.

    The libmpv instance is created lazily on the first :meth:`showEvent` (or on
    the first :meth:`load` after the widget is visible) so the native window
    handle is valid when it is passed to mpv.
    """

    #: Emitted as ``(position_seconds, duration_seconds)`` as playback advances.
    position_changed = Signal(float, float)
    #: Emitted with the media duration in seconds once it is known.
    duration_changed = Signal(float)
    #: Emitted whenever the pause state changes.
    pause_changed = Signal(bool)
    #: Emitted with the loaded path/URL once media starts loading.
    media_loaded = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, shortcuts: bool = True) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 180)

        self._player: mpv.MPV | None = None
        self._pending_path: str | None = None
        self._duration = 0.0
        self._about_quit_connected = False
        self._shortcuts: list[QShortcut] = []

        # The container is the widget whose native window libmpv draws into. It
        # gets a black background so the area is not garbage-coloured before the
        # first frame arrives.
        self._container = QWidget(self)
        self._container.setObjectName("videoSurface")
        self._container.setStyleSheet("background-color: black;")
        self._container.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._container)

        if shortcuts:
            self._install_shortcuts()

    # ───────────────────────── lifecycle ─────────────────────────

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Create the libmpv instance *after* the container has a native window."""
        super().showEvent(event)
        self._ensure_player()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Retry deferred libmpv creation once the widget has a real size.

        When the widget is shown before the layout has assigned it a non-zero
        size, :meth:`_ensure_player` defers (it must not take ``winId()`` yet).
        The layout's first resize is the cue to create the player. No manual
        surface geometry re-sync is needed: with the ancestors left native, Qt
        positions the native child correctly on its own.
        """
        super().resizeEvent(event)
        if self.isVisible():
            self._ensure_player()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Release libmpv cleanly before the widget goes away."""
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Terminate the libmpv instance (idempotent, safe from any thread)."""
        player, self._player = self._player, None
        if player is None:
            return
        try:
            player.terminate()
            log.info("libmpv terminated")
        except Exception:  # pragma: no cover - never crash on teardown
            log.exception("error while terminating libmpv")

    def _ensure_player(self) -> None:
        """Construct the ``mpv.MPV`` instance once, embedding into the container."""
        if self._player is not None:
            return

        # Leaf 10.4: never take ``winId()``/create the native window before the
        # widget has a real, non-zero size — doing so locks in bogus geometry. A
        # later resize retries (see :meth:`resizeEvent`).
        if self.width() <= 0 or self.height() <= 0:
            log.debug("deferring libmpv creation until the widget has a size")
            return

        # Leaf 10.4 fix: only ``WA_NativeWindow`` is set. Dropping
        # ``WA_DontCreateNativeAncestors`` lets Qt keep the ancestors native, so
        # the native surface is positioned relative to them instead of being
        # parked at the top-level window origin (the black rectangle over the
        # URL box). No manual geometry re-sync is required.
        self._container.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)

        # winId() is valid now (we are inside/after show); it also forces the
        # native window to be created on demand.
        wid = int(self._container.winId())

        # NOTE (plan/reality conflict, evidence-backed): the plan/brief specify
        # ``vo='libmpv'``. Verified against libmpv v0.41.0 that ``vo=libmpv`` is
        # the *render-API* output and does NOT draw into a ``wid`` (the observed
        # ``vo-configured`` stays ``False`` and no frame is presented). The
        # default video output (``gpu-next`` on this build) *does* render into the
        # ``wid`` (``vo-configured=True``, ``width=320``). So we let mpv choose the
        # default VO. We also disable config/input so the bundled player neither
        # reads the host's ``mpv.conf`` nor swallows keyboard input (Qt owns the
        # shortcuts — see jaseg/python-mpv#200).
        opts: dict[str, object] = {
            "keep_open": "yes",
            "osc": True,
            "config": False,
            "input_default_bindings": False,
            "input_vo_keyboard": False,
        }

        platform = QGuiApplication.platformName() if QGuiApplication.instance() else ""
        headless = platform in _HEADLESS_PLATFORMS or not wid
        if not headless:
            opts["wid"] = str(wid)
        else:
            # No real native surface (Qt "offscreen"/"minimal" plugin, or a zero
            # handle): fall back to a decode-only video output so the widget can
            # still load and decode media without error or a crash. Real
            # rendering requires a real surface.
            opts["vo"] = "null"
            log.warning(
                "headless Qt platform %r (wid=%s); creating libmpv with vo=null",
                platform or "<none>",
                wid,
            )

        self._player = mpv.MPV(**opts)
        self._wire_observers(self._player)
        self._connect_about_to_quit()
        log.info("libmpv ready: %s", getattr(self._player, "mpv_version", "?"))

        if self._pending_path is not None:
            path, self._pending_path = self._pending_path, None
            self.load(path)

    def _wire_observers(self, player: mpv.MPV) -> None:
        player.observe_property("time-pos", self._on_time_pos)
        player.observe_property("duration", self._on_duration)
        player.observe_property("pause", self._on_pause)

    def _connect_about_to_quit(self) -> None:
        app = QApplication.instance()
        if app is not None and not self._about_quit_connected:
            app.aboutToQuit.connect(self.shutdown)
            self._about_quit_connected = True

    # ───────────────────────── observers ─────────────────────────
    # These run on libmpv's event thread; emitting Qt signals from there is safe
    # (Qt queues cross-thread signal delivery).

    def _on_time_pos(self, _name: str, value) -> None:
        pos = float(value) if value is not None else 0.0
        self.position_changed.emit(pos, self._duration)

    def _on_duration(self, _name: str, value) -> None:
        self._duration = float(value) if value is not None else 0.0
        self.duration_changed.emit(self._duration)

    def _on_pause(self, _name: str, value) -> None:
        self.pause_changed.emit(bool(value))

    # ───────────────────────── public API ─────────────────────────

    @property
    def player(self) -> mpv.MPV | None:
        """The underlying ``mpv.MPV`` instance, or ``None`` before the first show."""
        return self._player

    @property
    def is_ready(self) -> bool:
        """Whether the libmpv instance has been created."""
        return self._player is not None

    def libmpv_version(self) -> str | None:
        """The resolved libmpv version string (``None`` before the player exists)."""
        if self._player is None:
            return None
        return getattr(self._player, "mpv_version", None)

    def load(self, path: str) -> None:
        """Load a media file/URL.

        If the widget is not shown yet (no libmpv instance), the path is queued
        and loaded automatically once the player exists.
        """
        path = str(path)
        if self._player is None:
            self._pending_path = path
            log.info("queued media until player exists: %s", path)
            return
        log.info("loading media: %s", path)
        self.media_loaded.emit(path)
        self._player.loadfile(path)

    def toggle_pause(self) -> None:
        """Toggle between playing and paused."""
        if self._player is not None:
            self._player.command("cycle", "pause")

    def seek(self, seconds: float, reference: str = "absolute") -> None:
        """Seek by ``seconds``.

        ``reference`` is ``"absolute"`` (default, jump to a position) or
        ``"relative"`` (move from the current position).
        """
        if self._player is not None:
            self._player.command("seek", float(seconds), reference)

    def set_volume(self, percent: float) -> None:
        """Set the audio volume (mpv scale: 0–100 is nominal, >100 allowed)."""
        if self._player is not None:
            self._player.volume = float(percent)

    def set_speed(self, speed: float) -> None:
        """Set the playback speed multiplier (1.0 = normal)."""
        if self._player is not None:
            self._player.speed = float(speed)

    def set_audio_track(self, track_id: int | str | None) -> None:
        """Select an audio track by id; ``None`` disables audio."""
        if self._player is not None:
            self._player.aid = "no" if track_id is None else track_id

    def set_sub_track(self, track_id: int | str | None) -> None:
        """Select a subtitle track by id; ``None`` disables subtitles."""
        if self._player is not None:
            self._player.sid = "no" if track_id is None else track_id

    def add_subtitle_file(self, path: str) -> None:
        """Load an external subtitle file and select it immediately."""
        if self._player is not None:
            self._player.command("sub-add", str(path), "select")

    def toggle_mute(self) -> None:
        """Toggle audio muting."""
        if self._player is not None:
            self._player.command("cycle", "mute")

    def toggle_fullscreen(self) -> None:
        """Toggle full-screen on the containing top-level window."""
        window = self.window()
        if window.isFullScreen():
            window.showNormal()
        else:
            window.showFullScreen()

    # ───────────────────────── shortcuts ─────────────────────────

    def _install_shortcuts(self) -> None:
        """Bind space/←/→/f/m at the Qt layer (mpv bindings don't fire embedded)."""

        def add(sequence: str, slot) -> None:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(slot)
            self._shortcuts.append(shortcut)

        add("Space", self.toggle_pause)
        add("Left", lambda: self.seek(-_SEEK_STEP, "relative"))
        add("Right", lambda: self.seek(_SEEK_STEP, "relative"))
        add("F", self.toggle_fullscreen)
        add("M", self.toggle_mute)
