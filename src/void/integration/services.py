"""systemd user services: VOID's own (void-core) and pausing Crimson's while VOID is active.

VOID and Crimson must never both watch Spotify, fetch lyrics, or drive the right-hand monitor.
Activation records whether crimson-core / crimson-dashboard were running and enabled, stops and
disables them, and deactivation puts back exactly that state. Crimson's files are never touched.
"""

from __future__ import annotations

from pathlib import Path

from .. import paths
from . import files, ui
from .journal import Handler, register

UNIT_DIR = paths.XDG_CONFIG / "systemd" / "user"
CRIMSON_UNITS = ["crimson-dashboard.service", "crimson-core.service"]


def systemctl(*args: str) -> tuple[int, str]:
    if not ui.have("systemctl"):
        return 127, "systemctl not found"
    return ui.run(["systemctl", "--user", *args])


def unit_exists(unit: str) -> bool:
    rc, out = systemctl("list-unit-files", "--no-legend", unit)
    return rc == 0 and unit in out


@register
class Service(Handler):
    kind = "service"

    def get(self, key):
        active = systemctl("is-active", key)[1].strip() in ("active", "activating", "reloading")
        enabled = systemctl("is-enabled", key)[1].strip() in ("enabled", "enabled-runtime")
        return {"active": active, "enabled": enabled}

    def set(self, key, value):
        cur = self.get(key)
        if value["enabled"] != cur["enabled"]:
            systemctl("enable" if value["enabled"] else "disable", key)
        if value["active"] != cur["active"]:
            rc, out = systemctl("start" if value["active"] else "stop", key)
            if rc != 0:
                raise RuntimeError(f"systemctl --user {'start' if value['active'] else 'stop'} {key}: {out[-200:]}")

    def describe(self, key):
        return f"user service {key}"


def core_unit() -> str:
    import sys
    return "\n".join([
        "[Unit]",
        "Description=VOID core (Spotify MPRIS, synced lyrics, spectrum, system stats)",
        "Documentation=file://" + str(paths.PROJECT_DIR / "README.md"),
        "After=graphical-session.target",
        "PartOf=graphical-session.target",
        "",
        "[Service]",
        f"ExecStart={sys.executable} -m void.core",
        f"WorkingDirectory={paths.PROJECT_DIR}",
        f"Environment=PYTHONPATH={paths.SRC_DIR}",
        "Restart=on-failure",
        "RestartSec=3",
        "Nice=5",
        "CPUWeight=40",
        "MemoryMax=300M",
        "",
        "[Install]",
        "WantedBy=graphical-session.target",
        "",
    ])


def install_units() -> None:
    if files.install(UNIT_DIR / "void-core.service", core_unit()):
        systemctl("daemon-reload")


def crimson_state(cfg: dict) -> dict:
    proj = Path(cfg["crimson"]["project_dir"]).expanduser()
    units = {u: (Service().get(u) if unit_exists(u) else None) for u in CRIMSON_UNITS}
    return {"project": str(proj) if proj.is_dir() else None, "units": units,
            "running": any(v and v["active"] for v in units.values())}
