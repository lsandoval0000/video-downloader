"""Unit tests for :class:`~vdl.ui.download_panel.DownloadPanel` URL input (10.7).

Covers the clipboard append fix: repeating ``set_url`` only ever filled an empty
box, so a *second* clipboard copy was dropped. ``append_url`` instead adds each
subsequent copy on its own line, skipping junk and exact duplicates, while
``set_url`` keeps its original "fill-only-when-empty" contract.

Hermetic: a temp ``ConfigStore`` (never the real user-data dir) plus a plain
``DownloadQueue``; the clipboard watcher itself is not exercised.
"""

from __future__ import annotations

from pathlib import Path


def _make_panel(tmp_path: Path):
    from vdl.config import ConfigStore
    from vdl.core.queue import DownloadQueue
    from vdl.ui.download_panel import DownloadPanel

    config = ConfigStore(path=tmp_path / "config.json").load()
    return DownloadPanel(config, DownloadQueue(config.settings))


def test_append_url_three_distinct_copies_make_three_lines(qapp, tmp_path: Path) -> None:
    panel = _make_panel(tmp_path)
    try:
        assert panel.append_url("https://a.example.com/1") is True
        assert panel.append_url("https://b.example.com/2") is True
        assert panel.append_url("https://c.example.com/3") is True
        assert panel._urls.toPlainText().splitlines() == [
            "https://a.example.com/1",
            "https://b.example.com/2",
            "https://c.example.com/3",
        ]
    finally:
        panel.close()


def test_append_url_skips_exact_duplicates(qapp, tmp_path: Path) -> None:
    panel = _make_panel(tmp_path)
    try:
        assert panel.append_url("https://a.example.com/1") is True
        assert panel.append_url("https://b.example.com/2") is True
        assert panel.append_url("https://a.example.com/1") is False
        assert panel._urls.toPlainText().splitlines() == [
            "https://a.example.com/1",
            "https://b.example.com/2",
        ]
    finally:
        panel.close()


def test_append_url_rejects_junk(qapp, tmp_path: Path) -> None:
    panel = _make_panel(tmp_path)
    try:
        assert panel.append_url("not a url") is False
        assert panel.append_url("") is False
        assert panel._urls.toPlainText() == ""
    finally:
        panel.close()


def test_set_url_still_only_fills_an_empty_box(qapp, tmp_path: Path) -> None:
    panel = _make_panel(tmp_path)
    try:
        assert panel.set_url("https://a.example.com/1") is True
        # The original contract is preserved: a non-empty box is never overwritten.
        assert panel.set_url("https://b.example.com/2") is False
        assert panel._urls.toPlainText() == "https://a.example.com/1"
    finally:
        panel.close()
