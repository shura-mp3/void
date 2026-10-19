"""Cheap system statistics read straight from /proc and /sys (no psutil dependency)."""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import socket
import time
from pathlib import Path


def _read(path: str, default: str = "") -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def os_name() -> str:
    for line in _read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip('"')
    return platform.system()


def cpu_model() -> str:
    for line in _read("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            name = line.split(":", 1)[1].strip()
            for junk in ("(R)", "(TM)", " CPU", "with Radeon Graphics", "Processor"):
                name = name.replace(junk, "")
            return " ".join(name.split()).split(" @")[0]
    return platform.processor() or "cpu"


def _hwmon_temp(names: tuple[str, ...]) -> float | None:
    for hw in Path("/sys/class/hwmon").glob("hwmon*"):
        if _read(f"{hw}/name") in names:
            for inp in sorted(hw.glob("temp*_input")):
                v = _read(str(inp))
                if v.isdigit():
                    return int(v) / 1000
    return None


class SysInfo:
    def __init__(self):
        self._last_cpu: tuple[int, int] | None = None
        self.static = {
            "host": socket.gethostname(),
            "user": os.environ.get("USER", ""),
            "os": os_name(),
            "kernel": platform.release(),
            "cpu": cpu_model(),
            "cores": os.cpu_count() or 1,
            "gpu": "",
            "packages": "",
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
            "session": os.environ.get("XDG_SESSION_TYPE", ""),
        }
        self._amd_busy = next(iter(Path("/sys/class/drm").glob("card*/device/gpu_busy_percent")), None)
        self._has_nvsmi = bool(shutil.which("nvidia-smi"))
        self._nv_cache: tuple[float, dict] = (0.0, {})

    async def load_static(self) -> None:
        """Slow one-off facts (package count, GPU name), run once in the background."""
        async def run(*cmd: str) -> str:
            try:
                p = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                out, _ = await asyncio.wait_for(p.communicate(), 10)
                return out.decode(errors="replace")
            except (OSError, asyncio.TimeoutError):
                return ""

        if shutil.which("rpm"):
            n = (await run("rpm", "-qa", "--qf", ".")).count(".")
            if n:
                self.static["packages"] = f"{n} (rpm)"
        if shutil.which("flatpak"):
            n = len((await run("flatpak", "list", "--app", "--columns=application")).split())
            if n:
                self.static["packages"] += f"{', ' if self.static['packages'] else ''}{n} (flatpak)"
        if self._has_nvsmi:
            names = (await run("nvidia-smi", "--query-gpu=name", "--format=csv,noheader")).strip().splitlines()
            if names:
                self.static["gpu"] = names[0]
        if not self.static["gpu"] and shutil.which("lspci"):
            for line in (await run("lspci", "-mm")).splitlines():
                if '"VGA' in line or '"3D' in line or '"Display' in line:
                    parts = line.split('"')
                    if len(parts) >= 6:
                        self.static["gpu"] = parts[5].split("[")[-1].rstrip("]") if "[" in parts[5] else parts[5]
                        break

    def _cpu_percent(self) -> float:
        fields = _read("/proc/stat").splitlines()[0].split()[1:]
        vals = list(map(int, fields))
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals[:8])
        pct = 0.0
        if self._last_cpu:
            dt, di = total - self._last_cpu[0], idle - self._last_cpu[1]
            pct = 100.0 * (1 - di / dt) if dt > 0 else 0.0
        self._last_cpu = (total, idle)
        return round(pct, 1)

    @staticmethod
    def _mem() -> tuple[int, int]:
        info = {}
        for line in _read("/proc/meminfo").splitlines():
            k, v = line.split(":", 1)
            info[k] = int(v.split()[0])
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        return (total - avail) // 1024, total // 1024

    async def _gpu(self) -> dict:
        if self._amd_busy:
            busy = _read(str(self._amd_busy))
            return {"gpu_pct": int(busy) if busy.isdigit() else None, "gpu_temp": _hwmon_temp(("amdgpu",))}
        if self._has_nvsmi:
            ts, cached = self._nv_cache
            if time.monotonic() - ts < 4:
                return cached
            try:
                p = await asyncio.create_subprocess_exec(
                    "nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                out, _ = await asyncio.wait_for(p.communicate(), 3)
                u, t = (x.strip() for x in out.decode().splitlines()[0].split(","))
                cached = {"gpu_pct": int(u), "gpu_temp": float(t)}
            except (OSError, ValueError, IndexError, asyncio.TimeoutError):
                cached = {"gpu_pct": None, "gpu_temp": None}
            self._nv_cache = (time.monotonic(), cached)
            return cached
        return {"gpu_pct": None, "gpu_temp": None}

    async def sample(self) -> dict:
        used, total = self._mem()
        up = float(_read("/proc/uptime", "0").split()[0])
        load = os.getloadavg()
        d = {
            "cpu_pct": self._cpu_percent(),
            "cpu_temp": _hwmon_temp(("k10temp", "coretemp", "zenpower", "cpu_thermal")),
            "mem_used": used,
            "mem_total": total,
            "load": [round(x, 2) for x in load],
            "uptime_s": int(up),
            **(await self._gpu()),
        }
        d.update(self.static)
        return d
