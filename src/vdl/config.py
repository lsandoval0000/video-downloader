"""Application settings and download presets (JSON-backed).

Writes are atomic (temp file + :func:`os.replace`) and reads recover gracefully
from a missing or corrupt file by falling back to defaults — the app must never
fail to start because of a bad config.

Storage lives in :func:`vdl.paths.user_data_dir`; never beside the exe unless
portable mode is active (see the plan's portable-vs-installed gotcha).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from vdl.paths import user_data_dir

logger = logging.getLogger("vdl.config")

_SETTINGS_FILE = "config.json"


@dataclass
class Settings:
    """User-configurable download defaults (extra #15 and app-wide options)."""

    download_dir: str = ""
    default_format_preset: str = "best"  # best|1080p|720p|audio|smallest
    audio_only: bool = False
    audio_codec: str = "mp3"  # mp3|m4a
    video_container: str | None = None  # None|mp4|mkv|webm
    video_remux: bool = False  # remux (stream-copy) instead of re-encode (extra #12)
    embed_subs: bool = False
    write_subs: bool = True
    sub_langs: list[str] = field(default_factory=lambda: ["en"])
    embed_thumbnail: bool = True
    convert_thumbnail: bool = False  # pre-convert thumbnails to jpg before embedding
    embed_metadata: bool = True
    sponsorblock_enabled: bool = False
    sponsorblock_categories: list[str] = field(default_factory=lambda: ["sponsor", "selfpromo"])
    use_cookies: bool = False
    cookie_browser: str | None = None  # chrome|edge|firefox|brave|opera|vivaldi
    cookie_file: str | None = None  # explicit cookies.txt path (extra #11)
    archive_enabled: bool = True
    playlist_items: str | None = None  # "1-10"
    notify_on_complete: bool = True
    clipboard_watch: bool = True
    max_concurrent: int = 2
    proxy: str | None = None
    js_runtime_enabled: bool = True  # deno for YouTube


@dataclass
class Preset:
    """A named snapshot of a subset of :class:`Settings` values."""

    name: str
    values: dict


_SETTING_FIELDS = {f.name for f in fields(Settings)}


def _coerce_settings(data: Any) -> Settings:
    """Build a :class:`Settings` from untrusted JSON, ignoring unknown keys."""
    if not isinstance(data, dict):
        return Settings()
    defaults = Settings()
    kwargs: dict[str, Any] = {key: value for key, value in data.items() if key in _SETTING_FIELDS}

    # Sanity-guard the raw (Any-typed) values before constructing the dataclass,
    # so a hand-edited file cannot inject the wrong types.
    max_concurrent = kwargs.get("max_concurrent")
    if (
        not isinstance(max_concurrent, int)
        or isinstance(max_concurrent, bool)
        or max_concurrent < 1
    ):
        kwargs["max_concurrent"] = defaults.max_concurrent
    if not isinstance(kwargs.get("sub_langs"), list):
        kwargs["sub_langs"] = defaults.sub_langs
    if not isinstance(kwargs.get("sponsorblock_categories"), list):
        kwargs["sponsorblock_categories"] = defaults.sponsorblock_categories

    try:
        return Settings(**kwargs)
    except TypeError:
        logger.warning("config: incompatible settings payload; using defaults")
        return Settings()


def _coerce_presets(data: Any) -> dict[str, Preset]:
    """Build the preset mapping from untrusted JSON, skipping malformed rows."""
    presets: dict[str, Preset] = {}
    if not isinstance(data, dict):
        return presets
    for name, values in data.items():
        if isinstance(name, str) and isinstance(values, dict):
            presets[name] = Preset(name=name, values=values)
    return presets


class ConfigStore:
    """JSON-backed store for :class:`Settings` and named :class:`Preset`\\ s."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path is not None else user_data_dir() / _SETTINGS_FILE
        self._settings = Settings()
        self._presets: dict[str, Preset] = {}

    # ── lifecycle ────────────────────────────────────────────────────────────
    def load(self) -> ConfigStore:
        """Load from disk, falling back to defaults on any read/parse error."""
        raw: dict[str, Any] = {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.info("config: %s not found; using defaults", self.path)
        except (OSError, ValueError) as exc:
            logger.warning("config: cannot read %s (%s); using defaults", self.path, exc)
        else:
            if isinstance(loaded, dict):
                raw = loaded
            else:
                logger.warning("config: %s is not a JSON object; using defaults", self.path)

        self._settings = _coerce_settings(raw.get("settings"))
        self._presets = _coerce_presets(raw.get("presets"))
        return self

    def save(self) -> None:
        """Persist settings + presets atomically."""
        payload = {
            "settings": asdict(self._settings),
            "presets": {name: preset.values for name, preset in self._presets.items()},
        }
        self._atomic_write(payload)

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

    # ── settings access ──────────────────────────────────────────────────────
    @property
    def settings(self) -> Settings:
        return self._settings

    def get(self, key: str, default: Any = None) -> Any:
        """Return a setting value, or ``default`` if the key is not a setting."""
        if key in _SETTING_FIELDS:
            return getattr(self._settings, key)
        return default

    def set(self, key: str, value: Any) -> None:
        """Set a setting value. Raises ``KeyError`` for an unknown key."""
        if key not in _SETTING_FIELDS:
            raise KeyError(f"unknown setting: {key!r}")
        setattr(self._settings, key, value)

    # ── presets ──────────────────────────────────────────────────────────────
    def list_presets(self) -> list[Preset]:
        """Return presets ordered by name."""
        return [self._presets[name] for name in sorted(self._presets)]

    def get_preset(self, name: str) -> Preset | None:
        return self._presets.get(name)

    def add_preset(self, preset: Preset) -> None:
        """Add or replace a preset by name, then persist."""
        self._presets[preset.name] = preset
        self.save()

    def delete_preset(self, name: str) -> bool:
        """Delete a preset by name. Returns ``True`` if it existed."""
        if name not in self._presets:
            return False
        del self._presets[name]
        self.save()
        return True
