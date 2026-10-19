"""LRC / enhanced-LRC (A2) parser.

Line format:      [mm:ss.xx]text            (several leading stamps allowed)
Word timestamps:  [mm:ss.xx]<mm:ss.xx>word <mm:ss.xx>word ...
Tags:             [offset:+250] [ar:...] [ti:...]

Word timings are only produced when the file actually contains them; we never invent them.
"""

from __future__ import annotations

import re

_STAMP = r"(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?"
LINE_STAMP = re.compile(r"\[" + _STAMP + r"\]")
WORD_STAMP = re.compile(r"<" + _STAMP + r">")
TAG = re.compile(r"^\[([A-Za-z#]+):(.*)\]\s*$")


def _ms(m: str, s: str, frac: str | None) -> int:
    ms = (int(m) * 60 + int(s)) * 1000
    if frac:
        ms += int(frac.ljust(3, "0")[:3])
    return ms


def _parse_words(body: str) -> tuple[str, list[list] | None]:
    """Split '<t>word <t>word' into ([t, text], ...). Returns (plain_text, words|None)."""
    parts = WORD_STAMP.split(body)
    if len(parts) < 4:  # no word stamps
        return body.strip(), None
    words: list[list] = []
    lead = parts[0]
    for i in range(1, len(parts), 4):
        t = _ms(parts[i], parts[i + 1], parts[i + 2])
        text = parts[i + 3]
        if text.strip():
            words.append([t, text])
        elif words:
            # trailing stamp with no text marks the end of the previous word
            words[-1].append(t)
    if lead.strip():
        words.insert(0, [words[0][0] if words else 0, lead])
    text = "".join(w[1] for w in words).strip()
    return re.sub(r"\s+", " ", text), (words or None)


def parse(text: str) -> dict:
    lines: list[dict] = []
    offset = 0
    tags: dict[str, str] = {}
    for raw in text.splitlines():
        raw = raw.strip("﻿ \t\r")
        if not raw:
            continue
        stamps = []
        pos = 0
        while True:
            m = LINE_STAMP.match(raw, pos)
            if not m:
                break
            stamps.append(_ms(*m.groups()))
            pos = m.end()
        if not stamps:
            tm = TAG.match(raw)
            if tm:
                key, val = tm.group(1).lower(), tm.group(2).strip()
                tags[key] = val
                if key == "offset":
                    try:
                        offset = int(val)
                    except ValueError:
                        pass
            continue
        body, words = _parse_words(raw[pos:])
        for t in stamps:
            lines.append({"t": t, "text": body, "w": words})
    lines.sort(key=lambda ln: ln["t"])
    has_words = any(ln["w"] for ln in lines)
    return {"lines": lines, "offset": offset, "tags": tags, "has_words": has_words}


def line_index(lines: list[dict], t_ms: int) -> int:
    """Index of the active line at t_ms (binary search), -1 before the first line."""
    lo, hi = 0, len(lines) - 1
    ans = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if lines[mid]["t"] <= t_ms:
            ans = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ans
