"""Configuration: built-in defaults, deep-merged with ~/.config/void-desktop/config.toml.

The TOML file is only ever read. Values changed at runtime (lyric offsets, the current
performance profile) live in small JSON files under ~/.local/state/void-desktop.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tomllib
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "spotify": {
        # MPRIS player names in priority order. "*" = fall back to any MPRIS player.
        "players": ["spotify"],
        # Seconds between Position re-reads while playing (drift / seek detection).
        "resync_interval": 1.5,
    },
    "lyrics": {
        # Global latency compensation in ms. Positive = lyrics appear EARLIER.
        "latency_ms": 0,
        "local_dirs": ["~/Music/Lyrics", "~/Music/lyrics", "~/.lyrics"],
        "lrclib": True,
        "lrclib_url": "https://lrclib.net",
        "duration_tolerance": 3,
        "negative_cache_hours": 24,
        # Reuse lyrics Crimson Desktop already downloaded (read-only) before asking LRCLIB.
        "use_crimson_cache": True,
    },
    "audio": {
        "enabled": True,
        # "system" = everything you hear (default sink monitor); "spotify" = experimental, Spotify's stream only.
        "source": "system",
        "bars": 64,
        "cava_binary": "cava",
    },
    "dashboard": {
        # "auto" = the right-most monitor by KScreen position, or a connector name such as "DP-2".
        "monitor": "auto",
        # minimal | balanced | showcase
        "performance": "balanced",
        # When Feral GameMode reports a running game: "minimal" (drop to the minimal profile) or "ignore".
        "gamemode_action": "minimal",
        # Drop to minimal while the 1-minute load average exceeds (cores x this).
        "load_threshold": 0.9,
        # Pane programs. "auto" uses the external tool when installed, else VOID's built-in one.
        "system_monitor": "auto",   # auto | btop | builtin
        "clock": "builtin",          # builtin | tty-clock
        "rain": "builtin",           # builtin | cmatrix
        "terminal": "auto",          # auto | konsole | alacritty
    },
    "konsole": {
        # Make "VOID" Konsole's default profile while VOID is active (restored on deactivate).
        "set_default_profile": True,
        # Show the Geass fastfetch once when a VOID Konsole session opens.
        "startup_fetch": True,
    },
    "kde": {
        "color_scheme": True,
        "plasma_style": True,
        "window_decoration": True,
        "wallpaper": True,
        "lockscreen": True,
        # "auto" = a monochrome cursor theme that is already installed (Breeze), or "" to leave it.
        "cursor": "auto",
        "dashboard_window_rule": True,
    },
    "wallpaper": {
        "source_dir": "~/Downloads/home/jan/Downloads/pack 1",
        # Force a specific file instead of the automatic ranking.
        "pick": "",
    },
    "spicetify": {
        "enabled": True,
        # Loopback WebSocket for the VOID Spicetify theme (Crimson uses 47811; VOID never shares it).
        "bridge": True,
        "bridge_port": 47812,
        "allowed_origins": ["https://xpui.app.spotify.com"],
        # Album art stays in colour (it is content, not chrome). True = grayscale artwork in Spotify.
        "grayscale_art": False,
        # Spicetify's bundled Full App Display extension (LGPL-2.1, ships with Spicetify).
        "full_app_display": True,
        # VOID sidebar page in Spotify: synced lyrics + spectrum from void-core.
        "custom_app": True,
    },
    "crimson": {
        "project_dir": "~/Projects/crimson-desktop",
        # Stop Crimson's services while VOID is active (one MPRIS/lyrics watcher, one appearance manager).
        "pause_services": True,
    },
}

PERFORMANCE: dict[str, dict[str, Any]] = {
    "minimal": {"rain_fps": 0, "music_fps": 4, "spectrum": False, "cava_fps": 0, "btop_ms": 3000,
                "fetch_refresh": 0, "clock_seconds": False},
    "balanced": {"rain_fps": 10, "music_fps": 10, "spectrum": True, "cava_fps": 30, "btop_ms": 2000,
                 "fetch_refresh": 600, "clock_seconds": True},
    "showcase": {"rain_fps": 20, "music_fps": 20, "spectrum": True, "cava_fps": 45, "btop_ms": 1000,
                 "fetch_refresh": 300, "clock_seconds": True},
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: Path | None = None) -> dict[str, Any]:
    path = path or Path(os.environ.get("VOID_CONFIG") or paths.CONFIG_FILE)
    cfg = copy.deepcopy(DEFAULTS)
    if path.exists():
        try:
            with open(path, "rb") as f:
                cfg = _merge(cfg, tomllib.load(f))
        except (OSError, tomllib.TOMLDecodeError) as e:
            log.error("config %s unreadable (%s) - using defaults", path, e)
    return cfg


def profile(name: str | None) -> dict[str, Any]:
    return PERFORMANCE.get(name or "balanced", PERFORMANCE["balanced"])


class JsonState:
    """A tiny JSON-backed dict, written atomically."""

    def __init__(self, path: Path, default: dict | None = None):
        self.path = path
        self.data: dict = dict(default or {})
        try:
            self.data.update(json.loads(path.read_text()))
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True))
        tmp.replace(self.path)


def current_profile(cfg: dict | None = None) -> str:
    """The performance profile chosen at runtime (`void profile …`), else the configured default."""
    cfg = cfg or load()
    p = JsonState(paths.UI_STATE_FILE).data.get("performance") or cfg["dashboard"].get("performance", "balanced")
    return p if p in PERFORMANCE else "balanced"
