"""Scheduled downloads engine (extra #13, leaf 6.4).

Qt-light by design: the *due* computation (:func:`is_due`, :func:`next_occurrence`)
and the :class:`ScheduleItem` model are pure and dependency-free, so they are
unit-testable with a frozen clock. Only the thin :class:`Scheduler` driver pulls in
Qt (``QObject`` / ``QTimer``) to poll from the GUI thread.

Persistence lands in ``user_data_dir()/schedules.json`` through an atomic
(temp file + :func:`os.replace`) write, mirroring :mod:`vdl.config`, so a crash
mid-save can never leave a half-written file.

Missed-item policy (plan gotcha): a **one-shot** item whose trigger time elapsed
while the app was closed is marked ``missed`` on the next launch and is *never*
fired late. A repeating (daily) item that elapsed is simply advanced to its next
occurrence without firing, so a stale download never starts by surprise.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QTimer, Signal

from vdl.paths import user_data_dir

if TYPE_CHECKING:
    from collections.abc import Callable

    from vdl.core.queue import DownloadQueue

logger = logging.getLogger("vdl.core.scheduler")

#: File name (under :func:`vdl.paths.user_data_dir`) holding the schedule list.
SCHEDULES_FILENAME = "schedules.json"

# ── repeat vocabulary ────────────────────────────────────────────────────────
REPEAT_ONCE = "once"
REPEAT_DAILY = "daily"
REPEATS: tuple[str, ...] = (REPEAT_ONCE, REPEAT_DAILY)

# ── item status vocabulary ───────────────────────────────────────────────────
STATUS_PENDING = "pending"
STATUS_FIRED = "fired"
STATUS_MISSED = "missed"
STATUS_CANCELLED = "cancelled"
STATUSES: tuple[str, ...] = (STATUS_PENDING, STATUS_FIRED, STATUS_MISSED, STATUS_CANCELLED)
#: Statuses a one-shot item never leaves (repeating items stay ``pending``).
TERMINAL_STATUSES = frozenset({STATUS_FIRED, STATUS_MISSED, STATUS_CANCELLED})

_SECONDS_PER_DAY = 86400.0
_MAX_CATCHUP_DAYS = 3660  # safety bound on the daily catch-up loop (~10 years)
#: Default poll cadence for the driver timer.
DEFAULT_INTERVAL_MS = 30_000


@dataclass
class ScheduleItem:
    """One scheduled download.

    ``job`` holds the keyword arguments handed to
    :meth:`vdl.core.queue.DownloadQueue.add` — at minimum ``url``, optionally
    ``title`` and per-job overrides (e.g. ``format_selector``).

    ``when`` is a POSIX timestamp (seconds); ``repeat`` is ``"once"`` or
    ``"daily"``. A ``once`` item becomes terminal (``fired``/``missed``); a
    ``daily`` item stays ``pending`` and its ``when`` advances on every fire.
    """

    when: float
    repeat: str = REPEAT_ONCE
    job: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = STATUS_PENDING
    last_fired: float | None = None

    @property
    def url(self) -> str:
        """The target URL from the embedded job spec (``""`` if absent)."""
        return str(self.job.get("url", "") or "")


# ── pure due-computation (unit-testable with a frozen clock) ──────────────────


def is_due(item: ScheduleItem, now: float) -> bool:
    """Return ``True`` when a *pending* item's trigger time has been reached.

    Pure: it inspects only ``item`` and the caller-supplied ``now`` (seconds),
    so tests can pass a frozen clock. Terminal items are never due.
    """
    return item.status == STATUS_PENDING and item.when <= float(now)


def next_occurrence(when: float, repeat: str, now: float) -> float | None:
    """The next fire time *strictly after* ``now`` for a repeating item.

    Returns ``None`` for a one-shot item (or an unknown repeat value, treated
    defensively as one-shot). Daily repeats keep their local *wall-clock*
    time-of-day: each step advances one calendar day in local time, so a
    daylight-saving change does not shift the scheduled hour.
    """
    if repeat != REPEAT_DAILY:
        return None
    target = float(when)
    if target > float(now):
        return target

    # Jump most of the gap in one whole-day step, then walk forward in local
    # wall-clock until strictly in the future (handles DST-length days).
    skipped = int((float(now) - target) // _SECONDS_PER_DAY)
    candidate = target
    if skipped > 0:
        candidate = (datetime.fromtimestamp(target) + timedelta(days=skipped)).timestamp()
    guard = 0
    while candidate <= float(now) and guard < _MAX_CATCHUP_DAYS:
        candidate = (datetime.fromtimestamp(candidate) + timedelta(days=1)).timestamp()
        guard += 1
    return float(candidate)


# ── (de)serialization ─────────────────────────────────────────────────────────


def _coerce_item(raw: Any) -> ScheduleItem | None:
    """Build a :class:`ScheduleItem` from untrusted JSON, or ``None`` if invalid."""
    if not isinstance(raw, dict):
        return None
    job = raw.get("job")
    if not isinstance(job, dict) or not str(job.get("url", "") or "").strip():
        return None
    try:
        when = float(raw["when"])
    except (KeyError, TypeError, ValueError):
        return None

    repeat = raw.get("repeat")
    if repeat not in REPEATS:
        repeat = REPEAT_ONCE
    status = raw.get("status")
    if status not in STATUSES:
        status = STATUS_PENDING

    item_id = raw.get("id")
    if not isinstance(item_id, str) or not item_id:
        item_id = uuid.uuid4().hex

    last = raw.get("last_fired")
    last_fired = (
        float(last) if isinstance(last, (int, float)) and not isinstance(last, bool) else None
    )
    return ScheduleItem(
        when=when,
        repeat=repeat,
        job=dict(job),
        id=item_id,
        status=status,
        last_fired=last_fired,
    )


class Scheduler(QObject):
    """Polls scheduled items and enqueues their jobs when they come due.

    The driver runs entirely on the GUI thread (a ``QTimer``), so enqueuing on
    the shared :class:`~vdl.core.queue.DownloadQueue` never crosses threads.

    Signals
    -------
    item_fired(ScheduleItem): the item's job was enqueued.
    item_missed(ScheduleItem): a one-shot item was found stale at startup.
    items_changed(): the item list/state changed (views should refresh).
    """

    item_fired = Signal(object)
    item_missed = Signal(object)
    items_changed = Signal()

    def __init__(
        self,
        queue: DownloadQueue,
        *,
        path: str | os.PathLike[str] | None = None,
        interval_ms: int = DEFAULT_INTERVAL_MS,
        clock: Callable[[], float] | None = None,
        autostart: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._queue = queue
        self.path = Path(path) if path is not None else user_data_dir() / SCHEDULES_FILENAME
        self._clock: Callable[[], float] = clock or time.time
        self._items: list[ScheduleItem] = []

        self._load()
        self._reconcile_on_start()

        self._timer = QTimer(self)
        self._timer.setInterval(max(1000, int(interval_ms)))
        self._timer.timeout.connect(self.check_due)
        if autostart:
            self._timer.start()

    # ── queries ──────────────────────────────────────────────────────────────
    @property
    def items(self) -> list[ScheduleItem]:
        """A snapshot copy of the scheduled items (insertion order)."""
        return list(self._items)

    def is_running(self) -> bool:
        return self._timer.isActive()

    # ── CRUD ─────────────────────────────────────────────────────────────────
    def add(self, item: ScheduleItem) -> ScheduleItem:
        """Append ``item``, persist, and notify views."""
        self._items.append(item)
        self._save()
        self.items_changed.emit()
        return item

    def remove(self, item_id: str) -> bool:
        """Cancel/delete the item with ``item_id``. ``True`` if it existed."""
        for index, item in enumerate(self._items):
            if item.id == item_id:
                del self._items[index]
                self._save()
                self.items_changed.emit()
                logger.info("scheduler: removed item %s", item_id)
                return True
        return False

    def clear_finished(self) -> int:
        """Drop terminal (fired/missed/cancelled) one-shot items; return the count."""
        before = len(self._items)
        self._items = [item for item in self._items if item.status not in TERMINAL_STATUSES]
        removed = before - len(self._items)
        if removed:
            self._save()
            self.items_changed.emit()
        return removed

    # ── driver ───────────────────────────────────────────────────────────────
    def start(self) -> None:
        """Begin polling (no-op if already running)."""
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """Stop polling (idempotent)."""
        self._timer.stop()

    def check_due(self, now: float | None = None) -> list[ScheduleItem]:
        """Fire every pending item whose time has come; return the fired items.

        ``now`` overrides the clock (tests may pass a frozen value). Repeating
        items are rescheduled to their next occurrence; one-shot items become
        terminal.
        """
        moment = self._clock() if now is None else float(now)
        fired: list[ScheduleItem] = []
        changed = False
        for item in list(self._items):
            if not is_due(item, moment):
                continue
            changed = True
            if not item.url:
                item.status = STATUS_MISSED
                self.item_missed.emit(item)
                continue
            self._enqueue(item)
            item.last_fired = moment
            following = next_occurrence(item.when, item.repeat, moment)
            if following is None:
                item.status = STATUS_FIRED
            else:
                item.when = following
            logger.info("scheduler: fired %s (%s)", item.url, item.repeat)
            self.item_fired.emit(item)
            fired.append(item)
        if changed:
            self._save()
            self.items_changed.emit()
        return fired

    def _enqueue(self, item: ScheduleItem) -> None:
        kwargs = dict(item.job)
        url = str(kwargs.pop("url", "") or "")
        if not url:
            return
        self._queue.add(url, **kwargs)

    def _reconcile_on_start(self) -> None:
        """Resolve items that elapsed while the app was closed (plan gotcha)."""
        moment = self._clock()
        changed = False
        for item in self._items:
            if item.status != STATUS_PENDING or item.when > moment:
                continue
            changed = True
            if item.repeat == REPEAT_ONCE:
                item.status = STATUS_MISSED
                logger.warning("scheduler: one-shot item missed while closed: %s", item.url)
                self.item_missed.emit(item)
            else:
                following = next_occurrence(item.when, item.repeat, moment)
                if following is not None:
                    item.when = following
                logger.info("scheduler: advanced missed daily item to %s", item.when)
        if changed:
            self._save()
            self.items_changed.emit()

    # ── persistence ──────────────────────────────────────────────────────────
    def _load(self) -> None:
        raw: Any = None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            logger.warning("scheduler: cannot read %s (%s); starting empty", self.path, exc)
            return
        entries = raw.get("items") if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            return
        for entry in entries:
            item = _coerce_item(entry)
            if item is not None:
                self._items.append(item)

    def _save(self) -> None:
        payload = {"items": [asdict(item) for item in self._items]}
        try:
            self._atomic_write(payload)
        except OSError as exc:  # pragma: no cover - disk failures are environmental
            logger.error("scheduler: could not persist %s (%s)", self.path, exc)

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=self.path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(tmp_name)
            raise
