"""Download history: yt-dlp archive + a SQLite index (extra #14, engine side).

Two deliberately separate stores (plan "Implementation Notes" — do not merge):

* **``archive.txt``** — yt-dlp's own plain-text download archive, one
  ``"<extractor_key> <id>"`` line per completed video. It is yt-dlp's *source of
  truth* and follows an **append-only contract**: yt-dlp appends, and this module
  only ever *reads* it (the plan's gotcha). Rewriting it would corrupt resume
  behaviour and is forbidden.
* **``history.db``** — a rich SQLite index (id, title, url, path, status,
  timestamp) that the UI browses and that survives independently of the archive.

Everything here is pure stdlib (``sqlite3``), Qt-free and import-light so it can
be unit-tested headless and reused by the worker thread.
"""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vdl.paths import user_data_dir

#: yt-dlp's plain-text archive file name.
ARCHIVE_FILENAME = "archive.txt"
#: The rich SQLite history index file name.
HISTORY_DB_FILENAME = "history.db"

# ── status vocabulary (kept as plain strings for the DB + UI) ────────────────
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"  # already present in the yt-dlp archive
STATUS_CANCELLED = "cancelled"


def archive_path() -> str:
    """Absolute path to yt-dlp's plain-text download archive.

    Single definition, owned here (leaf 4.2); :mod:`vdl.core.options` imports it
    to inject ``download_archive``. Resolving (and lazily creating) the
    user-data directory is the only filesystem side effect.
    """
    return str(user_data_dir() / ARCHIVE_FILENAME)


def history_db_path() -> str:
    """Absolute path to the SQLite history index."""
    return str(user_data_dir() / HISTORY_DB_FILENAME)


# ── yt-dlp archive: READ-ONLY helpers (never rewrite the file) ────────────────


def read_archive(path: str | os.PathLike[str] | None = None) -> set[str]:
    """Return the set of *raw* archive lines (yt-dlp's ``"<key> <id>"`` records).

    Missing or unreadable files yield an empty set — this never raises and never
    writes (the archive is append-only and owned by yt-dlp).
    """
    archive = Path(path) if path is not None else Path(archive_path())
    if not archive.is_file():
        return set()
    lines: set[str] = set()
    try:
        with archive.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.strip()
                if line and not line.startswith("#"):
                    lines.add(line)
    except OSError:
        return set()
    return lines


def archive_ids(path: str | os.PathLike[str] | None = None) -> set[str]:
    """Return just the video-id token of each archive line.

    yt-dlp writes ``"<extractor_key> <id>"`` (e.g. ``"youtube dQw4w9WgXcQ"``);
    the id is the last whitespace-separated token.
    """
    return {line.split()[-1] for line in read_archive(path) if line.split()}


def is_in_archive(
    video_id: str | None,
    *,
    archive: str | os.PathLike[str] | None = None,
) -> bool:
    """Return ``True`` if ``video_id`` is already recorded in the archive.

    This is the "already in archive → skip" helper the UI can query before
    enqueuing a URL (extra #14). A full archive line (``"youtube <id>"``) is also
    accepted so callers holding yt-dlp's ``_make_archive_id`` output can pass it
    directly. An empty/``None`` id is never "in" the archive.
    """
    if not video_id:
        return False
    token = video_id.strip()
    if not token:
        return False
    lines = read_archive(archive)
    if token in lines:
        return True
    return token.split()[-1] in {line.split()[-1] for line in lines if line.split()}


# ── SQLite history index ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class HistoryRecord:
    """One row of the history index (UI-facing, immutable snapshot)."""

    id: int
    video_id: str | None
    title: str
    url: str
    path: str | None
    status: str
    timestamp: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id  TEXT,
    title     TEXT NOT NULL DEFAULT '',
    url       TEXT NOT NULL,
    path      TEXT,
    status    TEXT NOT NULL DEFAULT '',
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_video_id ON history(video_id);
CREATE INDEX IF NOT EXISTS idx_history_url ON history(url);
CREATE INDEX IF NOT EXISTS idx_history_timestamp ON history(timestamp);
"""

_COLUMNS = ("id", "video_id", "title", "url", "path", "status", "timestamp")


def _row_to_record(row: Iterable[Any]) -> HistoryRecord:
    values = tuple(row)
    return HistoryRecord(
        id=int(values[0]),
        video_id=values[1] if values[1] is None else str(values[1]),
        title=str(values[2] or ""),
        url=str(values[3]),
        path=values[4] if values[4] is None else str(values[4]),
        status=str(values[5] or ""),
        timestamp=float(values[6]),
    )


class HistoryStore:
    """A small SQLite-backed index of past downloads.

    The store is intentionally tolerant: it creates its schema on first use,
    opens lazily, and accepts a custom ``path`` so tests can use a temp file. It
    is safe to instantiate with no argument (defaults to
    :func:`history_db_path`).

    Use it as a context manager to guarantee the connection is closed::

        with HistoryStore() as store:
            store.add("https://…", title="…", path="…", status=STATUS_DONE)
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path is not None else Path(history_db_path())
        self._conn: sqlite3.Connection | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────
    @property
    def connection(self) -> sqlite3.Connection:
        """The lazily-opened connection (schema is created on first access)."""
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path))
            conn.row_factory = None
            conn.executescript(_SCHEMA)
            conn.commit()
            self._conn = conn
        return self._conn

    def close(self) -> None:
        """Close the connection if open (idempotent)."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> HistoryStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        conn = self.connection
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        finally:
            cursor.close()

    # ── writes ───────────────────────────────────────────────────────────────
    def add(
        self,
        url: str,
        *,
        video_id: str | None = None,
        title: str = "",
        path: str | None = None,
        status: str = STATUS_DONE,
        timestamp: float | None = None,
    ) -> int:
        """Insert a history row and return its new integer id."""
        when = time.time() if timestamp is None else float(timestamp)
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO history (video_id, title, url, path, status, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (video_id, title, url, path, status, when),
            )
            return int(cursor.lastrowid or 0)

    def record_job(
        self,
        url: str,
        *,
        video_id: str | None = None,
        title: str = "",
        path: str | None = None,
        status: str = STATUS_DONE,
    ) -> int:
        """Convenience wrapper mirroring :meth:`add` (engine-facing vocabulary)."""
        return self.add(url, video_id=video_id, title=title, path=path, status=status)

    def update_status(
        self,
        record_id: int,
        status: str,
        *,
        path: str | None = None,
    ) -> bool:
        """Update a row's status (and optionally its path). ``True`` if it existed."""
        with self._cursor() as cursor:
            if path is None:
                cursor.execute("UPDATE history SET status = ? WHERE id = ?", (status, record_id))
            else:
                cursor.execute(
                    "UPDATE history SET status = ?, path = ? WHERE id = ?",
                    (status, path, record_id),
                )
            return cursor.rowcount > 0

    def delete(self, record_id: int) -> bool:
        """Delete one row. ``True`` if it existed."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM history WHERE id = ?", (record_id,))
            return cursor.rowcount > 0

    def clear(self) -> int:
        """Delete every row and return the number removed."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM history")
            return cursor.rowcount

    # ── reads ────────────────────────────────────────────────────────────────
    def items(self, *, limit: int | None = None, offset: int = 0) -> list[HistoryRecord]:
        """Return rows newest-first (by timestamp, then id)."""
        sql = f"SELECT {', '.join(_COLUMNS)} FROM history ORDER BY timestamp DESC, id DESC"
        params: tuple[object, ...] = ()
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = (int(limit), int(offset))
        elif offset:
            sql += " LIMIT -1 OFFSET ?"
            params = (int(offset),)
        with self._cursor() as cursor:
            return [_row_to_record(row) for row in cursor.execute(sql, params).fetchall()]

    def get(self, record_id: int) -> HistoryRecord | None:
        """Return a single row by id, or ``None``."""
        sql = f"SELECT {', '.join(_COLUMNS)} FROM history WHERE id = ?"
        with self._cursor() as cursor:
            row = cursor.execute(sql, (record_id,)).fetchone()
        return _row_to_record(row) if row is not None else None

    def find_by_video_id(self, video_id: str) -> list[HistoryRecord]:
        """Return all rows recorded for a given video id (newest-first)."""
        sql = (
            f"SELECT {', '.join(_COLUMNS)} FROM history WHERE video_id = ? "
            "ORDER BY timestamp DESC, id DESC"
        )
        with self._cursor() as cursor:
            return [_row_to_record(row) for row in cursor.execute(sql, (video_id,)).fetchall()]

    def count(self) -> int:
        """Total number of recorded rows."""
        with self._cursor() as cursor:
            return int(cursor.execute("SELECT COUNT(*) FROM history").fetchone()[0])

    def was_downloaded(self, video_id: str | None) -> bool:
        """``True`` if a *completed* row exists for ``video_id``."""
        if not video_id:
            return False
        with self._cursor() as cursor:
            row = cursor.execute(
                "SELECT 1 FROM history WHERE video_id = ? AND status = ? LIMIT 1",
                (video_id, STATUS_DONE),
            ).fetchone()
        return row is not None
