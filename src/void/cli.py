"""`void <command>` dispatcher (filled in as components are added)."""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    cmd, rest = (argv[0], argv[1:]) if argv else ("help", [])
    if cmd == "tokens":
        from . import tokens
        return tokens.main(rest)
    print(__doc__)
    return 0 if cmd in ("help", "-h", "--help") else 2
