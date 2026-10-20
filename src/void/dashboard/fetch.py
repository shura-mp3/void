"""`void fetch` — the Geass sigil + system summary (fastfetch with VOID's config).

Never touches your own ~/.config/fastfetch/config.jsonc: VOID's config is rendered to
~/.local/state/void-desktop/generated/fastfetch.jsonc and passed with -c.
Without fastfetch, a built-in summary is printed next to the same sigil.

    void fetch            print once (also used by the VOID Konsole profile at shell start)
    void fetch --pane     dashboard pane: re-render every N s (profile), and on resize
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time

from .. import config, paths
from ..sysinfo import SysInfo
from .term import BOLD, RESET, fg, width

LOGO = paths.CONFIG_SRC / "fastfetch" / "geass.txt"
PLAIN_LOGO = paths.PROJECT_DIR / "assets" / "ascii" / "geass.txt"


def config_file() -> str:
    """Render the fastfetch config template with absolute paths (idempotent)."""
    dest = paths.GENERATED / "fastfetch.jsonc"
    quote = config.load()["dashboard"].get("quote") or ""
    text = (paths.CONFIG_SRC / "fastfetch" / "void.jsonc.in").read_text().replace("@LOGO@", str(LOGO)) \
        .replace("@QUOTE@", json.dumps(quote)[1:-1])
    if not quote:
        text = text.replace('"format": "❝  ❞"', '"format": ""')
    if not dest.exists() or dest.read_text() != text:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    return str(dest)


def builtin() -> None:
    s = asyncio.run(_sample())
    art = PLAIN_LOGO.read_text().splitlines()
    up = s.get("uptime_s", 0)
    info = [
        fg("highlight") + BOLD + f"{s.get('user')}@{s.get('host')}" + RESET,
        fg("border") + "─" * 24,
        ("OS", s.get("os")), ("KERNEL", s.get("kernel")), ("UPTIME", f"{up // 3600}h {up % 3600 // 60}m"),
        ("DESKTOP", f"{s.get('desktop') or '?'} ({s.get('session') or '?'})"), ("CPU", s.get("cpu")),
        ("GPU", s.get("gpu") or "—"), ("RAM", f"{s.get('mem_used', 0) / 1024:.1f} / {s.get('mem_total', 0) / 1024:.1f} GiB"),
        ("TERMINAL", os.environ.get("TERM_PROGRAM") or ("Konsole" if os.environ.get("KONSOLE_VERSION") else os.environ.get("TERM", "?"))),
    ]
    lw = max(width(l) for l in art) + 4
    print()
    for i in range(max(len(art), len(info))):
        a = art[i] if i < len(art) else ""
        colour = "highlight" if i < 6 else "muted"
        left = "  " + fg(colour) + a + " " * (lw - width(a))
        it = info[i] if i < len(info) else ""
        if isinstance(it, tuple):
            it = fg("muted") + f"{it[0]:<9}" + fg("border") + " ▸ " + fg("text") + str(it[1])
        print(left + it + RESET)
    print()


async def _sample() -> dict:
    si = SysInfo()
    await si.load_static()
    return await si.sample()


def show() -> None:
    if shutil.which("fastfetch"):
        r = subprocess.run(["fastfetch", "-c", config_file()])
        if r.returncode == 0:
            return
    builtin()


def pane() -> int:
    refresh = config.profile(config.current_profile())["fetch_refresh"]
    redraw = [True]
    signal.signal(signal.SIGWINCH, lambda *_: redraw.__setitem__(0, True))
    last = 0.0
    sys.stdout.write("\x1b[?25l")
    try:
        while True:
            if redraw[0] or (refresh and time.monotonic() - last >= refresh):
                redraw[0] = False
                last = time.monotonic()
                sys.stdout.write("\x1b[2J\x1b[H" + fg("muted") + "01 // GEASS.SYS" + RESET + "\n")
                sys.stdout.flush()
                show()
                sys.stdout.flush()
            try:
                time.sleep(refresh or 3600)
            except InterruptedError:
                pass
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write("\x1b[?25h")


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    if "--config-path" in argv:
        print(config_file())
        return 0
    if "--pane" in argv:
        return pane()
    if "--builtin" in argv:
        builtin()
        return 0
    show()
    return 0
