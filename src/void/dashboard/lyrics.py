"""`void lyrics` — full-page synchronized Spotify lyrics, made for Kitty (works in any truecolor terminal).

Ported from Crimson Desktop's crimson-lyrics (crimson/tui.py) and adapted to VOID: monochrome
tokens, void-core as the only backend (one MPRIS watcher, one lyrics fetch for the dashboard, this
view and Spotify), Kitty's text-sizing protocol for the big line on Kitty ≥ 0.40 and VOID's block
font everywhere else, and a short fade when the current line changes.

Keys:  space play/pause   n/p next/prev   ←/→ seek 5 s   +/- offset ±100 ms   0 reset offset
       r re-fetch lyrics   b big line   c compact   j/k scroll unsynced lyrics   ? help   q quit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import termios
import textwrap
import time
import tty

from .. import client, config, lrc, paths
from . import bigfont
from .term import BOLD, RESET as RST, bg, clip, fg, width

ESC = "\x1b"
# Crimson's six shades mapped onto VOID's tokens
HI, NEAR, MID, DIM, FAINT, PANEL = "highlight", "secondary_text", "muted", "#4A4A4A", "border", "elevated"


def center(s: str, w: int, visible: int | None = None) -> str:
    v = width(s) if visible is None else visible
    return " " * max(0, (w - v) // 2) + s


def fmt_time(ms: float) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"


def kitty_text_sizing() -> bool:
    """Kitty ≥ 0.40 understands OSC 66 (text sizing): the big line is real font glyphs at 2x."""
    if os.environ.get("TERM") != "xterm-kitty" and not os.environ.get("KITTY_WINDOW_ID"):
        return False
    try:
        out = subprocess.run(["kitty", "--version"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    m = re.search(r"(\d+)\.(\d+)", out)
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= (0, 40)


class LyricsTUI:
    def __init__(self, args):
        self.args = args
        self.player: dict = {}
        self.lyrics: dict = {"status": "none", "lines": []}
        self.ui: dict = {}
        self.toast: tuple[str, float] | None = None
        self.osc66 = kitty_text_sizing()
        self.big = args.big if args.big is not None else self.osc66
        self.compact = args.compact
        self.help = False
        self.scroll = 0
        self.prev_frame: list[str] = []
        self.dirty = True
        self.writer: asyncio.StreamWriter | None = None
        self.local_core = None
        self.connected = False
        self.line_key = None
        self.line_since = 0.0
        self.cols, self.rows = shutil.get_terminal_size((80, 24))

    # ------------------------------------------------------------ connection (void-core only)
    async def connect(self) -> None:
        for attempt in range(2):
            try:
                reader, self.writer = await asyncio.open_unix_connection(str(paths.SOCKET_PATH))
                self.connected = True
                self._send({"cmd": "sub", "topics": []})
                asyncio.create_task(self._read(reader))
                return
            except (FileNotFoundError, ConnectionRefusedError):
                if attempt == 0:
                    await asyncio.get_running_loop().run_in_executor(None, client.start_core)
                    for _ in range(30):
                        await asyncio.sleep(0.15)
                        if paths.SOCKET_PATH.exists():
                            break
        if self.args.embedded:
            # explicit opt-in only: an in-process core next to a running crimson-core would mean two watchers
            from ..core import Core
            self.local_core = Core(config.load())
            await self.local_core.start(serve=False)
            self._local_client = self.local_core.add_local_client(self._on_msg)
            self.connected = True
            return
        asyncio.create_task(self._reconnect())

    async def _read(self, reader) -> None:
        try:
            while line := await reader.readline():
                try:
                    self._on_msg(json.loads(line))
                except ValueError:
                    pass
        finally:
            self.connected = False
            self.player = {}
            self.dirty = True
            await asyncio.sleep(2)
            asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        while not self.connected:
            try:
                reader, self.writer = await asyncio.open_unix_connection(str(paths.SOCKET_PATH))
                self.connected = True
                self.dirty = True
                self._send({"cmd": "sub", "topics": []})
                asyncio.create_task(self._read(reader))
            except (FileNotFoundError, ConnectionRefusedError):
                await asyncio.sleep(2)

    def _send(self, msg: dict) -> None:
        if self.local_core:
            asyncio.ensure_future(self.local_core.command(self._local_client, msg))
        elif self.writer:
            self.writer.write((json.dumps(msg) + "\n").encode())

    def _on_msg(self, m: dict) -> None:
        t = m.get("t")
        if t == "player":
            if m.get("track", {}).get("id") != self.player.get("track", {}).get("id"):
                self.scroll = 0
            self.player = m
        elif t == "lyrics":
            self.lyrics = m
        elif t == "ui":
            self.ui = m
        elif t == "toast":
            self.toast = (m["text"], time.monotonic() + 2.5)
        self.dirty = True

    # ------------------------------------------------------------ timing
    def position(self) -> float:
        p = self.player
        if not p:
            return 0.0
        pos = p.get("pos_ms", 0.0)
        if p.get("playing"):
            pos += (time.monotonic() - p.get("mono", time.monotonic())) * 1000
        length = p.get("track", {}).get("length_ms") or 0
        return min(pos, length) if length else pos

    # ------------------------------------------------------------ rendering
    def frame(self) -> list[str]:
        W, H = self.cols, self.rows
        rows: list[str] = []
        p = self.player
        tr = p.get("track", {}) if p else {}
        pos = self.position()
        length = tr.get("length_ms") or 0
        if not self.compact:
            state = ("▶ PLAYING" if p.get("playing") else "❚❚ PAUSED") if p.get("available") else "◇ OFFLINE"
            left_txt = " ▌VOID // LYRICS "
            right_txt = f"{state}  {fmt_time(pos)} / {fmt_time(length)} "
            gap = W - width(left_txt) - width(right_txt)
            rows.append(bg(PANEL) + fg(HI) + BOLD + left_txt + RST + fg(FAINT) + "─" * max(0, gap) + RST + fg(NEAR) + right_txt + RST)
            if tr.get("title"):
                info = f" {tr['title']}"
                sub = f"  {tr.get('artist', '')}" + (f" · {tr['album']}" if tr.get("album") else "")
                rows.append(fg(HI) + BOLD + clip(info, W) + RST + fg(MID) + clip(sub, max(0, W - width(info))) + RST)
            else:
                rows.append(fg(MID) + " no track" + RST)
            bar_w = max(10, W - 2)
            filled = int(bar_w * (pos / length)) if length else 0
            rows.append(" " + fg(NEAR) + "━" * filled + fg(HI) + ("╸" if filled < bar_w else "") +
                        fg(FAINT) + "─" * max(0, bar_w - filled - 1) + RST)
            rows.append("")
        body_h = H - len(rows) - 2
        rows += self.body(W, body_h, pos)
        while len(rows) < H - 1:
            rows.append("")
        rows = rows[:H - 1]
        rows.append(self.footer(W))
        if self.help:
            rows = self.overlay_help(rows, W, H)
        return rows

    def body(self, W: int, H: int, pos: float) -> list[str]:
        st = self.lyrics.get("status")
        p = self.player
        if not self.connected:
            return self.message(W, H, "◇ CONNECTING TO VOID-CORE ◇", "if this stays: void launch  ·  void health")
        if not p.get("available"):
            return self.message(W, H, "◇ AWAITING SIGNAL ◇", "Spotify isn't running — open it and press play")
        if st == "loading":
            return self.message(W, H, "SEARCHING LYRICS", "local .lrc → cache → lrclib.net")
        if st == "ad":
            return self.message(W, H, "ADVERTISEMENT", "")
        if st == "instrumental":
            return self.message(W, H, "♪ INSTRUMENTAL ♪", "")
        if st == "error":
            ly = self.lyrics
            sub = (ly.get("error") or "network error")[:60] + \
                ("  ·  retrying in %ss" % ly["retry_in"] if ly.get("retry_in") else "  ·  press r to retry")
            return self.message(W, H, "LYRICS SERVICE UNREACHABLE", sub)
        if st == "plain":
            return self.plain(W, H)
        if st != "synced" or not self.lyrics.get("lines"):
            return self.message(W, H, "NO SYNCED LYRICS FOUND",
                                f"add an .lrc file to {paths.USER_LYRICS_DIR}".replace(os.path.expanduser("~"), "~"))
        return self.synced(W, H, pos)

    def message(self, W, H, title, sub) -> list[str]:
        out = [""] * max(0, H // 2 - 1)
        out.append(center(fg(HI) + BOLD + title + RST, W, width(title)))
        if sub:
            out.append(center(fg(MID) + clip(sub, W - 4) + RST, W, min(width(sub), W - 4)))
        return out

    def plain(self, W, H) -> list[str]:
        text = (self.lyrics.get("plain") or "").splitlines()
        head = "— unsynced lyrics · j/k to scroll · no timing is invented —"
        out = [center(fg(MID) + head + RST, W, width(head)), ""]
        self.scroll = max(0, min(self.scroll, max(0, len(text) - (H - 2))))
        for line in text[self.scroll:self.scroll + H - 2]:
            out.append(center(fg(NEAR) + clip(line, W - 4) + RST, W, min(width(line), W - 4)))
        return out

    def _active_colour(self, idx) -> str:
        key = (self.lyrics.get("track_id"), idx)
        now = time.monotonic()
        if key != self.line_key:
            self.line_key, self.line_since = key, now
        age = now - self.line_since
        return MID if age < 0.08 else NEAR if age < 0.2 else HI

    def synced(self, W, H, pos) -> list[str]:
        lines = self.lyrics["lines"]
        t = pos + self.lyrics.get("offset_ms", 0)
        idx = lrc.line_index(lines, int(t))
        maxw = W - 8
        cur_rows: list[str] = []
        if idx >= 0:
            ln = lines[idx]
            text = ln["text"] or "♪"
            col = self._active_colour(idx)
            if self.big and self.osc66:
                # kitty text-sizing protocol: real glyphs at 2x scale (occupies two rows)
                txt = clip(text, max(4, maxw // 2))
                pad = " " * max(0, (W - width(txt) * 2) // 2)
                cur_rows = [pad + fg(col) + BOLD + f"{ESC}]66;s=2;{txt}{ESC}\\" + RST, "\x00"]
            elif self.big and bigfont.supported(text) and bigfont.cell_width(text) <= W - 2:
                cur_rows = [center(fg(col) + r + RST, W, len(r)) for r in bigfont.render(text)]
            elif ln.get("w") and text != "♪":
                cur_rows = self.karaoke(ln, t, W, maxw)
            else:
                for wl in textwrap.wrap(text, maxw) or [text]:
                    cur_rows.append(center(fg(col) + BOLD + wl + RST, W, width(wl)))
        else:
            cur_rows = [center(fg(DIM) + "· · ·" + RST, W, 5)]
        above = (H - len(cur_rows)) // 2
        below = H - len(cur_rows) - above
        out: list[str] = []
        for k in range(above, 0, -1):
            j = idx - k
            if j < 0:
                out.append("")
                continue
            col = MID if k == 1 else DIM if k <= 3 else FAINT
            text = clip(lines[j]["text"] or "♪", maxw)
            out.append(center(fg(col) + text + RST, W, width(text)))
        out += cur_rows
        for k in range(1, below + 1):
            j = idx + k
            if j >= len(lines):
                out.append("")
                continue
            col = NEAR if k == 1 else MID if k <= 3 else DIM
            text = clip(lines[j]["text"] or "♪", maxw)
            out.append(center(fg(col) + text + RST, W, width(text)))
        return out

    def karaoke(self, ln, t, W, maxw) -> list[str]:
        rows, cur, cur_w = [], "", 0
        for w in ln["w"]:
            word = w[1]
            sung = t >= w[0]
            active = sung and (len(w) < 3 or t < w[2])
            col = (fg(HI) + BOLD) if sung else fg(MID)
            if active:
                col = f"{ESC}[4m" + fg(HI) + BOLD
            ww = width(word)
            if cur_w + ww > maxw and cur:
                rows.append((cur, cur_w))
                cur, cur_w = "", 0
            cur += col + word + RST
            cur_w += ww
        if cur:
            rows.append((cur, cur_w))
        return [center(r, W, vw) for r, vw in rows]

    def footer(self, W) -> str:
        if self.toast and time.monotonic() < self.toast[1]:
            msg = self.toast[0]
            return center(bg(PANEL) + fg(HI) + BOLD + f" {msg} " + RST, W, width(msg) + 2)
        ly = self.lyrics
        src = ly.get("source") or "—"
        info = f" {ly.get('status', '')} · {src} · offset {ly.get('user_offset_ms', 0):+d}ms "
        keys = " ␣ play  n/p skip  ←→ seek  +/- offset  b big  ? help  q quit "
        if width(info) + width(keys) > W:
            keys = " ? help  q quit "
        gap = W - width(info) - width(keys)
        return fg(MID) + clip(info, W) + " " * max(0, gap) + fg(DIM) + keys + RST

    def overlay_help(self, rows, W, H) -> list[str]:
        lines = [
            "VOID // LYRICS — KEYS", "",
            "space   play / pause", "n / p   next / previous track", "← / →   seek -5s / +5s",
            "+ / -   lyric offset ±100 ms (saved per track)", "0       reset offset",
            "r       re-fetch lyrics (ignores cache)",
            "b       big line (" + ("kitty text sizing" if self.osc66 else "block font") + ")",
            "c       compact mode", "j / k   scroll unsynced lyrics", "q       quit",
        ]
        bw = max(width(l) for l in lines) + 6
        top = max(0, (H - len(lines) - 2) // 2)
        left = max(0, (W - bw) // 2)
        for i, l in enumerate(["┌" + "─" * (bw - 2) + "┐"] + [f"│  {l}{' ' * (bw - 4 - width(l))}│" for l in lines]
                              + ["└" + "─" * (bw - 2) + "┘"]):
            if top + i < len(rows):
                rows[top + i] = " " * left + bg("background") + fg(HI if i == 1 else NEAR) + l + RST
        return rows

    def render(self) -> None:
        self.cols, self.rows = shutil.get_terminal_size((80, 24))
        frame = self.frame()
        out = []
        full = len(frame) != len(self.prev_frame)
        for i, line in enumerate(frame):
            if line == "\x00":
                continue  # second row of a 2x-scaled line
            if full or self.prev_frame[i] != line:
                out.append(f"{ESC}[{i + 1};1H{bg('background')}{ESC}[2K{line}")
        if out:
            sys.stdout.write(f"{ESC}[?2026h" + "".join(out) + f"{ESC}[?2026l")  # synchronized update
            sys.stdout.flush()
        self.prev_frame = frame

    # ------------------------------------------------------------ input
    def on_key(self, s: str) -> bool:
        keymap = {
            " ": {"cmd": "play_pause"}, "n": {"cmd": "next"}, "p": {"cmd": "prev"},
            f"{ESC}[C": {"cmd": "seek_rel", "ms": 5000}, f"{ESC}[D": {"cmd": "seek_rel", "ms": -5000},
            "+": {"cmd": "offset", "delta": 100}, "=": {"cmd": "offset", "delta": 100},
            "-": {"cmd": "offset", "delta": -100}, "0": {"cmd": "offset", "reset": True},
            "r": {"cmd": "reload_lyrics"},
        }
        if s in ("q", ESC, "\x03"):
            if self.help and s == ESC:
                self.help = False
                return True
            return False
        if s in keymap:
            self._send(keymap[s])
        elif s == "b":
            self.big = not self.big
            self.prev_frame = []
        elif s == "c":
            self.compact = not self.compact
        elif s == "?":
            self.help = not self.help
        elif s in ("j", f"{ESC}[B"):
            self.scroll += 1
        elif s in ("k", f"{ESC}[A"):
            self.scroll = max(0, self.scroll - 1)
        self.dirty = True
        return True

    def _line_key(self, pos):
        lines = self.lyrics.get("lines") or []
        if not lines:
            return None
        t = int(pos + self.lyrics.get("offset_ms", 0))
        i = lrc.line_index(lines, t)
        if i < 0 or not lines[i].get("w"):
            return i
        return i, sum(1 for w in lines[i]["w"] if t >= w[0])

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        quit_ev = asyncio.Event()
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        sys.stdout.write(f"{ESC}[?1049h{ESC}[?25l{bg('background')}{ESC}[2J")
        sys.stdout.flush()
        tty.setcbreak(fd)

        def on_stdin():
            data = os.read(fd, 256).decode(errors="ignore")
            i = 0
            while i < len(data):
                if data[i] == ESC and data[i + 1:i + 2] == "[":
                    j = i + 2
                    while j < len(data) and not ("@" <= data[j] <= "~"):
                        j += 1
                    key, i = data[i:j + 1], j + 1
                else:
                    key, i = data[i], i + 1
                if not self.on_key(key):
                    quit_ev.set()
                    return

        loop.add_reader(fd, on_stdin)
        loop.add_signal_handler(signal.SIGWINCH, lambda: setattr(self, "prev_frame", []))
        loop.add_signal_handler(signal.SIGTERM, quit_ev.set)
        try:
            self.render()
            await self.connect()
            last_key = None
            while not quit_ev.is_set():
                # redraw only when something visible changed (line/word index, second, message, fade)
                pos = self.position()
                fading = time.monotonic() - self.line_since < 0.25
                key = (int(pos // 1000), self._line_key(pos), self.cols, self.rows,
                       bool(self.toast and time.monotonic() < self.toast[1]), fading)
                if self.dirty or key != last_key or fading:
                    self.render()
                    self.dirty, last_key = False, key
                playing = bool(self.player.get("playing"))
                try:
                    await asyncio.wait_for(quit_ev.wait(), 0.05 if playing else 0.5)
                except asyncio.TimeoutError:
                    pass
        finally:
            loop.remove_reader(fd)
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            sys.stdout.write(f"{RST}{ESC}[2J{ESC}[?25h{ESC}[?1049l")
            sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="void lyrics", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--big", action="store_true", default=None, help="big current line (default: on in Kitty ≥ 0.40)")
    ap.add_argument("--no-big", dest="big", action="store_false")
    ap.add_argument("--compact", action="store_true", help="hide the header")
    ap.add_argument("--embedded", action="store_true",
                    help="run a private core in this process if void-core can't be reached (never alongside crimson-core)")
    args = ap.parse_args(argv)
    if not sys.stdin.isatty():
        print("void lyrics needs an interactive terminal", file=sys.stderr)
        return 1
    try:
        asyncio.run(LyricsTUI(args).run())
    except KeyboardInterrupt:
        pass
    return 0

