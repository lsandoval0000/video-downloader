"""Integration test: frozen bundle smoke check (leaf 8.4).

Subprocesses the built ``dist\\VideoDownloader\\VideoDownloader.exe --selftest``,
reads the ``selftest.json`` it writes, and asserts the readiness probe passed:

* ``ok`` and ``qt_import_ok`` are true;
* the libmpv / ffmpeg / ffprobe / deno versions are present;
* every bundled resource resolved to a file that exists on disk;
* ``_MEIPASS`` is not leaking into the child's ``PATH`` (DLL-search sanitised).

Opt-in only (marked ``integration``, gated by ``tests/conftest.py``) and it skips
cleanly when the frozen build is absent — run ``scripts/build.ps1`` first.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FROZEN_EXE = _REPO_ROOT / "dist" / "VideoDownloader" / "VideoDownloader.exe"

#: Generous ceiling: the probe spawns ffmpeg/ffprobe/deno and loads libmpv.
_TIMEOUT_S = 180

#: Version fields the selftest must report once the bundle is complete.
_VERSION_KEYS = ("libmpv_version", "ffmpeg_version", "ffprobe_version", "deno_version")


def test_frozen_selftest_reports_ready(tmp_path: Path) -> None:
    if not _FROZEN_EXE.is_file():
        pytest.skip(f"frozen build not found: {_FROZEN_EXE} (run scripts/build.ps1)")

    # ``--selftest`` writes selftest.json to the CWD, so run it in a temp dir to
    # avoid clobbering the repo's own copy.
    proc = subprocess.run(
        [str(_FROZEN_EXE), "--selftest"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
    )

    report_path = tmp_path / "selftest.json"
    assert report_path.is_file(), (
        f"--selftest did not write selftest.json (exit {proc.returncode}); stderr={proc.stderr!r}"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report.get("ok") is True, (
        f"frozen selftest reported not-ok: errors={report.get('errors')!r}"
    )
    assert report.get("frozen") is True, "selftest did not run from the frozen bundle"
    assert report.get("qt_import_ok") is True, f"Qt import failed: {report.get('qt')!r}"

    for key in _VERSION_KEYS:
        assert report.get(key), f"selftest.json missing a value for {key!r}"

    resources = report.get("resources", {})
    missing = [name for name, entry in resources.items() if not entry.get("exists")]
    assert resources, "selftest.json reported no resolved resources"
    assert not missing, f"selftest resources missing on disk: {missing}"

    dll_search = report.get("dll_search", {})
    assert dll_search.get("meipass_in_path") is False, (
        "_MEIPASS leaked into the child PATH (DLL search not sanitised)"
    )

    assert proc.returncode == 0, f"--selftest exit code {proc.returncode} (expected 0)"
