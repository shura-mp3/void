"""`void rain` — sparse grey data rain. Low cost: ~10 fps (balanced), diffed redraws, static in minimal.

Glyphs are ASCII/Latin only, so every cell is exactly one column wide in any font.
"""

from __future__ import annotations

import random
import sys
import time

from .. import config
from .term import RESET, Screen, fg, run_safely

GLYPHS = "0123456789ABCDEF:.=+*<>|/\\#%$"
SHADES = ["highlight", "text", "secondary_text", "muted", "muted", "border", "border"]


class Rain:
    def __init__(self, cols: int, rows: int, seed: int | None = None, dense: bool = False):
        self.rng = random.Random(seed)
        self.dense = dense
        self.resize(cols, rows)

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, max(1, rows)
        self.grid = [[self.rng.choice(GLYPHS) for _ in range(cols)] for _ in range(self.rows)]
        # sparse: every other column carries a stream (subtle); dense: every column (cmatrix-like)
        self.drops = {c: self._new_drop(start=True) for c in range(0, cols, 1 if self.dense else 2)}
        self.colour_cache = [fg(s) for s in SHADES]

    def _new_drop(self, start: bool = False) -> list[float]:
        # [head row, speed rows/tick, trail length]
        head = self.rng.uniform(-self.rows, self.rows) if start else self.rng.uniform(-self.rows * 0.8, 0)
        return [head, self.rng.uniform(0.25, 0.9), self.rng.randint(5, max(6, self.rows))]

    def step(self) -> None:
        for c, d in self.drops.items():
            d[0] += d[1]
            if d[0] - d[2] > self.rows:
                self.drops[c] = self._new_drop()
            h = int(d[0])
            if 0 <= h < self.rows and self.rng.random() < 0.6:
                self.grid[h][c] = self.rng.choice(GLYPHS)
        for _ in range(max(1, self.cols // 20)):  # a few glyphs mutate in place
            self.grid[self.rng.randrange(self.rows)][self.rng.randrange(self.cols)] = self.rng.choice(GLYPHS)

    def lines(self) -> list[str]:
        shade = [[-1] * self.cols for _ in range(self.rows)]
        for c, (head, _, trail) in self.drops.items():
            h = int(head)
            for k in range(trail):
                r = h - k
                if 0 <= r < self.rows:
                    shade[r][c] = min(len(SHADES) - 1, k * len(SHADES) // trail)
        out = []
        for r in range(self.rows):
            parts, last = [], None
            for c in range(self.cols):
                s = shade[r][c]
                if s < 0:
                    if last != -1:
                        parts.append(RESET)
                        last = -1
                    parts.append(" ")
                    continue
                if s != last:
                    parts.append(self.colour_cache[s])
                    last = s
                parts.append(self.grid[r][c])
            out.append("".join(parts))
        return out


def main(argv: list[str] | None = None) -> int:
    fps = config.profile(config.current_profile())["rain_fps"]
    dense = bool(argv and "--dense" in argv)

    def loop() -> None:
        with Screen() as scr:
            cols, rows = scr.size()
            rain = Rain(cols, rows - 1, dense=dense)
            while True:
                if scr.resized:
                    cols, rows = scr.size()
                    rain.resize(cols, rows - 1)
                label = fg("muted") + "03 // DATA.STREAM" + (" · STATIC (MINIMAL)" if not fps else "")
                scr.draw([label] + rain.lines())
                if not fps:
                    scr.read_key(3600)  # minimal profile: one static frame, redrawn only on resize
                    continue
                t0 = time.monotonic()
                rain.step()
                scr.read_key(max(0.0, 1 / fps - (time.monotonic() - t0)))

    return run_safely(loop)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
