"""Unit tests for :mod:`vdl.core.cookies` (extra #11) — stdlib only, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from vdl.core import cookies


def test_cookies_option_minimal_tuple() -> None:
    assert cookies.cookies_option("chrome") == ("chrome",)


def test_cookies_option_normalizes_case_and_whitespace() -> None:
    assert cookies.cookies_option("  Chrome ") == ("chrome",)


def test_cookies_option_none_and_empty() -> None:
    assert cookies.cookies_option(None) is None
    assert cookies.cookies_option("") is None


def test_cookies_option_with_profile() -> None:
    assert cookies.cookies_option("firefox", profile="Work") == ("firefox", "Work")


def test_cookies_option_with_keyring_keeps_placeholder() -> None:
    assert cookies.cookies_option("chrome", keyring="gnomekeyring") == (
        "chrome",
        None,
        "gnomekeyring",
    )


def test_cookies_option_full_spec() -> None:
    assert cookies.cookies_option("firefox", profile="P", keyring="K", container="C") == (
        "firefox",
        "P",
        "K",
        "C",
    )


def test_cookies_option_rejects_unknown_browser() -> None:
    with pytest.raises(ValueError):
        cookies.cookies_option("netscape")


def test_cookie_file_option_expands_and_none() -> None:
    assert cookies.cookie_file_option(None) is None
    assert cookies.cookie_file_option("") is None
    result = cookies.cookie_file_option("~/cookies.txt")
    assert result is not None and "~" not in result
    assert result.endswith("cookies.txt")


def test_cookie_file_option_accepts_pathlike() -> None:
    result = cookies.cookie_file_option(Path("C:/c/cookies.txt"))
    assert result is not None and "cookies.txt" in result


def test_is_supported_browser() -> None:
    assert cookies.is_supported_browser("chrome") is True
    assert cookies.is_supported_browser("Chrome") is True
    assert cookies.is_supported_browser("netscape") is False
    assert cookies.is_supported_browser(None) is False


def test_browser_choices_contains_common_browsers() -> None:
    choices = cookies.browser_choices()
    for name in ("chrome", "edge", "firefox", "brave", "opera", "vivaldi"):
        assert name in choices


def test_is_cookie_error_detects_ytdlp_message() -> None:
    assert cookies.is_cookie_error("ERROR: failed to load cookies") is True
    assert cookies.is_cookie_error("unable to open database file") is True
    assert cookies.is_cookie_error("HTTP Error 404: Not Found") is False


def test_is_cookie_error_inspects_cause() -> None:
    exc = RuntimeError("failed to load cookies")
    exc.__cause__ = PermissionError("could not copy chrome cookie database")
    assert cookies.is_cookie_error(exc) is True


def test_cookie_error_hint_mentions_close_for_chromium() -> None:
    hint = cookies.cookie_error_hint("chrome")
    assert "Close" in hint or "close" in hint
    assert "chrome" in hint.lower()


def test_cookie_error_hint_generic_for_unknown() -> None:
    hint = cookies.cookie_error_hint(None)
    assert "cookies.txt" in hint
