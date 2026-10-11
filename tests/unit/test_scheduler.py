"""Unit tests for :mod:`vdl.core.scheduler` (extra #13) — frozen clock.

Covers:

* the pure due-computation (:func:`is_due` / :func:`next_occurrence`) with an
  injected ``now`` — one-shot past / future / boundary and daily
  strictly-future / DST-safe behaviour;
* the **missed-one-shot policy** (a one-shot item whose time elapsed while the
  app was closed is marked ``missed`` and never fired late).

Headless: no display and no network. ``vdl.core.scheduler`` imports ``QtCore``
for its driver, so a missing PySide6 skips the whole module (``importorskip``);
the pure functions still run without any ``QApplication``. The single test that
touches the Qt ``Scheduler`` class needs no event loop — signal connections are
delivered directly.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, timedelta, tzinfo
from datetime import datetime as _datetime

import pytest

scheduler = pytest.importorskip("vdl.core.scheduler")

ScheduleItem = scheduler.ScheduleItem
is_due = scheduler.is_due
next_occurrence = scheduler.next_occurrence

REPEAT_ONCE = scheduler.REPEAT_ONCE
REPEAT_DAILY = scheduler.REPEAT_DAILY
STATUS_PENDING = scheduler.STATUS_PENDING
STATUS_FIRED = scheduler.STATUS_FIRED
STATUS_MISSED = scheduler.STATUS_MISSED
STATUS_CANCELLED = scheduler.STATUS_CANCELLED

#: A frozen reference instant (seconds) used across the pure tests.
NOW = 1_700_000_000.0

_SECONDS_PER_DAY = 86400.0


# ── deterministic time zones for the daily-repeat tests ──────────────────────
# The CI host has no system tz database (``tzdata`` is not installed), so we
# inject tiny, self-contained ``tzinfo`` implementations instead of ``zoneinfo``.
# Each returns a ``datetime`` subclass whose ``fromtimestamp`` uses that zone;
# arithmetic keeps the subclass, so ``next_occurrence``'s calendar-day stepping
# is exercised exactly as in production but in a known zone.


class _SpringForwardTz(tzinfo):
    """A deterministic zone with one DST jump: std UTC+0 → DST UTC+1.

    Every local wall-clock instant on/after the transition date is DST, which is
    enough to distinguish calendar-day stepping (DST-safe) from fixed
    86 400-second stepping.
    """

    _TRANSITION = _datetime(2026, 3, 29, 0, 0)

    def utcoffset(self, dt: _datetime | None) -> timedelta:
        if dt is not None and dt.replace(tzinfo=None) >= self._TRANSITION:
            return timedelta(hours=1)
        return timedelta(0)

    def dst(self, dt: _datetime | None) -> timedelta:
        return self.utcoffset(dt)

    def tzname(self, dt: _datetime | None) -> str:
        return "TEST/SPRINGFORWARD"


def _zoned_datetime(tz: tzinfo) -> type[_datetime]:
    """Return a ``datetime`` subclass whose ``fromtimestamp`` uses ``tz``."""

    class _Zoned(_datetime):
        @classmethod
        def fromtimestamp(cls, ts: float) -> _datetime:
            base = _datetime.fromtimestamp(ts, tz)
            return cls(
                base.year,
                base.month,
                base.day,
                base.hour,
                base.minute,
                base.second,
                base.microsecond,
                tzinfo=tz,
            )

    return _Zoned


_UTC = _zoned_datetime(UTC)
_SPRING = _zoned_datetime(_SpringForwardTz())


# ── is_due: pending + when <= now (terminal items never due) ─────────────────


def test_is_due_one_shot_past() -> None:
    item = ScheduleItem(when=NOW - 10, repeat=REPEAT_ONCE)
    assert is_due(item, NOW) is True


def test_is_due_one_shot_future() -> None:
    item = ScheduleItem(when=NOW + 10, repeat=REPEAT_ONCE)
    assert is_due(item, NOW) is False


def test_is_due_boundary_is_inclusive() -> None:
    """``when == now`` is due (the comparison is ``<=``)."""
    item = ScheduleItem(when=NOW, repeat=REPEAT_ONCE)
    assert is_due(item, NOW) is True


@pytest.mark.parametrize("status", [STATUS_FIRED, STATUS_MISSED, STATUS_CANCELLED])
def test_is_due_terminal_items_are_never_due(status: str) -> None:
    item = ScheduleItem(when=NOW - 10, status=status)
    assert is_due(item, NOW) is False


def test_is_due_only_pending_matters() -> None:
    statuses = {
        STATUS_PENDING: True,
        STATUS_FIRED: False,
        STATUS_MISSED: False,
        STATUS_CANCELLED: False,
    }
    for status, expected in statuses.items():
        assert is_due(ScheduleItem(when=NOW - 1, status=status), NOW) is expected


# ── next_occurrence: one-shot → None; daily → strictly after now ──────────────


@pytest.mark.parametrize("when", [NOW - 10, NOW, NOW + 10])
def test_next_occurrence_one_shot_is_none(when: float) -> None:
    assert next_occurrence(when, REPEAT_ONCE, NOW) is None


def test_next_occurrence_unknown_repeat_is_none() -> None:
    # Unknown repeats are treated defensively as one-shot.
    assert next_occurrence(NOW - 10, "weekly", NOW) is None


def test_next_occurrence_daily_future_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler, "datetime", _UTC)
    future = NOW + 3600.0
    assert next_occurrence(future, REPEAT_DAILY, NOW) == future


def test_next_occurrence_daily_past_is_strictly_future(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler, "datetime", _UTC)
    when = NOW - 3600.0
    result = next_occurrence(when, REPEAT_DAILY, NOW)
    assert result is not None
    assert result > NOW  # strictly future
    assert result == when + _SECONDS_PER_DAY  # exactly one calendar day later


def test_next_occurrence_daily_boundary_is_strictly_future(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``when == now`` must roll forward — never return a non-future instant."""
    monkeypatch.setattr(scheduler, "datetime", _UTC)
    result = next_occurrence(NOW, REPEAT_DAILY, NOW)
    assert result is not None and result > NOW
    assert result == NOW + _SECONDS_PER_DAY


def test_next_occurrence_daily_multi_day_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler, "datetime", _UTC)
    when = NOW - 5 * _SECONDS_PER_DAY - 3600.0
    result = next_occurrence(when, REPEAT_DAILY, NOW)
    assert result is not None and result > NOW
    assert (result - when) % _SECONDS_PER_DAY == 0  # whole calendar days


def test_next_occurrence_daily_is_dst_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """A daily repeat keeps its local wall-clock time-of-day across a DST jump.

    With fixed 86 400-second stepping the scheduled hour would drift by an hour
    (12:00 → 13:00) after the spring-forward; calendar-day stepping keeps 12:00.
    """
    monkeypatch.setattr(scheduler, "datetime", _SPRING)
    tz = _SpringForwardTz()
    when = _datetime(2026, 3, 27, 12, 0, tzinfo=tz).timestamp()
    now = _datetime(2026, 3, 30, 9, 0, tzinfo=tz).timestamp()

    result = next_occurrence(when, REPEAT_DAILY, now)
    assert result is not None and result > now

    local = _datetime.fromtimestamp(result, tz)
    assert (local.hour, local.minute) == (12, 0)  # wall-clock preserved
    assert local.date() == _datetime(2026, 3, 30).date()


def test_next_occurrence_daily_default_zone_is_strictly_future() -> None:
    """The un-patched (real local) zone also always yields a future instant."""
    result = next_occurrence(NOW - 3600.0, REPEAT_DAILY, NOW)
    assert result is not None and result > NOW


# ── missed-one-shot policy + driver (no QApplication required) ───────────────


class _FakeQueue:
    """Minimal stand-in for ``DownloadQueue`` capturing enqueued jobs."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def add(self, url: str, **kwargs: object) -> None:
        self.calls.append((url, dict(kwargs)))


def _make_scheduler(tmp_path, queue: _FakeQueue, *, now: float):
    return scheduler.Scheduler(
        queue,
        path=tmp_path / "schedules.json",
        clock=lambda: now,
        autostart=False,  # no event loop needed
    )


def test_one_shot_elapsed_while_closed_is_missed(tmp_path) -> None:
    """A one-shot whose time passed while closed is marked missed, never fired."""
    path = tmp_path / "schedules.json"
    item = ScheduleItem(when=NOW - 60, repeat=REPEAT_ONCE, job={"url": "https://example.com/a"})
    path.write_text(json.dumps({"items": [asdict(item)]}), encoding="utf-8")

    queue = _FakeQueue()
    sched = _make_scheduler(tmp_path, queue, now=NOW)

    assert len(sched.items) == 1
    assert sched.items[0].status == STATUS_MISSED
    assert queue.calls == []


def test_daily_elapsed_while_closed_is_advanced_not_missed(tmp_path) -> None:
    """An elapsed daily item is advanced to its next occurrence, not fired/missed."""
    path = tmp_path / "schedules.json"
    item = ScheduleItem(when=NOW - 60, repeat=REPEAT_DAILY, job={"url": "https://example.com/b"})
    path.write_text(json.dumps({"items": [asdict(item)]}), encoding="utf-8")

    queue = _FakeQueue()
    sched = _make_scheduler(tmp_path, queue, now=NOW)

    reloaded = sched.items[0]
    assert reloaded.status == STATUS_PENDING
    assert reloaded.when > NOW
    assert queue.calls == []


def test_reconcile_emits_item_missed(tmp_path) -> None:
    queue = _FakeQueue()
    sched = _make_scheduler(tmp_path, queue, now=NOW)
    past = ScheduleItem(when=NOW - 1, job={"url": "https://example.com/c"})
    sched.add(past)

    seen: list[object] = []
    sched.item_missed.connect(seen.append)
    sched._reconcile_on_start()

    assert seen == [past]
    assert past.status == STATUS_MISSED
    assert queue.calls == []


def test_check_due_fires_one_shot_and_marks_fired(tmp_path) -> None:
    queue = _FakeQueue()
    sched = _make_scheduler(tmp_path, queue, now=NOW)
    item = ScheduleItem(when=NOW - 1, job={"url": "https://example.com/d", "title": "D"})
    sched.add(item)

    fired = sched.check_due(now=NOW)

    assert fired == [item]
    assert item.status == STATUS_FIRED
    assert item.last_fired == NOW
    assert queue.calls == [("https://example.com/d", {"title": "D"})]


def test_check_due_reschedules_daily_and_stays_pending(tmp_path) -> None:
    queue = _FakeQueue()
    sched = _make_scheduler(tmp_path, queue, now=NOW)
    item = ScheduleItem(when=NOW - 1, repeat=REPEAT_DAILY, job={"url": "https://example.com/e"})
    sched.add(item)

    fired = sched.check_due(now=NOW)

    assert item in fired
    assert item.status == STATUS_PENDING
    assert item.when > NOW
    assert queue.calls == [("https://example.com/e", {})]


def test_check_due_missing_url_is_missed_not_queued(tmp_path) -> None:
    queue = _FakeQueue()
    sched = _make_scheduler(tmp_path, queue, now=NOW)
    item = ScheduleItem(when=NOW - 1, job={})  # no url
    sched.add(item)

    seen: list[object] = []
    sched.item_missed.connect(seen.append)
    fired = sched.check_due(now=NOW)

    assert fired == []
    assert item.status == STATUS_MISSED
    assert seen == [item]
    assert queue.calls == []


def test_not_due_items_are_left_alone(tmp_path) -> None:
    queue = _FakeQueue()
    sched = _make_scheduler(tmp_path, queue, now=NOW)
    item = ScheduleItem(when=NOW + 3600, job={"url": "https://example.com/f"})
    sched.add(item)

    assert sched.check_due(now=NOW) == []
    assert item.status == STATUS_PENDING
    assert queue.calls == []


def test_items_persist_across_instances(tmp_path) -> None:
    sched = _make_scheduler(tmp_path, _FakeQueue(), now=NOW)
    sched.add(ScheduleItem(when=NOW + 3600, job={"url": "https://example.com/g"}))

    reloaded = _make_scheduler(tmp_path, _FakeQueue(), now=NOW)
    assert [item.url for item in reloaded.items] == ["https://example.com/g"]
