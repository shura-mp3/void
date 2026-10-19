"""Minimal full-screen terminal toolkit shared by VOID's panes (no curses, no third-party deps).

* colours come from config/tokens.toml (truecolor SGR)
* frames are diffed line by line, so an unchanged screen costs nothing to "redraw"
* output is wrapped in synchronized-update escapes (ignored by terminals that lack them)
"""

from __future__ import annotations

import os
import select
import shutil
import signal
import sys
import termios
import tty
import unicodedata

from .. import tokens

ESC = "\x1b["
RESET = ESC + "0m"


def fg(name_or_hex: str) -> str:
    return f"{ESC}{tokens.sgr(tokens.resolve(name_or_hex))}m"


def bg(name_or_hex: str) -> str:
    return f"{ESC}{tokens.sgr(tokens.resolve(name_or_hex), bg=True)}m"


BOLD = ESC + "1m"


def width(s: str) -> int:
    """Display width (cells) of plain text, East Asian wide characters count 2."""
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def clip(s: str, n: int) -> str:
    """Cut plain text to at most n cells, with an ellipsis when shortened."""
    if width(s) <= n:
        return s
    out, w = "", 0
    for ch in s:
        cw = width(ch)
        if w + cw > n - 1:
            break
        out += ch
        w += cw
    return out + "…"


def center(s: str, n: int) -> str:
    pad = max(0, n - width(s))
    return " " * (pad // 2) + s + " " * (pad - pad // 2)


def wrap(text: str, n: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        cand = f"{cur} {wd}".strip()
        if width(cand) <= n or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return [clip(l, n) for l in lines] or [""]


class Screen:
    """Alternate screen with diffed redraws. Use as a context manager."""

    def __init__(self, keys: bool = False):
        self.keys = keys
        self.prev: list[str] = []
        self.resized = True
        self._fd = sys.stdin.fileno() if sys.stdin.isatty() else None
        self._saved = None
        self.cols, self.rows = shutil.get_terminal_size((100, 30))

    def __enter__(self) -> "Screen":
        if self.keys and self._fd is not None:
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        signal.signal(signal.SIGWINCH, self._on_winch)
        sys.stdout.write(f"\x1b[?1049h\x1b[?25l{bg('background')}{ESC}2J")
        sys.stdout.flush()
        return self

    def __exit__(self, *exc) -> None:
        if self._saved is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
        sys.stdout.write(f"{RESET}\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()

    def _on_winch(self, *_):
        self.resized = True

    def size(self) -> tuple[int, int]:
        if self.resized:
            self.cols, self.rows = shutil.get_terminal_size((100, 30))
        return self.cols, self.rows

    def draw(self, lines: list[str]) -> bool:
        """lines: already-styled rows (each must fit the width). Returns True if anything was written."""
        cols, rows = self.size()
        lines = (lines + [""] * rows)[:rows]
        full = self.resized or len(self.prev) != rows
        self.resized = False
        out = []
        base = bg("background") + fg("text")
        for i, line in enumerate(lines):
            if full or self.prev[i] != line:
                out.append(f"{ESC}{i + 1};1H{base}{ESC}2K{line}{RESET}")
        self.prev = lines
        if not out:
            return False
        sys.stdout.write("\x1b[?2026h" + "".join(out) + "\x1b[?2026l")
        sys.stdout.flush()
        return True

    def read_key(self, timeout: float) -> str | None:
        """Wait up to timeout seconds for a key (also returns early on resize). None = no key."""
        if self._fd is None or not self.keys:
            if timeout > 0:
                try:
                    select.select([], [], [], timeout)
                except InterruptedError:
                    pass
            return None
        try:
            r, _, _ = select.select([self._fd], [], [], max(0.0, timeout))
        except InterruptedError:
            return None
        if not r:
            return None
        data = os.read(self._fd, 32).decode(errors="ignore")
        return {"\x1b[C": "right", "\x1b[D": "left", "\x1b[A": "up", "\x1b[B": "down"}.get(data, data[:1])


def run_safely(fn) -> int:
    """Pane entry wrapper: Ctrl+C exits quietly; SIGTERM/SIGHUP restore the terminal."""
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    signal.signal(signal.SIGHUP, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        return fn() or 0
    except KeyboardInterrupt:
        return 0
