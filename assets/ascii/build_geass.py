#!/usr/bin/env python3
"""Build the VOID Geass sigil from its left half (mirrored, so it is exactly symmetric).

    python3 assets/ascii/build_geass.py      writes assets/ascii/geass.txt (plain)
                                             and config/fastfetch/geass.txt (fastfetch $1/$2 colours)
$1 = highlight (upper wings, body), $2 = muted (lower wings). Block elements only (U+2580-259F),
so every glyph is one cell wide in Konsole regardless of locale.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# (left half, centre column, layer) — layer 1 = bright, 2 = lower wing (grey) except the body
ROWS = [
    ("▄▄                  ", " ", 1),
    (" ▀██▄▄              ", " ", 1),
    ("   ▀████▄▄          ", " ", 1),
    ("     ▀▀█████▄▄      ", "▄", 1),
    ("         ▀▀█████▄▄ █", "█", 1),
    ("             ▀▀█████", "█", 1),
    ("           ▄▄▄▄▄████", "█", 2),
    ("       ▄▄██▀▀▀▀  ▀██", "█", 2),
    ("    ▄██▀▀          █", "█", 2),
    ("  ▀▀▀               ", "█", 2),
    ("                    ", "▀", 2),
]
BODY = 5  # columns either side of the centre drawn bright on grey rows


def lines() -> list[tuple[str, int]]:
    out = []
    for left, centre, layer in ROWS:
        assert len(left) == 20 and len(centre) == 1, left
        out.append((left + centre + left[::-1], layer))
    return out


def coloured(row: str, layer: int) -> str:
    if layer == 1:
        return "$1" + row
    c = 20  # centre column of the 41-wide sigil
    a, b = c - BODY, c + BODY + 1
    out = "$2" + row[:a] + "$1" + row[a:b] + ("$2" + row[b:] if row[b:].strip() else "")
    return out.rstrip()


def main() -> None:
    rows = lines()
    plain = "\n".join(r.rstrip() for r, _ in rows) + "\n"
    (ROOT / "assets" / "ascii" / "geass.txt").write_text(plain)
    (ROOT / "config" / "fastfetch" / "geass.txt").write_text("\n".join(coloured(r.rstrip(), l) for r, l in rows) + "\n")
    print(plain)


if __name__ == "__main__":
    main()
