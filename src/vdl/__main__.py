"""Module entrypoint for ``python -m vdl`` and the console script.

Intentionally thin: the real bootstrap lives in :mod:`vdl.app`. The two jobs
done here are (a) sanitising the process DLL search path *before* any DLL is
loaded (leaf 7.3), and (b) handling ``--selftest``, which must return before a
window — or even a ``QApplication`` — is created so the frozen exe can be probed
headlessly (leaf 7.4).
"""

from __future__ import annotations

import sys


def _selftest() -> int:
    """Headless readiness probe (stub — expanded in leaf 7.4).

    Deliberately avoids constructing a ``QApplication``/window so it can run in
    CI and inside the frozen ``--windowed`` exe.
    """
    from vdl import __version__, logging_setup, paths

    log = logging_setup.setup_logging()
    log.info("selftest: vdl %s starting", __version__)
    checks = {
        "ffmpeg_exe": paths.ffmpeg_exe(),
        "ffprobe_exe": paths.ffprobe_exe(),
        "deno_exe": paths.deno_exe(),
        "libmpv_dll": paths.libmpv_dll(),
        "user_data_dir": str(paths.user_data_dir()),
        "log_file": str(logging_setup.log_file_path()),
    }
    for name, value in checks.items():
        log.info("selftest: %s = %s", name, value)

    # sys.stdout is None in a frozen --windowed build; never print() unguarded.
    if sys.stdout is not None:
        print(f"vdl selftest OK — vdl {__version__}")
    return 0


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
