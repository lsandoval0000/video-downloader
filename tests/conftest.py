"""Shared pytest setup for the ``vdl`` test suite (leaf 8.1).

Responsibilities:

* make the ``src`` layout importable when the package is not installed;
* provide the shared fixtures (``tmp_config_dir``, ``fake_settings``,
  ``sample_info_dict``) and a headless ``qapp`` hook for Qt-aware tests;
* gate **integration** tests (network / frozen bundle) behind an explicit opt-in
  (``--run-integration`` or ``VDL_RUN_INTEGRATION=1``).

Unit tests must stay hermetic: no network and no display. The integration gate
means ``pytest tests/unit -q`` never touches the network, and
``pytest tests/integration`` skips unless explicitly enabled.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ── integration gate ─────────────────────────────────────────────────────────
#: Values of ``VDL_RUN_INTEGRATION`` treated as "on".
_TRUTHY = frozenset({"1", "true", "yes", "on"})

_INTEGRATION_SKIP_REASON = (
    "integration test (needs network/frozen bundle); "
    "pass --run-integration or set VDL_RUN_INTEGRATION=1"
)


def _env_enables_integration() -> bool:
    return os.environ.get("VDL_RUN_INTEGRATION", "").strip().lower() in _TRUTHY


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--run-integration`` (in addition to the env var)."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help=(
            "Run tests marked 'integration' (real network download / frozen "
            "bundle). Also enabled by setting VDL_RUN_INTEGRATION=1. Default: skip."
        ),
    )


def _integration_enabled(config: pytest.Config) -> bool:
    return bool(config.getoption("--run-integration")) or _env_enables_integration()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip every ``integration``-marked test unless explicitly opted in."""
    if _integration_enabled(config):
        return
    skip = pytest.mark.skip(reason=_INTEGRATION_SKIP_REASON)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


# ── shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """An isolated, writable user-data directory for config/preset tests.

    Mirrors :func:`vdl.paths.user_data_dir` (which creates the directory) without
    touching the real ``%APPDATA%``/portable location.
    """
    directory = tmp_path / "userdata"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


#: Feature flags that are ON by default in :class:`vdl.config.Settings`; a
#: "fake" (hermetic) Settings turns them OFF so a test opts in to one feature at
#: a time and the resulting opts dict stays minimal and predictable.
_QUIET_OVERRIDES: dict[str, Any] = {
    "download_dir": r"C:\dl",
    "write_subs": False,
    "embed_subs": False,
    "embed_thumbnail": False,
    "embed_metadata": False,
    "sponsorblock_enabled": False,
    "archive_enabled": False,
    "js_runtime_enabled": False,
    "use_cookies": False,
    "cookie_browser": None,
    "cookie_file": None,
    "video_container": None,
    "video_remux": False,
    "convert_thumbnail": False,
    "playlist_items": None,
    "proxy": None,
}


@pytest.fixture
def fake_settings():
    """Factory returning a hermetic :class:`~vdl.config.Settings`.

    Usage::

        def test_x(fake_settings):
            settings = fake_settings(audio_only=True)

    Every optional feature defaults to OFF (overriding the real dataclass
    defaults), so a test only enables the feature it is asserting on. Pure: no
    I/O, no Qt.
    """
    from vdl.config import Settings

    def make(**overrides: Any) -> Settings:
        values = dict(_QUIET_OVERRIDES)
        values.update(overrides)
        return Settings(**values)

    return make


@pytest.fixture
def sample_info_dict() -> dict[str, Any]:
    """A representative yt-dlp ``extract_info`` result (formats + subtitles).

    Close enough to the real shape that the pure format/subtitle helpers can be
    exercised without a network round-trip.
    """
    return {
        "id": "jNQXAC9IVRw",
        "title": "Me at the zoo",
        "duration": 19,
        "extractor": "youtube",
        "extractor_key": "Youtube",
        "webpage_url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
        "formats": [
            {
                "format_id": "137",
                "ext": "mp4",
                "height": 1080,
                "fps": 30,
                "vcodec": "avc1.640028",
                "acodec": "none",
                "filesize": 5_000_000,
                "format_note": "1080p",
            },
            {
                "format_id": "140",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "filesize": 300_000,
                "format_note": "medium",
            },
            {
                "format_id": "18",
                "ext": "mp4",
                "height": 360,
                "vcodec": "avc1",
                "acodec": "mp4a",
                "filesize_approx": 1_000_000,
                "format_note": "360p",
            },
        ],
        "subtitles": {"en": [{"ext": "vtt", "url": "https://example.invalid/en.vtt"}]},
        "automatic_captions": {"es": [{"ext": "json3"}]},
        "requested_subtitles": {"en": {"ext": "vtt"}},
    }


@pytest.fixture(scope="session")
def qapp():
    """A single ``QApplication`` for Qt-aware tests (headless-tolerant).

    pytest-qt's ``qtbot`` fixture is picked up automatically when pytest-qt is
    installed; this fixture exists for tests that only need the application
    object. If no display is available it falls back to the ``offscreen`` Qt
    platform, so the unit suite can run completely headlessly.
    """
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    app = QtWidgets.QApplication.instance()
    if app is not None:
        return app
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        return QtWidgets.QApplication([])
    except Exception as exc:  # pragma: no cover - depends on the host
        pytest.skip(f"no Qt platform available: {exc}")
