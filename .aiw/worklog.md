# Worklog — video-downloader

## [2026-10-11] Session — A.L.L.I.C.E. orchestration (bootstrap)

- **Goal:** Light, portable desktop app (Python) to download videos from any site supporting a given URL, wrapping `yt-dlp` + `ffmpeg`, with a full extras set and an embedded libmpv player. Ships as a **portable folder (PyInstaller onedir)**.
- **Project root:** `D:\Desarrollo\Repos\video-downloader` (empty greenfield at bootstrap).

### Decisions (user, 2026-10-11)
- **Packaging:** portable folder only — PyInstaller **onedir** (no onefile artifact).
- **Licensing:** open-source is fine → standard **GPL** builds of ffmpeg + libmpv acceptable.
- **Stack:** Python. **GUI:** PySide6 (needed for libmpv `wid` embedding).
- **yt-dlp:** Python package (in-process), per exploration recommendation.
- **Player:** full tier — embedded **libmpv**.
- Next: planner to build `.aiw/plan.md`.

> Note: the explorer's entry below was written to this file, replacing the initial bootstrap header. Header restored here; explorer entry preserved verbatim.

## [2026-10-11 00:00] explorer — root: single-exe feasibility for Python video-downloader (libmpv+ffmpeg+yt-dlp)
- Status: DONE
- Summary: Researched packaging bundlers, sidecar binary bundling, libmpv/VLC Python bindings, codec coverage, GUI toolkits, and licensing/AV trade-offs. Verdict: fully achievable as a portable FOLDER (onedir); a genuine onefile is technically possible but carries real costs (extraction-on-launch, AV false positives, large size). Recommended: PyInstaller onedir as primary, onefile as optional.
- Files touched: none (created this worklog only)
- Decisions: none
- Issues: PyInstaller does not prominently document AV false positives in current docs (Nuitka does, officially). Exact Windows libmpv DLL naming confirmed from python-mpv source (`mpv-2.dll`/`libmpv-2.dll`/`mpv-1.dll`). Exact PySide6 installed size not measured (only meta-wheel 579 KB observed; Essentials/Addons pull the bulk).

## [2026-10-11] planner — root: build plan for portable Windows video-downloader
- Status: DONE
- Summary: Wrote `.aiw/plan.md` — 10 branches × 40 leaves (depth 2; within 10-wide/5-deep limits), ~786 lines. All 17 extras mapped to discrete tester-verifiable leaves via a traceability table. Includes Success Criteria, Context & References, Gotchas, Implementation Blueprint/pseudocode, a real PowerShell Validation Loop (L0–L4) with a 17-row acceptance matrix, Anti-Patterns, Risks, and a `## Plan Rulings` section seeded with R-001. CONFIDENCE 8/10.
- Files touched: `.aiw/plan.md` (only). Note: node constraint forbade editing the worklog, so the orchestrator recorded this entry.
- Decisions (evidence-backed): PySide6-Essentials 6.12.0 confirmed to work on installed Python 3.14.6 (cp310-abi3 wheels); PyInstaller≥6.15 is the 3.14 floor; venv+pip (no uv); PySide6-Essentials + Qt-module exclusions for "light"; vendor `mpv.py` co-located with `libmpv-2.dll`; bundle deno≥2.3.0 + `yt-dlp-ejs`.
- Issues: Plan sits exactly at the 10-branch ceiling (no room for a new top-level branch). Exact bundled sizes measured-at-build (budget ≤350 MB unpacked).
- Next: builder vertical slice — branch 1 → 2.1 → 5.1/5.2 → 6.1 → 7.4, then fan out to remaining extras.

## [2026-10-11 01:36] builder — 1.1–1.4: Foundations & Scaffolding + git init
- Status: DONE
- Summary: Created the full branch-1 skeleton for the PySide6 video-downloader: src-layout package `vdl` with `paths.py` (single frozen/resource resolver), `config.py` (Settings/Preset store, atomic + corrupt-safe), `logging_setup.py` (rotating 2 MB file log + sys/threading excepthook + Qt dialog), and a thin `__main__.py`/`app.py` bootstrap that enforces the Qt-before-`LC_NUMERIC` ordering. Dependency manifests, `pyproject.toml` (ruff/mypy/pytest), and 16 unit tests added. `git init` done; three descriptive commits made; `.venv/` and `vendor/` are ignored.
- Files touched: `.gitignore`, `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `src/vdl/{__init__,__main__,app,paths,config,logging_setup}.py`, `src/vdl/{core,player,ui,resources}/__init__.py`, `src/vdl/ui/main_window.py` (placeholder), `src/vdl/resources/{icons,styles}/.gitkeep`, `tests/conftest.py`, `tests/unit/{test_paths,test_config}.py`
- Decisions: (1) Editable install (`pip install -e .`) is used so `python -m vdl` works from a src-layout without PYTHONPATH tricks; `[project.dependencies]` left empty with requirements.txt as the single source of truth during scaffolding. (2) `resource_path()` resolves native binaries under `<repo>/vendor/` in dev and `<_MEIPASS>/…` when frozen — binary subdirs are `bin/` and `libmpv/` (per the brief's `_internal/bin/ffmpeg.exe` acceptance), so `build/vdl.spec` (leaf 7.2) must place its binaries in `bin/`, not `_internal/` root as the plan's sample spec shows. (3) `platformdirs.user_data_dir(appname, appauthor=False)` to avoid the redundant `<...>\VideoDownloader\VideoDownloader` nesting that the bare call produces (matches the plan's intended `%…%\VideoDownloader`). (4) `--selftest` is a headless stub returning before any `QApplication`/window (leaf 7.4 fills it in). (5) `.aiw/` kept tracked; worklog appended (not rewritten).
- Issues: Git had no configured identity, so a repo-local `user.name`/`user.email` (`Luis <luis@localhost>`) was set — amend if the address should differ. `_sanitize_dll_search()` fully implemented now (SetDllDirectoryW(None) + `_MEIPASS` PATH strip). No `build/`/`scripts/` fetch or spec files yet (branches 7.x). Validation: `ruff check` clean, `ruff format --check` clean, `mypy src` clean, `pytest tests/unit -q` 16 passed, `python -m vdl --selftest` exit 0, offscreen GUI bootstrap exit 0.
- Next: branch 2.1 (`core/options.py`) pure yt-dlp opts builder; leaf 7.2 must place sidecars under `_internal/bin/` and `_internal/libmpv/` to match `paths.resource_path`.
