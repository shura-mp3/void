"""A 5x5 pixel font drawn with block elements, for the clock and the large active lyric.

Rendered as glyphs by Konsole's own font engine, so it is as sharp as any other text at every
display scale — nothing is rasterised or scaled.

    render(text, "half")  3 terminal rows: two pixel rows per cell (▀ ▄ █)
    render(text, "wide")  5 terminal rows: one pixel = "██" (the clock)
"""

from __future__ import annotations

_G = {
    "A": ".##.|#..#|####|#..#|#..#", "B": "###.|#..#|###.|#..#|###.", "C": ".###|#...|#...|#...|.###",
    "D": "###.|#..#|#..#|#..#|###.", "E": "####|#...|###.|#...|####", "F": "####|#...|###.|#...|#...",
    "G": ".###|#...|#.##|#..#|.###", "H": "#..#|#..#|####|#..#|#..#", "I": "###|.#.|.#.|.#.|###",
    "J": "...#|...#|...#|#..#|.##.", "K": "#..#|#.#.|##..|#.#.|#..#", "L": "#...|#...|#...|#...|####",
    "M": "#...#|##.##|#.#.#|#...#|#...#", "N": "#..#|##.#|#.##|#..#|#..#", "O": ".##.|#..#|#..#|#..#|.##.",
    "P": "###.|#..#|###.|#...|#...", "Q": ".##.|#..#|#..#|#.#.|.#.#", "R": "###.|#..#|###.|#.#.|#..#",
    "S": ".###|#...|.##.|...#|###.", "T": "#####|..#..|..#..|..#..|..#..", "U": "#..#|#..#|#..#|#..#|.##.",
    "V": "#...#|#...#|.#.#.|.#.#.|..#..", "W": "#...#|#...#|#.#.#|##.##|#...#", "X": "#..#|#..#|.##.|#..#|#..#",
    "Y": "#...#|.#.#.|..#..|..#..|..#..", "Z": "####|...#|.##.|#...|####",
    "0": ".##.|#.##|##.#|#..#|.##.", "1": ".#.|##.|.#.|.#.|###", "2": "###.|...#|.##.|#...|####",
    "3": "###.|...#|.##.|...#|###.", "4": "#..#|#..#|####|...#|...#", "5": "####|#...|###.|...#|###.",
    "6": ".##.|#...|###.|#..#|.##.", "7": "####|...#|..#.|.#..|.#..", "8": ".##.|#..#|.##.|#..#|.##.",
    "9": ".##.|#..#|.###|...#|.##.",
    " ": "...|...|...|...|...", ".": ".|.|.|.|#", ",": "..|..|..|.#|#.", ":": ".|#|.|#|.", ";": "..|.#|..|.#|#.",
    "!": "#|#|#|.|#", "?": "###.|...#|.##.|....|.#..", "'": "#|#|.|.|.", '"': "#.#|#.#|...|...|...",
    "-": "...|...|###|...|...", "+": "...|.#.|###|.#.|...", "&": ".#..|#.#.|.#.#|#.#.|.#.#",
    "(": ".#|#.|#.|#.|.#", ")": "#.|.#|.#|.#|#.", "/": "...#|..#.|.#..|#...|....", "#": ".#.#.|#####|.#.#.|#####|.#.#.",
    "*": "#.#|.#.|#.#|...|...", "=": "...|###|...|###|...", "_": "....|....|....|....|####", "♪": ".##|.#.|.#.|##.|##.",
}
GLYPHS = {k: [row for row in v.split("|")] for k, v in _G.items()}
_ACCENTS = str.maketrans("ÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝ’‘“”–—…",
                         "AAAAAACEEEEIIIINOOOOOOUUUUY''\"\"--.")


def supported(text: str) -> bool:
    return all(c in GLYPHS for c in normalise(text))


def normalise(text: str) -> str:
    return text.upper().translate(_ACCENTS).replace("...", ".")


def pixel_width(text: str) -> int:
    t = normalise(text)
    return sum(len(GLYPHS[c][0]) + 1 for c in t if c in GLYPHS) - (1 if t else 0)


def cell_width(text: str, mode: str = "half") -> int:
    return pixel_width(text) * (2 if mode == "wide" else 1)


def _bitmap(text: str) -> list[str]:
    rows = [""] * 5
    t = [c for c in normalise(text) if c in GLYPHS]
    for i, c in enumerate(t):
        for r in range(5):
            rows[r] += GLYPHS[c][r] + ("." if i < len(t) - 1 else "")
    return rows


def render(text: str, mode: str = "half") -> list[str]:
    bm = _bitmap(text)
    if mode == "wide":
        return [row.replace("#", "██").replace(".", "  ") for row in bm]
    bm.append("." * len(bm[0]))
    out = []
    for top, bot in ((bm[0], bm[1]), (bm[2], bm[3]), (bm[4], bm[5])):
        out.append("".join("█" if a == "#" and b == "#" else "▀" if a == "#" else "▄" if b == "#" else " "
                           for a, b in zip(top, bot)))
    return out
