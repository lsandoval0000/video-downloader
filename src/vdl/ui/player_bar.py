"""Transport controls for the embedded libmpv player (leaf 6.1 support).

A thin, stateless bar that drives a :class:`~vdl.player.widget.VideoPlayerWidget`
and reflects its signals (position/duration/pause). It never reaches into libmpv
directly — it only calls the widget's public API, so the player's own threading
and lifecycle guarantees are preserved.

The player is created with ``shortcuts=False`` by the main window (see the
"sandbox the player shortcuts" decision in ``.aiw/worklog.md``); window-level
shortcuts live in :mod:`vdl.ui.main_window` instead.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QToolButton,
    QWidget,
)

from vdl.player.widget import VideoPlayerWidget
from vdl.ui.formatting import human_eta

#: Playback speeds offered in the speed combo.
_SPEEDS: tuple[float, ...] = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


class PlayerBar(QWidget):
    """A compact transport bar bound to a :class:`VideoPlayerWidget`."""

    def __init__(self, player: VideoPlayerWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._player = player
        self._seeking = False

        self._play_button = QPushButton("\u25b6", self)
        self._play_button.setToolTip("Play / pause (Space)")
        self._play_button.setFixedWidth(40)
        self._play_button.clicked.connect(self._player.toggle_pause)

        self._position = QSlider(Qt.Orientation.Horizontal, self)
        self._position.setRange(0, 0)
        self._position.sliderPressed.connect(self._on_seek_start)
        self._position.sliderReleased.connect(self._on_seek_end)
        self._position.sliderMoved.connect(self._on_seek_move)

        self._time_label = QLabel("00:00 / 00:00", self)
        self._time_label.setMinimumWidth(96)
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._mute_button = QToolButton(self)
        self._mute_button.setText("\U0001f50a")
        self._mute_button.setToolTip("Mute (M)")
        self._mute_button.clicked.connect(self._player.toggle_mute)

        self._volume = QSlider(Qt.Orientation.Horizontal, self)
        self._volume.setRange(0, 100)
        self._volume.setValue(100)
        self._volume.setFixedWidth(90)
        self._volume.setToolTip("Volume")
        self._volume.valueChanged.connect(self._player.set_volume)

        self._speed = QComboBox(self)
        for speed in _SPEEDS:
            self._speed.addItem(f"{speed:g}\u00d7", speed)
        self._speed.setCurrentIndex(_SPEEDS.index(1.0))
        self._speed.setToolTip("Playback speed")
        self._speed.currentIndexChanged.connect(self._on_speed_changed)

        self._fullscreen_button = QToolButton(self)
        self._fullscreen_button.setText("\u26f6")
        self._fullscreen_button.setToolTip("Fullscreen (F)")
        self._fullscreen_button.clicked.connect(self._player.toggle_fullscreen)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.addWidget(self._play_button)
        layout.addWidget(self._position, 1)
        layout.addWidget(self._time_label)
        layout.addWidget(self._mute_button)
        layout.addWidget(self._volume)
        layout.addWidget(self._speed)
        layout.addWidget(self._fullscreen_button)

        self._player.position_changed.connect(self._on_position_changed)
        self._player.duration_changed.connect(self._on_duration_changed)
        self._player.pause_changed.connect(self._on_pause_changed)

    # ── player -> bar ────────────────────────────────────────────────────────
    def _on_position_changed(self, position: float, duration: float) -> None:
        if duration > 0:
            self._position.setRange(0, int(duration * 1000))
        if not self._seeking:
            self._position.setValue(int(position * 1000))
        self._time_label.setText(f"{human_eta(position)} / {human_eta(duration)}")

    def _on_duration_changed(self, duration: float) -> None:
        if duration > 0:
            self._position.setRange(0, int(duration * 1000))

    def _on_pause_changed(self, paused: bool) -> None:
        self._play_button.setText("\u25b6" if paused else "\u23f8")

    # ── bar -> player ────────────────────────────────────────────────────────
    def _on_seek_start(self) -> None:
        self._seeking = True

    def _on_seek_move(self, value: int) -> None:
        self._time_label.setText(
            f"{human_eta(value / 1000)} / {human_eta(self._position.maximum() / 1000)}"
        )

    def _on_seek_end(self) -> None:
        self._seeking = False
        self._player.seek(self._position.value() / 1000, "absolute")

    def _on_speed_changed(self, _index: int) -> None:
        speed = self._speed.currentData()
        if speed is not None:
            self._player.set_speed(float(speed))
