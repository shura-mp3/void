"""`void clock` — large 24-hour clock with date. Wakes once per second (once per minute without seconds)."""

from __future__ import annotations

import sys
import time

from .. import config
from . import bigfont
from .term import Screen, center, fg, run_safely, width


def render(now: time.struct_time, cols: int, rows: int, seconds: bool) -> list[str]:
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


def main(argv: list[str] | None = None) -> int:
    seconds = config.profile(config.current_profile())["clock_seconds"]
    if argv and "--seconds" in argv:
        seconds = True

    def loop() -> None:
        with Screen() as scr:
            while True:
                cols, rows = scr.size()
                scr.draw(render(time.localtime(), cols, rows, seconds))
                step = 1 if seconds else 60
                scr.read_key(step - (time.time() % step) + 0.01)

    return run_safely(loop)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
