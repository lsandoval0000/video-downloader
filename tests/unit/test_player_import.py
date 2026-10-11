"""Headless import/construct checks for the vendored libmpv module (leaf 5.1).

These tests exercise the DLL-resolution preamble in ``vdl.player.mpv`` and the
fact that ``mpv.MPV()`` can be constructed and reports a version. They need
neither a display nor network. If libmpv cannot be located/loaded the whole
module is skipped (so a machine without the fetched ``vendor/libmpv`` binaries
does not report a false failure — run ``build/fetch_binaries.ps1`` to populate
them).
"""

from __future__ import annotations

import pytest

try:
    from vdl.player import mpv as vdl_mpv
except OSError as exc:  # pragma: no cover - depends on the local environment
    pytest.skip(f"libmpv not available: {exc}", allow_module_level=True)


def test_vendored_mpv_version_matches_upstream() -> None:
    """The vendored copy records its upstream provenance version."""
    assert vdl_mpv.__version__ == "1.0.8"


def test_client_api_version_is_sufficient() -> None:
    """python-mpv requires a libmpv client API of at least 1.108."""
    assert vdl_mpv.MPV_VERSION >= (1, 108)


def test_mpv_constructs_and_reports_version() -> None:
    """A bare ``MPV`` instance constructs (headless ``vo=null``) and has a version."""
    try:
        player = vdl_mpv.MPV(vo="null", config=False)
    except OSError as exc:  # pragma: no cover - depends on the local environment
        pytest.skip(f"libmpv cannot initialize: {exc}")
    try:
        assert player.mpv_version  # e.g. "mpv v0.41.0-..."
        assert player.mpv_version_tuple[0] >= 0
    finally:
        player.terminate()


def test_widget_module_is_importable() -> None:
    """The Qt widget module imports (does not require a display)."""
    from vdl.player.widget import VideoPlayerWidget

    assert VideoPlayerWidget is not None
