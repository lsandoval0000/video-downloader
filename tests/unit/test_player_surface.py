"""Discriminating checks for the native video-surface embed (leaf 10.4).

The libmpv container (``videoSurface``) is made a *native* OS child window
(``WA_NativeWindow``). Round 1 *also* set ``WA_DontCreateNativeAncestors``, which
kept every ancestor non-native; Qt then resolved the native child's position as
the top-level window origin and parked a black rectangle over the left panel's
"URLs (one per line)" box. The proven fix drops that attribute so Qt positions
the native child correctly on its own — no manual geometry re-sync required.

These tests are hermetic: the ``vdl.player.mpv.MPV`` factory is stubbed, so
neither libmpv nor a real display is required. ``test_container_stays_native``
*fails on the pre-fix code* (it asserts ``WA_DontCreateNativeAncestors`` is
unset), so it is genuinely discriminating — unlike the round-1 tests, which
passed either way. The real embed path stays covered by the opt-in
``tests/integration/test_player_smoke.py``.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt


class _FakeMPV:
    """Minimal stand-in for :class:`vdl.player.mpv.MPV` (never touches libmpv)."""

    def __init__(self, **opts: object) -> None:
        self.opts = opts
        self.mpv_version = "fake-libmpv"
        self.observed: dict[str, object] = {}
        self.terminated = False

    def observe_property(self, name: str, handler: object) -> None:
        self.observed[name] = handler

    def terminate(self) -> None:
        self.terminated = True


@pytest.fixture
def player(qapp, monkeypatch):
    """Yield ``(widget, created)`` — a widget with the mpv factory stubbed.

    ``created`` collects every :class:`_FakeMPV` the widget constructed, so a
    test can prove creation was (or was not) triggered without a real player.
    """
    from vdl.player import mpv
    from vdl.player.widget import VideoPlayerWidget

    created: list[_FakeMPV] = []

    def factory(**opts: object) -> _FakeMPV:
        instance = _FakeMPV(**opts)
        created.append(instance)
        return instance

    monkeypatch.setattr(mpv, "MPV", factory)
    widget = VideoPlayerWidget()
    try:
        yield widget, created
    finally:
        widget.shutdown()
        widget.close()


def test_container_stays_native(player) -> None:
    """The container must be native *without* forcing non-native ancestors.

    Discriminating: on the round-1 (pre-fix) code the container has
    ``WA_DontCreateNativeAncestors`` set, so the first assertion fails.
    """
    widget, created = player
    widget.resize(640, 360)
    assert not widget.is_ready  # nothing is created until _ensure_player runs

    widget._ensure_player()

    assert widget.is_ready
    assert len(created) == 1
    container = widget._container
    assert not container.testAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors), (
        "container must not keep WA_DontCreateNativeAncestors (leaf 10.4 bug)"
    )
    assert container.testAttribute(Qt.WidgetAttribute.WA_NativeWindow), (
        "container must be a native window so libmpv can embed via wid="
    )


def test_ensure_player_defers_at_zero_size(player) -> None:
    """``_ensure_player`` takes no ``winId()``/creates nothing at zero size."""
    widget, created = player
    # A fresh widget floors at its 320x180 minimum, so force a truly zero size.
    widget.setMinimumSize(0, 0)
    widget.resize(0, 0)
    assert widget.width() == 0 and widget.height() == 0

    widget._ensure_player()

    assert not widget.is_ready, "player created while the widget had no size"
    assert created == [], "mpv factory called before a real size existed"
    # The native attribute is set only *after* the size guard, so it stays unset
    # — proving the guard returned before winId()/creation was reached.
    assert not widget._container.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)

    # Once a real size exists, creation proceeds exactly once.
    widget.resize(320, 240)
    widget._ensure_player()
    assert widget.is_ready
    assert len(created) == 1
