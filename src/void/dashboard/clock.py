"""`void clock` — large 24-hour clock with date, and (grid layout) the current lyrics underneath.

Wakes once per second (once per minute without seconds); only while a song with synced lyrics is
playing does it redraw at the profile's music rate. Lyrics come from void-core like everywhere else.
"""

from __future__ import annotations

import sys
import time

from .. import config, lrc
from . import bigfont, music
from .corelink import CoreLink
from .term import BOLD, Screen, center, clip, fg, run_safely, width


def render(now: time.struct_time, cols: int, rows: int, seconds: bool, style: str = "classic") -> list[str]:
    if style == "segment":
        return render_segment(now, cols, rows, seconds)
    hhmm = time.strftime("%H:%M:%S" if seconds else "%H:%M", now)
    mode = "wide" if bigfont.cell_width(hhmm, "wide") <= cols - 2 and rows >= 8 else "half"
    if bigfont.cell_width(hhmm, mode) > cols:
        hhmm = time.strftime("%H:%M", now)
    digits = bigfont.render(hhmm, mode)
    date = time.strftime("%A  %d  %B  %Y", now).upper()
    tz = time.strftime("%Z", now)
    sub = f"WEEK {time.strftime('%V', now)}  ·  DAY {time.strftime('%j', now)}  ·  {tz}"
    label = "04 // CHRONO.SYS"
    block = [fg("highlight") + center(d, cols) for d in digits]
    block += ["", fg("secondary_text") + center(" ".join(date), cols) if width(" ".join(date)) <= cols else fg("secondary_text") + center(date, cols)]
    if rows >= len(block) + 4:
        block.append(fg("muted") + center(sub, cols))
    top = max(1, (rows - len(block)) // 2)
    return [fg("muted") + label] + [""] * (top - 1) + block


def render_segment(now: time.struct_time, cols: int, rows: int, seconds: bool, lyrics: list[str] | None = None) -> list[str]:
    """The reference look: big digits in groups ("21 29 50"), ISO date underneath — then the lyrics."""
    text = time.strftime("%H %M %S" if seconds else "%H %M", now)
    room = rows - (len(lyrics) + 1 if lyrics else 0)
    mode = "wide" if bigfont.cell_width(text, "wide") <= cols - 2 and room >= 8 else "half"
    digits = bigfont.render(text, mode)
    block = [fg("highlight") + center(d, cols) for d in digits] + ["", fg("muted") + center(time.strftime("%Y-%m-%d", now), cols)]
    if lyrics:
        block += [""] + lyrics[: max(0, rows - len(block) - 1)]
    top = max(0, (rows - len(block)) // 2)
    return [""] * top + block


def lyric_lines(st: "music.State", cols: int, now: float) -> list[str]:
    """♪ title · artist, then previous / current (karaoke when the LRC has word timing) / next line.
    Empty while nothing is playing, so the tile stays a clean clock."""
    track = (st.player or {}).get("track") or {}
    if not st.connected or not track.get("title"):
        return []
    head = " · ".join(x for x in (track.get("title"), track.get("artist")) if x)
    out = [fg("muted") + center(clip("♪ " + head, cols - 4), cols)]
    ly = st.lyrics or {}
    lines = ly.get("lines") or []
    if ly.get("status") != "synced" or not lines:
        return out
    t = st.position(now) + (ly.get("offset_ms") or 0)
    idx = lrc.line_index(lines, int(t))
    key = (ly.get("track_id"), idx)
    if key != st.line_key:
        st.line_key, st.line_since = key, now
    active = music._fade(now - st.line_since, st.perf.get("music_fps", 10) >= 10)
    text = lambda i: (lines[i]["text"] or "♪") if 0 <= i < len(lines) else ""  # noqa: E731
    out.append("")
    out.append(fg("muted") + center(clip(text(idx - 1), cols - 4), cols))
    if idx < 0:
        out.append(fg("border") + center("·  ·  ·", cols))
    else:
        cur = lines[idx]
        words = [(w[1], w[0] <= t) for w in cur["w"]] if cur.get("w") else [(w, True) for w in text(idx).split()]
        for row in music._wrap_words(words, cols - 6)[:2]:
            plain = " ".join(w for w, _ in row)
            out.append(" " * max(0, (cols - width(plain)) // 2) +
                       " ".join(fg(active if s else "muted") + BOLD + w for w, s in row))
    out.append(fg("secondary_text") + center(clip(text(idx + 1), cols - 4), cols))
    return out


def main(argv: list[str] | None = None) -> int:
    cfg = config.load()
    style = cfg["dashboard"].get("clock_style") or ("segment" if cfg["dashboard"].get("layout", "grid") == "grid" else "classic")
    seconds = config.profile(config.current_profile())["clock_seconds"]
    if argv and "--seconds" in argv:
        seconds = True
    show_lyrics = style == "segment" and cfg["dashboard"].get("clock_lyrics", True)

    def loop() -> None:
        st = music.State()
        link = CoreLink(topics=[]) if show_lyrics else None
        with Screen() as scr:
            while True:
                step = 1 if seconds else 60
                wait = step - (time.time() % step) + 0.01
                lyrics = None
                if link:
                    link.ensure()
                    for m in link.read():
                        st.handle(m)
                    st.connected = link.connected
                    lyrics = lyric_lines(st, scr.size()[0], time.monotonic())
                    if st.player.get("playing") and (st.lyrics or {}).get("status") == "synced":
                        wait = min(wait, 1 / max(1, st.perf.get("music_fps", 10)))
                cols, rows = scr.size()
                if style == "segment":
                    scr.draw(render_segment(time.localtime(), cols, rows, seconds, lyrics))
                else:
                    scr.draw(render(time.localtime(), cols, rows, seconds, style))
                if link:
                    link.wait(wait)
                else:
                    scr.read_key(wait)

    return run_safely(loop)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
