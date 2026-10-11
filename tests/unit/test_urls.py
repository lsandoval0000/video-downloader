"""Unit tests for :mod:`vdl.core.urls` — no network, no PySide6."""

from __future__ import annotations

from vdl.core.urls import extract_urls, is_probably_valid


def test_messy_multiline_dedupes_and_cleans() -> None:
    text = """
    # a comment line that must be ignored
    https://a.example.com/v/1

    not a url at all
    https://b.example.com/v/2?x=1&y=2
    https://a.example.com/v/1          # duplicate -> dropped
    (https://c.example.com/v/3)
    https://d.example.com/v/4.
    """
    assert extract_urls(text) == [
        "https://a.example.com/v/1",
        "https://b.example.com/v/2?x=1&y=2",
        "https://c.example.com/v/3",
        "https://d.example.com/v/4",
    ]


def test_blank_and_whitespace_input() -> None:
    assert extract_urls("   \n\n\t\n") == []
    assert extract_urls("") == []
    assert extract_urls(None) == []


def test_comment_lines_skipped_but_inline_urls_kept() -> None:
    text = "# https://ignored.example.com/x\nhttps://kept.example.com/y"
    assert extract_urls(text) == ["https://kept.example.com/y"]


def test_multiple_urls_on_one_line() -> None:
    text = "see https://x.example.com/1 and also https://y.example.com/2#frag"
    assert extract_urls(text) == ["https://x.example.com/1", "https://y.example.com/2#frag"]


def test_balanced_parentheses_are_preserved() -> None:
    url = "https://en.wikipedia.org/wiki/Foo_(bar)"
    assert extract_urls(url) == [url]


def test_dedupe_preserves_first_seen_order() -> None:
    text = "https://b.com https://a.com https://b.com https://c.com https://a.com"
    assert extract_urls(text) == ["https://b.com", "https://a.com", "https://c.com"]


def test_is_probably_valid_accepts_real_urls() -> None:
    assert is_probably_valid("https://www.youtube.com/watch?v=abc123")
    assert is_probably_valid("http://example.com")
    assert is_probably_valid("https://user:pass@example.com:8443/path?q=1")
    assert is_probably_valid("https://sub.domain.co.uk/x")


def test_is_probably_valid_rejects_junk() -> None:
    assert not is_probably_valid("ftp://example.com")
    assert not is_probably_valid("https://localhost")
    assert not is_probably_valid("just some text")
    assert not is_probably_valid("")
    assert not is_probably_valid("https://exa mple.com")
    assert not is_probably_valid("https://.com")
    assert not is_probably_valid(None)
