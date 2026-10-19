"""`void sysmon` — built-in monochrome system monitor, used when btop is not installed.

Reads /proc and /sys directly (shared code with void-core's SysInfo); refreshes at the
profile's btop interval (3 / 2 / 1 s).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from .. import config
from ..sysinfo import SysInfo
from .term import BOLD, Screen, clip, fg, run_safely

TICK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def bar(frac: float, n: int) -> str:
    frac = max(0.0, min(1.0, frac or 0.0))
    full = int(frac * n)
    colour = "highlight" if frac > 0.85 else "text" if frac > 0.5 else "secondary_text"
    return fg(colour) + "█" * full + fg("border") + "░" * (n - full)


class Procs:
    def __init__(self):
        self.prev: dict[int, int] = {}
        self.t = time.monotonic()

    def top(self, n: int) -> list[tuple[float, int, str, int]]:
        now = time.monotonic()
        dt = max(0.001, now - self.t)
        self.t = now
        cur, rows = {}, []
        for d in Path("/proc").iterdir():
            if not d.name.isdigit():
                continue
            try:
                raw = (d / "stat").read_text()
                name = raw[raw.index("(") + 1: raw.rindex(")")]
                f = raw[raw.rindex(")") + 2:].split()
                ticks = int(f[11]) + int(f[12])
                rss = int(f[21]) * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
            except (OSError, ValueError, IndexError):
                continue
            pid = int(d.name)
            cur[pid] = ticks
            if pid in self.prev:
                rows.append((100 * (ticks - self.prev[pid]) / TICK / dt, pid, name, rss))
        self.prev = cur
        return sorted(rows, reverse=True)[:n]


def render(s: dict, procs: list, cols: int, rows: int) -> list[str]:
    bw = max(10, cols - 26)
    up = s.get("uptime_s", 0)
    out = [fg("muted") + "02 // SYSTEM.MON" + fg("border") + "   built-in (install btop for the full monitor)", ""]

    def row(label: str, frac: float, value: str) -> str:
        return fg("muted") + f"{label:<5}" + bar(frac, bw) + fg("text") + f"  {value:>17}"

    out.append(row("CPU", s.get("cpu_pct", 0) / 100, f"{s.get('cpu_pct', 0):5.1f}%" +
                   (f"  {s['cpu_temp']:.0f}°C" if s.get("cpu_temp") else "")))
    mt = s.get("mem_total") or 1
    out.append(row("RAM", s.get("mem_used", 0) / mt, f"{s.get('mem_used', 0) / 1024:.1f}/{mt / 1024:.1f} GiB"))
    if s.get("gpu_pct") is not None:
        out.append(row("GPU", s["gpu_pct"] / 100, f"{s['gpu_pct']:5.0f}%" + (f"  {s['gpu_temp']:.0f}°C" if s.get("gpu_temp") else "")))
    load = " ".join(f"{x:.2f}" for x in s.get("load", []))
    out.append(fg("muted") + "LOAD " + fg("text") + load + fg("muted") + "   UP " + fg("text") +
               f"{up // 86400}d {up % 86400 // 3600}h {up % 3600 // 60}m" + fg("muted") + "   CORES " + fg("text") + str(s.get("cores", "")))
    out += ["", fg("muted") + BOLD + f"{'PID':>7}  {'CPU%':>6}  {'MEM':>7}  PROCESS"]
    for cpu, pid, name, rss in procs[: max(0, rows - len(out))]:
        out.append(fg("highlight" if cpu > 50 else "text" if cpu > 5 else "secondary_text") +
                   f"{pid:>7}  {cpu:6.1f}  {rss:>5}M  " + clip(name, max(4, cols - 28)))
    return out


def main(argv: list[str] | None = None) -> int:
    interval = config.profile(config.current_profile())["btop_ms"] / 1000

    def loop() -> None:
        info, procs = SysInfo(), Procs()
        aloop = asyncio.new_event_loop()
        with Screen() as scr:
            while True:
                s = aloop.run_until_complete(info.sample())
                cols, rows = scr.size()
                scr.draw(render(s, procs.top(rows), cols, rows))
                scr.read_key(interval)

    return run_safely(loop)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
