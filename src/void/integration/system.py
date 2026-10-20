"""`void inspect` (read-only report), `void install` (dependencies + user-level setup), `void health`."""

from __future__ import annotations

import datetime as dt
import os
import platform
import re
import subprocess
from pathlib import Path

from .. import client, config, paths, tokens
from ..dashboard import session
from . import files, kde, konsole, monitors, services, spotify, ui
from .journal import Journal

# tool -> Fedora/Nobara package (official repositories only)
DEPS = {
    "tmux": ("tmux", True, "dashboard layout"),
    "fastfetch": ("fastfetch", False, "Geass system summary (built-in fallback otherwise)"),
    "btop": ("btop", False, "system monitor pane (built-in fallback otherwise)"),
    "cava": ("cava", False, "audio spectrum"),
    "playerctl": ("playerctl", False, "manual playback control from scripts (VOID itself uses D-Bus)"),
    "tty-clock": ("tty-clock", False, "optional clock ([dashboard] clock = \"tty-clock\")"),
    "cmatrix": ("cmatrix", False, "optional rain ([dashboard] rain = \"cmatrix\")"),
}
PY_DEPS = {"jeepney": ("python3-jeepney", True, "Spotify MPRIS over D-Bus"),
           "PIL": ("python3-pillow", False, "wallpaper analysis (bundled fallback otherwise)")}


def _py_has(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


def deps_report() -> list[dict]:
    out = []
    for tool, (pkg, required, why) in DEPS.items():
        out.append({"name": tool, "package": pkg, "required": required, "why": why, "ok": ui.have(tool)})
    for mod, (pkg, required, why) in PY_DEPS.items():
        out.append({"name": f"python:{mod}", "package": pkg, "required": required, "why": why, "ok": _py_has(mod)})
    return out


def inspect(argv: list[str]) -> int:
    cfg = config.load()
    osr = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', Path("/etc/os-release").read_text(), re.M)) \
        if Path("/etc/os-release").exists() else {}
    lines = ["# VOID — system inspection", "", f"Generated {dt.datetime.now():%Y-%m-%d %H:%M} by `void inspect` (read-only).", ""]

    def row(k, v):
        print(f"  {k:<14} {v}")
        lines.append(f"| {k} | {v} |")

    ui.hdr("system (read-only — nothing is changed)")
    lines += ["| item | value |", "|---|---|"]
    row("OS", osr.get("PRETTY_NAME", platform.platform()))
    row("kernel", platform.release())
    row("session", f"{os.environ.get('XDG_SESSION_TYPE', '?')} / {os.environ.get('XDG_CURRENT_DESKTOP', '?')}")
    k = kde.detect()
    row("Plasma", k.get("plasmashell"))
    row("KWin", k.get("kwin_wayland"))
    if "color_scheme" in k:
        row("colour scheme", f"{k['color_scheme']['scheme']} (accent {k['color_scheme']['accent'] if isinstance(k['color_scheme']['accent'], str) else 'from scheme'})")
        row("Plasma style", k["plasma_style"])
        row("cursor", k["cursor"])
    elif k.get("error"):
        row("KDE config", k["error"])
    row("KDE tools", ", ".join(f"{t}{'' if v else ' (missing)'}" for t, v in k["tools"].items()))
    row("D-Bus tool", kde.dbus_tool() or "NONE — wallpapers and KWin reload will fail (install qt6-qttools)")
    try:
        dp = kde.kread("konsolerc", "Desktop Entry", "DefaultProfile")
        row("Konsole default", dp if isinstance(dp, str) else "(built-in)")
    except RuntimeError:
        pass
    kp = sorted(p.name for p in konsole.KONSOLE_DIR.glob("*.profile")) if konsole.KONSOLE_DIR.is_dir() else []
    row("Konsole profiles", ", ".join(kp) or "—")
    row("Alacritty", "installed" if ui.have("alacritty") else "not installed (optional)")

    ui.hdr("monitors")
    mon = monitors.detect(cfg)
    monitors.print_table(mon)
    if mon.get("target"):
        lines.append(f"| dashboard monitor | {mon['target']['name']} at {mon['target']['x']},{mon['target']['y']} |")

    ui.hdr("wallpaper pack")
    wd = Path(cfg["wallpaper"]["source_dir"]).expanduser()
    if wd.is_dir():
        imgs = [p for p in wd.rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
        row("folder", f"{wd} — {len(imgs)} image(s)")
    else:
        row("folder", f"{wd} — NOT FOUND (a procedural VOID wallpaper will be used)")

    ui.hdr("dependencies")
    for d in deps_report():
        print(f"  {'✓' if d['ok'] else '✗'} {d['name']:<16} {d['package']:<16} {'required' if d['required'] else 'optional'} — {d['why']}")
        lines.append(f"| dep {d['name']} | {'ok' if d['ok'] else 'missing'} ({d['package']}) |")

    ui.hdr("Crimson Desktop")
    cr = services.crimson_state(cfg)
    row("project", cr["project"] or "not found")
    if cr["project"]:
        rc, head = ui.run(["git", "-C", cr["project"], "log", "--oneline", "-1"])
        row("git HEAD", head if rc == 0 else "?")
        rc, dirty = ui.run(["git", "-C", cr["project"], "status", "--porcelain"])
        row("git status", "clean" if rc == 0 and not dirty else f"{len(dirty.splitlines())} uncommitted change(s) — VOID never touches them")
    for u, st in cr["units"].items():
        row(u, "not installed" if st is None else f"{'active' if st['active'] else 'inactive'}, {'enabled' if st['enabled'] else 'disabled'}")

    sp = spotify.inspect()
    for s in sp["spotify"]:
        lines.append(f"| Spotify | {s['method']} {s['version']} {s['path']} state={s['state']} writable={s['writable']} |")
    lines.append(f"| Spicetify | {sp['spicetify']['binary'] or 'not installed'} {sp['spicetify']['version']} |")

    ui.hdr("VOID")
    j = Journal()
    row("state", j.status)
    row("project", str(paths.PROJECT_DIR))
    lines += ["", "No credentials or account data were read. Only Spotify's `app.last-launched-version` prefs key is read."]
    out = paths.PROJECT_DIR / "docs" / "INSPECTION.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    ui.ok(f"report written to {files.short(out)} (not committed)")
    return 0


def install(argv: list[str]) -> int:
    if "--yes" in argv or "-y" in argv:
        ui.ASSUME_YES = True
    ui.hdr("VOID — install (user level)")
    missing = [d for d in deps_report() if not d["ok"]]
    if missing:
        pkgs = [d["package"] for d in missing]
        avail = []
        if ui.have("dnf"):
            for p in pkgs:
                rc, out = ui.run(["dnf", "-q", "repoquery", "--available", "--latest-limit", "1", p], timeout=120)
                if rc == 0 and out.strip():
                    avail.append(p)
                else:
                    ui.warn(f"{p}: not found in your enabled repositories — skipped")
        for d in missing:
            print(f"  missing: {d['package']:<16} {'required' if d['required'] else 'optional'} — {d['why']}")
        if avail:
            print(f"\n  sudo dnf install {' '.join(avail)}")
            print("  (official Fedora/Nobara repositories only; no COPR or third-party sources are added)")
            if ui.ask("run this command now?", False, privileged=True):
                if subprocess.run(["sudo", "dnf", "install", *avail]).returncode == 0:
                    man = paths.STATE_DIR / "installed-packages.txt"
                    man.parent.mkdir(parents=True, exist_ok=True)
                    with open(man, "a") as f:
                        f.write(f"{dt.datetime.now():%F %T} {' '.join(avail)}\n")
                    ui.ok("packages installed (listed in ~/.local/state/void-desktop/installed-packages.txt)")
                else:
                    ui.bad("dnf failed — VOID continues; the built-in fallbacks cover optional tools")
        req = [d for d in missing if d["required"] and not (ui.have(d["name"]) or _py_has(d["name"].split(":")[-1]))]
        if req:
            ui.bad("still missing required: " + ", ".join(d["package"] for d in req))
    else:
        ui.ok("all dependencies present")
    paths.ensure_dirs()
    cfgf = paths.CONFIG_FILE
    if not cfgf.exists():
        cfgf.write_text((paths.CONFIG_SRC / "void.toml").read_text())
        ui.ok(f"config: {files.short(cfgf)} (every key documented; defaults shown)")
    link = paths.HOME / ".local" / "bin" / "void"
    if not link.exists() and not link.is_symlink():
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(paths.PROJECT_DIR / "bin" / "void")
        ui.ok("command: ~/.local/bin/void")
    elif link.resolve() != (paths.PROJECT_DIR / "bin" / "void").resolve():
        ui.warn("~/.local/bin/void exists and points elsewhere — kept; use the project's bin/void")
    services.install_units()
    konsole.install()
    from ..dashboard import fetch
    fetch.config_file()
    ui.ok("installed: void-core user unit, Konsole profiles, fastfetch config — nothing is applied yet")
    print("\n  next:  void inspect   ·   void activate   (undo any time: void deactivate)")
    return 0


def health(argv: list[str]) -> int:
    problems, notes = [], []
    cfg = config.load()
    j = Journal()
    ui.hdr("VOID health")
    for d in deps_report():
        if not d["ok"] and d["required"]:
            problems.append(f"missing required dependency {d['package']}")
    if tokens.stale():
        problems.append("generated palettes are stale: void tokens build")
    rc, out = ui.run(["pgrep", "-fc", r"python[0-9.]* -m void\.core"])
    n_core = int(out) if rc == 0 and out.strip().isdigit() else 0
    r = client.request({"cmd": "status"}, timeout=2)
    if r:
        ui.ok(f"void-core answering ({r['clients']} client(s), profile {r['ui']['effective_performance']})")
    elif j.status == "active":
        problems.append("VOID is active but void-core is not running (void launch starts it)")
    if n_core > 1:
        problems.append(f"{n_core} void-core processes running (expected 1) — void stop, then void launch")
    st = session.status()
    if st["running"]:
        dead = [p["pane"] for p in st["panes"] if p["dead"]]
        ui.ok(f"dashboard: {len(st['panes'])} panes, {st['clients']} terminal(s) attached")
        if dead:
            problems.append(f"dead dashboard panes: {', '.join(dead)}")
        want = 4 if any(p["pane"] == "shell" for p in st["panes"]) else 5   # grid / music layout
        if len(st["panes"]) != want:
            problems.append(f"dashboard has {len(st['panes'])} panes, expected {want}")
    cr = services.crimson_state(cfg)
    if j.status == "active" and cr["running"]:
        problems.append("Crimson services are running while VOID is active (two Spotify watchers): void activate re-pauses them")
    if j.status == "active":
        try:
            cs = kde.ColorScheme().get("")
            if cs["scheme"] != kde.SCHEME:
                notes.append(f"colour scheme is {cs['scheme']} (changed after activation — VOID won't override it)")
        except RuntimeError as e:
            notes.append(str(e))
        sp = spotify.Spicetify().get("current_theme") if spotify.spicetify_bin() else None
        if sp and sp != spotify.THEME:
            notes.append(f"Spicetify theme is {sp}, not VOID (Spotify update or manual change? void spotify apply)")
    if j.status in ("failed", "activating", "deactivating"):
        problems.append(f"switch state is '{j.status}' ({j.state.get('error', 'interrupted')}) — run void deactivate (or void activate)")
    for n in notes:
        ui.info(n)
    for p in problems:
        ui.bad(p)
    if not problems:
        ui.ok(f"healthy (VOID {j.status})")
    return 1 if problems else 0
