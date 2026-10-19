"""Console output and prompts for VOID's commands (monochrome, like everything else)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

TTY = sys.stdout.isatty()
_W, _M, _D, _B, _Z = ("\033[38;2;242;242;242m", "\033[38;2;170;170;170m", "\033[38;2;119;119;119m", "\033[1m", "\033[0m") \
    if TTY else ("",) * 5

ASSUME_YES = os.environ.get("VOID_YES") == "1"


def say(m: str) -> None:
    print(f"{_W}▌{_Z} {m}")


def ok(m: str) -> None:
    print(f"  {_W}✓{_Z} {m}")


def info(m: str) -> None:
    print(f"  {_D}·{_Z} {_M}{m}{_Z}")


def warn(m: str) -> None:
    print(f"  {_W}!{_Z} {m}")


def bad(m: str) -> None:
    print(f"  {_W}✗{_Z} {_B}{m}{_Z}")


def hdr(m: str) -> None:
    print(f"\n{_B}{_W}── {m} {'─' * max(2, 60 - len(m))}{_Z}")


def ask(q: str, default: bool = False, privileged: bool = False) -> bool:
    """Yes/no. --yes (VOID_YES=1) answers the default for ordinary questions, never for privileged ones."""
    if ASSUME_YES and not privileged:
        return default
    if not sys.stdin.isatty():
        return default and not privileged
    a = input(f"  {_W}?{_Z} {q} {'[Y/n]' if default else '[y/N]'} ").strip().lower()
    return default if not a else a.startswith("y")


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(cmd: list[str], timeout: int = 30, check: bool = False, env: dict | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        if check:
            raise RuntimeError(f"{cmd[0]}: {e}") from e
        return 127, str(e)
    out = (r.stdout + r.stderr).strip()
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed ({r.returncode}): {out[-300:]}")
    return r.returncode, out
