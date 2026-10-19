"""`void music` — Spotify now playing, synced lyrics and spectrum for the terminal.

The dashboard's bottom pane runs this; it also works on its own in any VOID Konsole tab.
Everything comes from void-core (one MPRIS watcher, one lyrics fetch, one CAVA), so this
process only renders. Position is extrapolated locally from the core's (pos_ms, monotonic)
anchor, so nothing streams a 60 Hz position over the socket.

keys: space play/pause · n/p next/previous · ←/→ seek 5 s · +/- lyric offset ±100 ms · 0 reset
      r re-fetch lyrics · f cycle performance profile · q quit
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field

from .. import config, lrc
from . import bigfont
from .corelink import CoreLink
from .term import BOLD, Screen, center, clip, fg, run_safely, width

SPARK = " ▁▂▃▄▅▆▇█"
PROFILES = ["minimal", "balanced", "showcase"]


@dataclass
class State:
    connected: bool = False
    player: dict = field(default_factory=dict)
    lyrics: dict = field(default_factory=lambda: {"status": "none", "lines": []})
    ui: dict = field(default_factory=dict)
    spec: list[int] = field(default_factory=list)
    toast: str = ""
    toast_until: float = 0.0
    line_key: tuple = ()
    line_since: float = 0.0

    def handle(self, m: dict) -> None:
        t = m.get("t")
        if t == "player":
            self.player = m
        elif t == "lyrics":
            self.lyrics = m
        elif t == "ui":
            self.ui = m
        elif t == "spec":
            self.spec = m.get("b", [])
        elif t == "toast":
            self.toast, self.toast_until = m.get("text", ""), time.monotonic() + 2.5

    def position(self, now: float) -> float:
        p = self.player
        if not p:
            return 0.0
        pos = float(p.get("pos_ms", 0))
        if p.get("playing"):
            pos += (now - float(p.get("mono", now))) * 1000
        length = (p.get("track") or {}).get("length_ms") or 0
        return min(pos, length) if length else pos

    @property
    def perf(self) -> dict:
        return self.ui.get("perf") or config.PERFORMANCE["balanced"]


def fmt(ms: float) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"


def _fade(age: float, animate: bool) -> str:
    if not animate or age > 0.24:
        return "highlight"
    return "muted" if age < 0.08 else "secondary_text"


def _big_line(words: list[tuple[str, bool]], cols: int, active: str) -> list[str] | None:
    """Large active lyric (block font) with sung words bright; None if it doesn't fit in 2 rows."""
    space = bigfont.cell_width(" ")
    rows: list[list[tuple[str, bool]]] = [[]]
    w = 0
    for word, sung in words:
        ww = bigfont.cell_width(word.strip())
        if ww > cols:
            return None
        if rows[-1] and w + space + ww > cols:
            rows.append([])
            w = 0
        w += (space if rows[-1] else 0) + ww
        rows[-1].append((word.strip(), sung))
    if len(rows) > 2:
        return None
    out = []
    for row in rows:
        glyph_rows = ["", "", ""]
        plain_w = 0
        for i, (word, sung) in enumerate(row):
            g = bigfont.render(word)
            colour = fg(active if sung else "border")
            for r in range(3):
                glyph_rows[r] += (" " * space if i else "") + colour + g[r]
            plain_w += (space if i else 0) + len(g[0])
        pad = " " * max(0, (cols - plain_w) // 2)
        out += [pad + r for r in glyph_rows]
    return out


def _wrap_words(words: list[tuple[str, bool]], n: int) -> list[list[tuple[str, bool]]]:
    rows: list[list[tuple[str, bool]]] = [[]]
    w = 0
    for word, sung in words:
        word = clip(word.strip(), n)
        if not word:
            continue
        if rows[-1] and w + 1 + width(word) > n:
            rows.append([])
            w = 0
        w += (1 if rows[-1] else 0) + width(word)
        rows[-1].append((word, sung))
    return rows


def lyric_block(st: State, cols: int, rows: int, now: float) -> list[str]:
    ly = st.lyrics or {}
    status = ly.get("status")
    track = (st.player or {}).get("track") or {}

    def message(big: str, small: str = "") -> list[str]:
        out = [""] * max(0, rows // 2 - 2)
        out.append(fg("secondary_text") + BOLD + center(big, cols))
        if small:
            out.append(fg("muted") + center(clip(small, cols), cols))
        return out

    if not st.connected:
        return message("VOID-CORE OFFLINE", "starting it… if this stays, run: void doctor")
    if not track.get("title"):
        return message("AWAITING SIGNAL", "start Spotify and press play")
    if status == "loading":
        return message("SEARCHING", "local .lrc  →  cache  →  lrclib.net")
    if status == "ad":
        return message("ADVERTISEMENT")
    if status == "instrumental":
        return message("♪  INSTRUMENTAL  ♪", track.get("artist", ""))
    if status == "error":
        retry = f"retrying in {ly['retry_in']}s" if ly.get("retry_in") else "press r to retry"
        return message("LYRICS UNREACHABLE", f"{(ly.get('error') or 'network error')[:80]} · {retry}")
    if status == "plain":
        text = [l for l in (ly.get("plain") or "").splitlines() if l.strip()]
        out = [fg("muted") + center("UNSYNCED LYRICS — NO TIMING AVAILABLE, NONE INVENTED", cols)]
        return out + [fg("secondary_text") + center(clip(l, cols), cols) for l in text[: rows - 1]]
    lines = ly.get("lines") or []
    if status != "synced" or not lines:
        return message("NO SYNCED LYRICS", "drop an \"Artist - Title.lrc\" into ~/.config/void-desktop/lyrics/")

    t = st.position(now) + (ly.get("offset_ms") or 0)
    idx = lrc.line_index(lines, int(t))
    key = (ly.get("track_id"), idx)
    if key != st.line_key:
        st.line_key, st.line_since = key, now
    active = _fade(now - st.line_since, st.perf.get("music_fps", 10) >= 10)
    cur = lines[idx] if idx >= 0 else None
    text = lambda i: (lines[i]["text"] or "♪") if 0 <= i < len(lines) else ""  # noqa: E731

    if cur is None:
        current = [fg("muted") + center("·  ·  ·", cols)]
        first = text(0)
        nxt = [first] if first else []
    else:
        words = cur.get("w")
        if words:
            sung = [(w[1], w[0] <= t) for w in words]
        else:
            sung = [(w, True) for w in (cur["text"] or "♪").split()]
        current = None
        if rows >= 9 and bigfont.supported(cur["text"] or "♪"):
            current = _big_line(sung, cols - 2, active)
        if current is None:  # normal size; sung words bright when the LRC has word timing
            current = []
            for row in _wrap_words(sung, cols - 4)[:2]:
                plain = " ".join(w for w, _ in row)
                line = " ".join(fg(active if s else "muted") + BOLD + w for w, s in row)
                current.append(" " * max(0, (cols - width(plain)) // 2) + line)
        nxt = [text(idx + 1), text(idx + 2)]

    prev = text(idx - 1) if cur is not None else ""
    out = [fg("muted") + center(clip(prev, cols), cols)] if prev or rows >= 6 else []
    out += [""] if rows - len(current) >= 5 else []
    out += current
    out += [""] if rows - len(out) >= 3 else []
    shades = ["secondary_text", "muted"]
    for i, n in enumerate(x for x in nxt if x):
        out.append(fg(shades[min(i, 1)]) + center(clip(n, cols), cols))
    pad_top = max(0, (rows - len(out)) // 2)
    return ([""] * pad_top + out)[:rows]


def spectrum_rows(spec: list[int], cols: int, height: int = 2) -> list[str]:
    if not spec:
        return [""] * height
    n = max(1, cols // 2)
    vals = [spec[min(len(spec) - 1, int(i * len(spec) / n))] / 255 for i in range(n)]
    out = []
    for r in range(height):  # top row first
        line = []
        for v in vals:
            level = max(0.0, min(1.0, v * height - (height - 1 - r)))
            ch = SPARK[round(level * (len(SPARK) - 1))]
            colour = "highlight" if v > 0.75 else "secondary_text" if v > 0.4 else "border"
            line.append(fg(colour) + ch + " ")
        out.append(" " * max(0, (cols - n * 2) // 2) + "".join(line))
    return out


def render(st: State, cols: int, rows: int, now: float) -> list[str]:
    p = st.player or {}
    track = p.get("track") or {}
    ly = st.lyrics or {}
    state = "OFFLINE" if not st.connected else ("LIVE  ▶" if p.get("playing") else "HOLD  ❚❚" if track.get("title") else "IDLE")
    prof = st.ui.get("effective_performance", "")
    right = f"{state}   {prof.upper()}" + ("   GAMEMODE" if st.ui.get("gamemode") else "")
    if ly.get("status") == "synced":
        src = (ly.get("source") or "").upper()
        right = f"{'WORD' if ly.get('has_words') else 'LINE'} SYNC · {clip(src, 24)}   " + right
    left = "05 // NOW PLAYING.SYS"
    out = [fg("muted") + left + " " * max(1, cols - width(left) - width(right)) + right, ""]

    pos = st.position(now)
    length = track.get("length_ms") or 0
    times = f"{fmt(pos)} / {fmt(length)}" if track.get("title") else ""
    title = clip(track.get("title") or "—", cols - width(times) - 2)
    out.append(fg("highlight") + BOLD + title + "\x1b[22m" + " " * max(1, cols - width(title) - width(times)) + fg("secondary_text") + times)
    meta = " · ".join(x for x in (track.get("artist"), track.get("album")) if x)
    off = ly.get("user_offset_ms") or 0
    off_s = f"OFFSET {off:+d} MS" if off else ""
    meta = clip(meta, cols - width(off_s) - 2)
    out.append(fg("secondary_text") + meta + " " * max(1, cols - width(meta) - width(off_s)) + fg("muted") + off_s)
    filled = int(cols * pos / length) if length else 0
    out.append(fg("highlight") + "━" * filled + fg("border") + "─" * (cols - filled))

    show_spec = st.perf.get("spectrum", True) and rows >= 14
    hints = rows >= 12
    body = rows - len(out) - (2 if show_spec else 0) - (1 if hints else 0)
    out += lyric_block(st, cols, max(1, body), now)
    out = (out + [""] * rows)[: rows - (2 if show_spec else 0) - (1 if hints else 0)]
    if show_spec:
        out += spectrum_rows(st.spec, cols, 2)
    if hints:
        msg = st.toast if st.toast and now < st.toast_until else \
            "space play/pause · n/p track · ←/→ seek · +/- offset · r refetch · f profile · q quit"
        out.append(fg("highlight" if st.toast and now < st.toast_until else "border") + center(clip(msg, cols), cols))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="void music", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-keys", action="store_true", help="display only (no keyboard control)")
    args = ap.parse_args(argv)
    st = State()
    link = CoreLink(topics=["spec"])

    def loop() -> None:
        with Screen(keys=not args.no_keys) as scr:
            while True:
                link.ensure()
                if link.connected != st.connected:
                    st.connected = link.connected
                for m in link.read():
                    st.handle(m)
                st.connected = link.connected
                now = time.monotonic()
                cols, rows = scr.size()
                scr.draw(render(st, cols, rows, now))
                playing = bool(st.player.get("playing")) and st.connected
                fps = max(1, st.perf.get("music_fps", 10)) if playing else 1
                ready = link.wait(1 / fps, [scr._fd] if scr._fd is not None and scr.keys else [])
                if scr._fd is not None and scr._fd in ready:
                    key = scr.read_key(0)
                    if key in ("q", "Q"):
                        return
                    cmd = {" ": {"cmd": "play_pause"}, "n": {"cmd": "next"}, "p": {"cmd": "prev"},
                           "right": {"cmd": "seek_rel", "ms": 5000}, "left": {"cmd": "seek_rel", "ms": -5000},
                           "+": {"cmd": "offset", "delta": 100}, "=": {"cmd": "offset", "delta": 100},
                           "-": {"cmd": "offset", "delta": -100}, "0": {"cmd": "offset", "reset": True},
                           "r": {"cmd": "reload_lyrics"}}.get(key or "")
                    if key == "f":
                        cur = st.ui.get("performance", "balanced")
                        cmd = {"cmd": "ui", "performance": PROFILES[(PROFILES.index(cur) + 1) % 3] if cur in PROFILES else "balanced"}
                    if cmd:
                        link.send(cmd)

    return run_safely(loop)


if __name__ == "__main__":
    sys.exit(main())
