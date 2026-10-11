"""Human-readable formatting helpers for the UI (leaf 2.8 support).

Pure, Qt-free and dependency-free so they are trivially unit-testable and can be
reused by any view. Byte values are rendered with SI units (``KB``/``MB``/``GB``,
powers of 1000) to match the "MB/s" vocabulary the acceptance criteria use for
download speed.
"""

from __future__ import annotations

from typing import Any

#: SI byte units (powers of 1000), matching the "MB/s" speed convention.
_UNITS: tuple[str, ...] = ("B", "KB", "MB", "GB", "TB", "PB")

_STEP = 1000.0


def _as_float(value: Any) -> float | None:
    """Best-effort numeric coercion; ``None`` for non-numeric/None input."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def human_bytes(num: float | int | None) -> str:
    """Format a byte count with SI units (``"12.3 MB"``).

    ``None``/negative/non-numeric input renders as an em dash so a cell never
    shows ``"None"``.
    """
    value = _as_float(num)
    if value is None or value < 0:
        return "\u2014"
    if value < _STEP:
        return f"{int(value)} B"
    index = 0
    while value >= _STEP and index < len(_UNITS) - 1:
        value /= _STEP
        index += 1
    return f"{value:.1f} {_UNITS[index]}"


def human_speed(bytes_per_sec: float | int | None) -> str:
    """Format a transfer rate (``"2.4 MB/s"``); ``"—"`` when unknown/zero."""
    value = _as_float(bytes_per_sec)
    if value is None or value <= 0:
        return "\u2014"
    return f"{human_bytes(value)}/s"


def human_eta(seconds: float | int | None) -> str:
    """Format a duration as ``mm:ss`` (or ``h:mm:ss`` past an hour).

    Negative/None input renders as ``"—"``; ``0`` renders as ``"00:00"``.
    """
    value = _as_float(seconds)
    if value is None or value < 0:
        return "\u2014"
    total = int(value)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def human_percent(value: float | int | None) -> str:
    """Format a 0-100 percentage as ``"42.5%"``; ``"—"`` when unknown."""
    number = _as_float(value)
    if number is None:
        return "\u2014"
    return f"{number:.1f}%"
