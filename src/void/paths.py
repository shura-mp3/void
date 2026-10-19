"""XDG-aware filesystem locations used by every VOID component."""

import os
from pathlib import Path

APP = "void-desktop"


def _xdg(env: str, fallback: str) -> Path:
    return Path(os.environ.get(env) or fallback).expanduser()


PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
SRC_DIR = PROJECT_DIR / "src"
CONFIG_SRC = PROJECT_DIR / "config"
TOKENS_FILE = CONFIG_SRC / "tokens.toml"
HOME = Path.home()
XDG_CONFIG = _xdg("XDG_CONFIG_HOME", "~/.config")
XDG_DATA = _xdg("XDG_DATA_HOME", "~/.local/share")
XDG_STATE = _xdg("XDG_STATE_HOME", "~/.local/state")
XDG_CACHE = _xdg("XDG_CACHE_HOME", "~/.cache")

CONFIG_DIR = XDG_CONFIG / APP
CACHE_DIR = XDG_CACHE / APP
STATE_DIR = XDG_STATE / APP
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/{APP}-{os.getuid()}") / APP

CONFIG_FILE = CONFIG_DIR / "config.toml"
DEFAULT_CONFIG_FILE = CONFIG_SRC / "void.toml"
UI_STATE_FILE = STATE_DIR / "ui.json"
OFFSETS_FILE = STATE_DIR / "offsets.json"
MONITORS_FILE = STATE_DIR / "monitors.json"
WALLPAPER_STATE = STATE_DIR / "wallpaper.json"
SOCKET_PATH = RUNTIME_DIR / "core.sock"
LYRICS_CACHE = CACHE_DIR / "lyrics"
ART_CACHE = CACHE_DIR / "art"
USER_LYRICS_DIR = CONFIG_DIR / "lyrics"
GENERATED = STATE_DIR / "generated"        # rendered copies of templates with absolute paths

# Crimson Desktop's lyric cache: read-only fallback so tracks it already fetched are not fetched again.
CRIMSON_LYRICS_CACHE = XDG_CACHE / "crimson-desktop" / "lyrics"
CRIMSON_USER_LYRICS = XDG_CONFIG / "crimson-desktop" / "lyrics"


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, CACHE_DIR, STATE_DIR, LYRICS_CACHE, ART_CACHE, USER_LYRICS_DIR, GENERATED):
        d.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
