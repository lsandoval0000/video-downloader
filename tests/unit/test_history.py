"""Unit tests for :mod:`vdl.core.history` — stdlib only, no network, no PySide6.

Covers the yt-dlp archive *read* helpers ("already in archive → skip") against a
temp ``archive.txt``, and the SQLite :class:`HistoryStore` CRUD.
"""

from __future__ import annotations

from pathlib import Path

from vdl.core import history

# ── yt-dlp archive (append-only contract, read-only here) ────────────────────


def test_archive_path_and_db_path_are_separate_files() -> None:
    assert Path(history.archive_path()).name == "archive.txt"
    assert Path(history.history_db_path()).name == "history.db"


def test_archive_path_owned_by_history_module() -> None:
    """options re-exports the exact same callable (single source of truth)."""
    from vdl.core import options

    assert options.archive_path is history.archive_path


def test_read_archive_missing_file_is_empty(tmp_path: Path) -> None:
    assert history.read_archive(tmp_path / "nope.txt") == set()


def test_read_archive_and_ids(tmp_path: Path) -> None:
    archive = tmp_path / "archive.txt"
    archive.write_text(
        "youtube dQw4w9WgXcQ\n# a comment\n\nvimeo 12345\n",
        encoding="utf-8",
    )
    lines = history.read_archive(archive)
    assert lines == {"youtube dQw4w9WgXcQ", "vimeo 12345"}
    assert history.archive_ids(archive) == {"dQw4w9WgXcQ", "12345"}


def test_is_in_archive_matches_id_and_full_line(tmp_path: Path) -> None:
    archive = tmp_path / "archive.txt"
    archive.write_text("youtube dQw4w9WgXcQ\n", encoding="utf-8")

    assert history.is_in_archive("dQw4w9WgXcQ", archive=archive) is True
    assert history.is_in_archive("youtube dQw4w9WgXcQ", archive=archive) is True
    assert history.is_in_archive("not-downloaded", archive=archive) is False


def test_is_in_archive_handles_empty_and_missing(tmp_path: Path) -> None:
    assert history.is_in_archive(None, archive=tmp_path / "x.txt") is False
    assert history.is_in_archive("", archive=tmp_path / "x.txt") is False
    assert history.is_in_archive("abc", archive=tmp_path / "x.txt") is False


def test_read_archive_never_writes(tmp_path: Path) -> None:
    """The archive is yt-dlp's; reading must leave it byte-identical."""
    archive = tmp_path / "archive.txt"
    original = "youtube keep-me\n"
    archive.write_text(original, encoding="utf-8")
    history.read_archive(archive)
    history.is_in_archive("keep-me", archive=archive)
    assert archive.read_text(encoding="utf-8") == original


# ── SQLite HistoryStore ──────────────────────────────────────────────────────


def test_history_store_add_and_items(tmp_path: Path) -> None:
    with history.HistoryStore(tmp_path / "history.db") as store:
        first = store.add(
            "https://example.com/a",
            video_id="aaa",
            title="A",
            path=r"C:\dl\a.mp4",
            status=history.STATUS_DONE,
            timestamp=100.0,
        )
        second = store.add(
            "https://example.com/b",
            video_id="bbb",
            title="B",
            path=r"C:\dl\b.mp4",
            status=history.STATUS_ERROR,
            timestamp=200.0,
        )
        assert (first, second) == (1, 2)
        assert store.count() == 2

        rows = store.items()
        # newest-first by timestamp
        assert [r.video_id for r in rows] == ["bbb", "aaa"]
        assert rows[0].title == "B"
        assert rows[1].path == r"C:\dl\a.mp4"
        assert rows[1].status == history.STATUS_DONE


def test_history_store_get_and_find(tmp_path: Path) -> None:
    with history.HistoryStore(tmp_path / "history.db") as store:
        rid = store.add("https://example.com/a", video_id="aaa", title="A")
        assert store.get(rid) is not None
        assert store.get(rid).video_id == "aaa"  # type: ignore[union-attr]
        assert store.get(9999) is None
        assert [r.video_id for r in store.find_by_video_id("aaa")] == ["aaa"]
        assert store.find_by_video_id("zzz") == []


def test_history_store_was_downloaded(tmp_path: Path) -> None:
    with history.HistoryStore(tmp_path / "history.db") as store:
        store.add("https://example.com/a", video_id="aaa", status=history.STATUS_ERROR)
        store.add("https://example.com/b", video_id="bbb", status=history.STATUS_DONE)
        assert store.was_downloaded("bbb") is True
        assert store.was_downloaded("aaa") is False  # errored, not completed
        assert store.was_downloaded(None) is False


def test_history_store_update_status(tmp_path: Path) -> None:
    with history.HistoryStore(tmp_path / "history.db") as store:
        rid = store.add("https://example.com/a", video_id="aaa", status=history.STATUS_ERROR)
        assert store.update_status(rid, history.STATUS_DONE, path=r"C:\dl\a.mp4") is True
        row = store.get(rid)
        assert row is not None and row.status == history.STATUS_DONE
        assert row.path == r"C:\dl\a.mp4"
        assert store.update_status(9999, history.STATUS_DONE) is False


def test_history_store_delete_and_clear(tmp_path: Path) -> None:
    with history.HistoryStore(tmp_path / "history.db") as store:
        a = store.add("https://example.com/a", video_id="aaa")
        store.add("https://example.com/b", video_id="bbb")
        assert store.delete(a) is True
        assert store.delete(a) is False
        assert store.count() == 1
        assert store.clear() == 1
        assert store.count() == 0


def test_history_store_limit_offset(tmp_path: Path) -> None:
    with history.HistoryStore(tmp_path / "history.db") as store:
        for i in range(5):
            store.add(f"https://example.com/{i}", video_id=str(i), timestamp=float(i))
        page = store.items(limit=2, offset=1)
        assert [r.video_id for r in page] == ["3", "2"]


def test_history_store_persists_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    with history.HistoryStore(db) as store:
        store.add("https://example.com/a", video_id="aaa", title="A")
    with history.HistoryStore(db) as reopened:
        assert reopened.count() == 1
        assert reopened.items()[0].title == "A"


def test_history_store_record_job_alias(tmp_path: Path) -> None:
    with history.HistoryStore(tmp_path / "history.db") as store:
        rid = store.record_job("https://example.com/a", video_id="aaa", title="A")
        assert store.get(rid) is not None
