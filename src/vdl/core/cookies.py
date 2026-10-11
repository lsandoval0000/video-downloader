"""Browser cookie import + ``cookiefile`` support (extra #11).

yt-dlp accepts two independent cookie sources:

* ``cookiesfrombrowser`` — a tuple ``(browser, profile?, keyring?, container?)``
  that makes yt-dlp read the browser's own cookie database (this is the
  "logged-in browser" path);
* ``cookiefile`` — a Netscape ``cookies.txt`` file exported by a browser
  extension (the fallback when the live DB cannot be read).

This module is **pure and import-light** (stdlib only): it turns user-facing
choices into the exact tuples/paths yt-dlp wants and produces *actionable* error
text. No Qt, no network, no filesystem writes — unit-testable headless.

Windows gotcha this module exists to surface: **Chromium browsers (Chrome,
Edge, Brave, Opera, Vivaldi) lock their cookie database while running**, so
yt-dlp cannot read it and fails with an opaque error. :func:`cookie_error_hint`
turns that into a message a user can act on (close the browser, or use a
``cookies.txt`` file).
"""

from __future__ import annotations

from pathlib import Path

#: Browsers yt-dlp can read cookies from (mirrors ``yt_dlp.cookies.SUPPORTED_BROWSERS``).
#: Kept as a local constant so importing this module never pulls in ``yt_dlp``.
SUPPORTED_BROWSERS: tuple[str, ...] = (
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "brave",
    "opera",
    "vivaldi",
    "whale",
    "safari",
)

#: Browsers that lock their cookie DB while running on Windows (see module doc).
CHROMIUM_BROWSERS: frozenset[str] = frozenset(
    {"chrome", "chromium", "edge", "brave", "opera", "vivaldi", "whale"}
)

#: Substrings that identify a cookie-load failure in yt-dlp's error text.
_COOKIE_ERROR_MARKERS: tuple[str, ...] = (
    "failed to load cookies",
    "could not copy",
    "database is locked",
    "unable to open database",
    "permissionerror",
    "operation not permitted",
    "cookie",
)

_ACTIONABLE_HINT = (
    "Close the browser completely (check Task Manager for background processes) "
    "and try again — Windows locks its cookie database while it is running. "
    "Alternatively, export cookies to a 'cookies.txt' file and select it as the "
    "cookie file."
)


def is_supported_browser(browser: str | None) -> bool:
    """Return ``True`` if ``browser`` is one yt-dlp can import cookies from."""
    if not browser:
        return False
    return browser.strip().lower() in SUPPORTED_BROWSERS


def cookies_option(
    browser: str | None,
    *,
    profile: str | None = None,
    keyring: str | None = None,
    container: str | None = None,
) -> tuple[str | None, ...] | None:
    """Return yt-dlp's ``cookiesfrombrowser`` tuple, or ``None`` when unset.

    The tuple is the *minimal* valid form: trailing ``None``\\ s are trimmed so a
    plain request yields ``('chrome',)`` (yt-dlp's
    ``_parse_browser_specification`` accepts 1-4 positional elements):

    >>> cookies_option('chrome')
    ('chrome',)
    >>> cookies_option('chrome', profile='Default')
    ('chrome', 'Default')
    >>> cookies_option('chrome', keyring='gnomekeyring')
    ('chrome', None, 'gnomekeyring')
    >>> cookies_option(None) is None
    True

    Raises :class:`ValueError` for an unknown browser name (fail fast, before the
    download starts, rather than deep inside yt-dlp).
    """
    if not browser:
        return None
    name = browser.strip().lower()
    if name not in SUPPORTED_BROWSERS:
        raise ValueError(f"unsupported browser: {browser!r} (expected one of {SUPPORTED_BROWSERS})")

    spec: list[str | None] = [name, profile, keyring, container]
    while len(spec) > 1 and spec[-1] is None:
        spec.pop()
    return tuple(spec)


def cookie_file_option(path: str | Path | None) -> str | None:
    """Normalize a ``cookies.txt`` path for yt-dlp's ``cookiefile`` option.

    Expands ``~`` and returns an absolute string, or ``None`` when unset. The
    file is **not** required to exist here (yt-dlp validates it at load time), so
    callers can store a path the user has yet to create.
    """
    if not path:
        return None
    return str(Path(path).expanduser())


def browser_choices() -> list[str]:
    """The browser names to offer in a UI dropdown (ordered for display)."""
    return list(SUPPORTED_BROWSERS)


def is_cookie_error(error: BaseException | str) -> bool:
    """Heuristically detect a cookie-load failure from yt-dlp's error text.

    yt-dlp wraps the underlying OS error in a generic ``CookieLoadError`` whose
    message is just ``"failed to load cookies"``, so the cause text is inspected
    too.
    """
    text = str(error).lower()
    if isinstance(error, BaseException) and error.__cause__ is not None:
        text += " " + str(error.__cause__).lower()
    return any(marker in text for marker in _COOKIE_ERROR_MARKERS)


def cookie_error_hint(browser: str | None = None) -> str:
    """Return actionable guidance for a failed cookie import.

    Chromium browsers (the common case on Windows) get the "close the browser"
    hint; other browsers point at the ``cookies.txt`` fallback.
    """
    if browser and browser.strip().lower() in CHROMIUM_BROWSERS:
        return f"Could not read {browser} cookies. {_ACTIONABLE_HINT}"
    return (
        "Could not read browser cookies. Make sure the browser is closed, or "
        "export cookies to a 'cookies.txt' file and select it as the cookie file."
    )
