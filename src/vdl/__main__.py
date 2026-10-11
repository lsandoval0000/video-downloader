"""Module entrypoint for ``python -m vdl`` and the console script.

Intentionally thin: the real bootstrap lives in :mod:`vdl.app`. The jobs done
here are (a) sanitising the process DLL search path *before* any DLL is loaded
(leaf 7.3), and (b) handling ``--selftest``, which must return before a window —
or even a ``QApplication`` — is created so the frozen exe can be probed headlessly
(leaf 7.4).

``--selftest`` is a readiness probe: it resolves every bundled resource, loads
libmpv headlessly, imports Qt **without a display**, and spawns the sidecar
``ffmpeg`` / ``ffprobe`` / ``deno`` executables as subprocesses (proving the
leaked ``SetDllDirectoryW`` was cleared). It writes ``selftest.json`` to the
current working directory and exits ``0`` only when every required check passes.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

#: Windows: keep sidecar probes from flashing a console window on a windowed build.
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

#: Per-probe subprocess timeout (seconds).
_PROBE_TIMEOUT_S = 30


def _run_version(cmd: list[str]) -> dict[str, Any]:
    """Run ``cmd`` and capture its first non-empty output line. Never raises."""
    exe = cmd[0]
    result: dict[str, Any] = {
        "path": exe,
        "ok": False,
        "version": None,
        "returncode": None,
        "error": None,
    }
    if not os.path.isfile(exe):
        result["error"] = "executable not found"
        return result
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception as exc:  # noqa: BLE001 - a probe must never crash the selftest
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    output = f"{proc.stdout or ''}{proc.stderr or ''}"
    first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
    result["version"] = first_line or None
    result["returncode"] = proc.returncode
    result["ok"] = proc.returncode == 0 and bool(first_line)
    if not result["ok"] and not result["error"]:
        result["error"] = f"exit code {proc.returncode}"
    return result


def _probe_qt() -> dict[str, Any]:
    """Import Qt (no ``QApplication``/display) and report the version.

    Importing ``PySide6.QtCore`` exercises the Qt DLL load but does **not**
    require a display, so this check is safe on a headless/frozen run.
    """
    info: dict[str, Any] = {
        "import_ok": False,
        "error": None,
        "pyside6_version": None,
        "qt_version": None,
    }
    try:
        import PySide6
        from PySide6 import QtCore

        info["pyside6_version"] = getattr(PySide6, "__version__", None)
        info["qt_version"] = QtCore.qVersion()
        info["import_ok"] = True
    except Exception as exc:  # noqa: BLE001 - report, never raise
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _probe_libmpv() -> dict[str, Any]:
    """Load libmpv headlessly and read its version. Never raises.

    Constructs an ``mpv.MPV`` with ``vo=null`` (no window/surface) purely to read
    the ``mpv-version`` property, then tears it down. The event thread is left on
    its default (is `True`): ``mpv_terminate_destroy`` blocks waiting for the
    client event queue to drain, so a player created with ``start_event_thread=
    False`` deadlocks on :meth:`terminate` — the event thread must be consuming
    events for the handle to shut down cleanly.
    """
    from vdl import paths

    info: dict[str, Any] = {
        "ok": False,
        "version": None,
        "client_api_version": None,
        "dll": paths.libmpv_dll(),
        "error": None,
    }
    player = None
    try:
        from vdl.player import mpv as mpv_mod

        info["client_api_version"] = ".".join(str(n) for n in mpv_mod.MPV_VERSION)
        player = mpv_mod.MPV(vo="null", config=False)
        info["version"] = player.mpv_version
        info["ok"] = True
    except Exception as exc:  # noqa: BLE001 - report, never raise
        info["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if player is not None:
            try:
                player.terminate()
            except Exception:  # pragma: no cover - teardown must never raise
                pass
    return info


def _dll_search_report() -> dict[str, Any]:
    """Report whether ``_MEIPASS`` still leaks into this process's ``PATH``."""
    meipass = getattr(sys, "_MEIPASS", None)
    entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    leaks = False
    if meipass:
        meipass_norm = os.path.normcase(os.path.normpath(meipass))
        leaks = any(os.path.normcase(os.path.normpath(entry)) == meipass_norm for entry in entries)
    return {
        "meipass": meipass,
        "meipass_in_path": leaks,
        "path_tail": entries[-3:],
    }


def _selftest() -> int:
    """Headless readiness probe; writes ``selftest.json`` to the CWD (leaf 7.4).

    Deliberately avoids constructing a ``QApplication``/window so it runs in CI
    and inside the frozen ``--windowed`` exe. Returns ``0`` iff every required
    check passes.
    """
    from vdl import __version__, logging_setup, paths

    log = logging_setup.setup_logging()
    log.info("selftest: vdl %s starting", __version__)

    errors: list[str] = []
    resources = {
        "ffmpeg_exe": paths.ffmpeg_exe(),
        "ffprobe_exe": paths.ffprobe_exe(),
        "deno_exe": paths.deno_exe(),
        "libmpv_dll": paths.libmpv_dll(),
    }
    resource_report = {
        name: {"path": value, "exists": os.path.isfile(value)} for name, value in resources.items()
    }
    for name, entry in resource_report.items():
        if not entry["exists"]:
            errors.append(f"missing resource: {name} -> {entry['path']}")
    log.info("selftest: resolved %d resources", len(resource_report))

    dll_search = _dll_search_report()
    if dll_search["meipass_in_path"]:
        errors.append("_MEIPASS still present in PATH (DLL search not sanitized)")
    log.info("selftest: dll search sanitized=%s", not dll_search["meipass_in_path"])

    # Spawning these sidecars proves the leaked SetDllDirectoryW is cleared (7.3).
    log.info("selftest: probing sidecar executables (subprocess)")
    ffmpeg = _run_version([resources["ffmpeg_exe"], "-version"])
    ffprobe = _run_version([resources["ffprobe_exe"], "-version"])
    deno = _run_version([resources["deno_exe"], "--version"])
    for name, probe in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe), ("deno", deno)):
        if not probe["ok"]:
            errors.append(f"{name} subprocess failed: {probe['error']}")
    log.info("selftest: sidecars ok (ffmpeg=%s, deno=%s)", ffmpeg["ok"], deno["ok"])

    log.info("selftest: importing Qt (headless)")
    qt = _probe_qt()
    if not qt["import_ok"]:
        errors.append(f"Qt import failed: {qt['error']}")
    log.info("selftest: qt import ok=%s", qt["import_ok"])

    log.info("selftest: loading libmpv (headless)")
    libmpv = _probe_libmpv()
    if not libmpv["ok"]:
        errors.append(f"libmpv load failed: {libmpv['error']}")
    log.info("selftest: libmpv ok=%s (%s)", libmpv["ok"], libmpv["version"])

    report: dict[str, Any] = {
        "vdl_version": __version__,
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "ok": not errors,
        "errors": errors,
        "dll_search": dll_search,
        "resources": resource_report,
        "qt_import_ok": qt["import_ok"],
        "qt": qt,
        "libmpv_version": libmpv.get("version"),
        "libmpv": libmpv,
        "ffmpeg_version": ffmpeg.get("version"),
        "ffmpeg": ffmpeg,
        "ffprobe_version": ffprobe.get("version"),
        "ffprobe": ffprobe,
        "deno_version": deno.get("version"),
        "deno": deno,
        "user_data_dir": str(paths.user_data_dir()),
        "log_file": str(logging_setup.log_file_path()),
    }

    out_path = Path.cwd() / "selftest.json"
    try:
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("selftest: wrote %s", out_path)
    except OSError as exc:
        errors.append(f"could not write {out_path}: {exc}")
        report["ok"] = False

    log.info(
        "selftest: ok=%s (ffmpeg=%s, deno=%s, libmpv=%s)",
        report["ok"],
        ffmpeg.get("version"),
        deno.get("version"),
        libmpv.get("version"),
    )
    for err in errors:
        log.warning("selftest: %s", err)

    # sys.stdout is None in a frozen --windowed build; never print() unguarded.
    if sys.stdout is not None:
        status = "OK" if report["ok"] else "FAILED"
        # ASCII-only: a frozen/dev console may use a non-UTF-8 code page (cp1252).
        print(f"vdl selftest {status} - vdl {__version__}")
        print(f"  ffmpeg : {ffmpeg.get('version')}")
        print(f"  ffprobe: {ffprobe.get('version')}")
        print(f"  deno   : {deno.get('version')}")
        print(f"  libmpv : {libmpv.get('version')}")
        print(f"  json   : {out_path}")
        for err in errors:
            print(f"  ERROR  : {err}")

    return 0 if report["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    """Entry point shared by ``python -m vdl`` and the ``video-downloader`` script."""
    from vdl import paths

    # 7.3: undo PyInstaller's leaky DLL search dir before anything loads a DLL.
    paths._sanitize_dll_search()

    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args:
        return _selftest()

    from vdl import app

    return app.run([sys.argv[0], *args])


if __name__ == "__main__":
    raise SystemExit(main())
