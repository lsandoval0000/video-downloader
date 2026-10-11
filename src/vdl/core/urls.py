"""URL extraction and validation for batch / multi-URL input (extra #4).

Pure, Qt-free, and I/O-free so it is trivially unit-testable. The extraction
regex is deliberately permissive (``https?://\\S+``); trailing punctuation and
machine-pasted noise are cleaned up afterwards, and comment (``#``) or blank
lines are skipped entirely so a user can paste a annotated list of links.
"""

from __future__ import annotations

import re

# ``https?://`` followed by one-or-more non-space characters. This intentionally
# over-matches (it may grab trailing punctuation or a closing bracket) — those
# are trimmed by :func:`_clean` — because a tighter regex misses legitimate URLs
# that end in ``)`` (Wikipedia) or ``!`` etc.
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# Sentence punctuation that is virtually never part of a URL.
_TRAILING_PUNCT = ".,;:!?\u2026"  # includes the ellipsis character

# Closing delimiters that only belong to a URL when their opener also appears.
_CLOSERS = {")": "(", "]": "[", "}": "{", ">": "<", '"': '"', "'": "'"}

# Conservative host validation: scheme + a host that contains a dot.
_HOST_RE = re.compile(r"^https?://[^/\s?#]+", re.IGNORECASE)


def _clean(url: str) -> str:
    """Trim trailing punctuation / unbalanced closing delimiters from a match."""
    url = url.strip()
    while url and url[-1] in _TRAILING_PUNCT:
        url = url[:-1]
    while url and url[-1] in _CLOSERS:
        closer = url[-1]
        opener = _CLOSERS[closer]
        # Keep the closer only if there is a matching opener inside the URL.
        if url.count(opener) >= url.count(closer):
            break
        url = url[:-1]
    return url


def extract_urls(text: str | None) -> list[str]:
    """Extract http(s) URLs from free-form text.

    * One URL per whitespace-delimited token (text inside a line is fine).
    * Blank lines and comment lines (starting with ``#``) are ignored.
    * Trailing sentence punctuation is stripped.
    * Duplicates are removed, preserving first-seen order.
    """
    if not text:
        return []

    seen: set[str] = set()
    result: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for match in _URL_RE.findall(line):
            url = _clean(match)
            if not url or url in seen:
                continue
            seen.add(url)
            result.append(url)
    return result


def is_probably_valid(url: str | None) -> bool:
    """Best-effort sanity check for a single URL (no network).

    Requires an ``http``/``https`` scheme and a host containing a dot (so
    ``https://localhost`` and bare words are rejected). Deliberately lenient:
    reachability is proven only by yt-dlp at download time.
    """
    if not isinstance(url, str):
        return False
    candidate = url.strip()
    if not candidate or any(ch.isspace() for ch in candidate):
        return False
    match = _HOST_RE.match(candidate)
    if match is None:
        return False
    # Strip the scheme, then isolate the authority (userinfo@host:port).
    authority = candidate.split("://", 1)[1]
    authority = authority.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    hostname = authority.rsplit("@", 1)[-1].split(":", 1)[0]
    if "." not in hostname or hostname.startswith(".") or hostname.endswith("."):
        return False
    return bool(hostname)
