"""Real-playback smoke test for the embedded libmpv player (leaves 5.2/5.3).

Generates a tiny test clip with the *bundled* ffmpeg and loads it in a real
``VideoPlayerWidget``. On a machine with a display the video output is asserted
to configure and render (``vo-configured`` + a video format); under the Qt
``offscreen`` plugin (CI) the player falls back to a decode-only output and the
test still proves the media decodes (a duration is reported).

Marked ``integration`` (it shells out to ffmpeg and initializes a GUI). Skips
cleanly when the bundled binaries are absent or libmpv cannot initialize.
"""

from __future__ import annotations

import os
import subprocess
import time

import pytest

pytestmark = pytest.mark.integration

_HEADLESS_PLATFORMS = frozenset({"offscreen", "minimal"})


@pytest.fixture(scope="module")
def qapp():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return app


@pytest.fixture(scope="module")
def sample_media(tmp_path_factory):
    from vdl.paths import ffmpeg_exe

    ffmpeg = ffmpeg_exe()
    if not os.path.isfile(ffmpeg):
        pytest.skip("bundled ffmpeg not available (run build/fetch_binaries.ps1)")

    out = tmp_path_factory.mktemp("media") / "testsrc.mp4"
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=160x120:rate=15:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(out),
    ]
    subprocess.run(cmd, check=True, timeout=120)
    return str(out)


def _libmpv_available() -> tuple[bool, str]:
    try:
        from vdl.player import mpv  # noqa: F401
    except OSError as exc:  # pragma: no cover - depends on the local environment
        return False, str(exc)
    return True, ""


def test_player_widget_plays_generated_media(qapp, sample_media) -> None:
    ok, err = _libmpv_available()
    if not ok:
        pytest.skip(f"libmpv unavailable: {err}")

    from vdl.player.widget import VideoPlayerWidget

    widget = VideoPlayerWidget()
    widget.resize(320, 240)
    widget.show()
    qapp.processEvents()

    assert widget.is_ready, "libmpv instance was not created on show()"
    assert widget.libmpv_version(), "libmpv did not report a version"

    player = widget.player
    seen: dict[str, object] = {}
    for name in ("duration", "time-pos", "vo-configured"):
        player.observe_property(name, (lambda n: lambda _n, v: seen.__setitem__(n, v))(name))

    # Must not raise.
    widget.load(sample_media)

    deadline = time.time() + 10
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.05)
        if seen.get("duration") and seen.get("time-pos"):
            break

    assert (seen.get("duration") or 0) > 0, (
        "libmpv never reported a duration — the generated media did not decode"
    )

    if qapp.platformName() not in _HEADLESS_PLATFORMS:
        assert seen.get("vo-configured") is True, (
            "video output was not configured — nothing rendered into the widget"
        )

    # Transport / track / subtitle API must be callable without raising.
    widget.toggle_pause()
    widget.seek(0.5)
    widget.set_volume(50)
    widget.set_speed(1.25)
    widget.set_audio_track(None)
    widget.set_sub_track(None)
    widget.toggle_mute()
    qapp.processEvents()

    widget.shutdown()
    assert widget.player is None, "shutdown() did not release the libmpv instance"
