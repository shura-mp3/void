"""The dashboard: a tmux session (own server, own config) with five panes.

    ┌──────────────────────┬────────────────────────────┐
    │ 01 GEASS / FASTFETCH │ 02 SYSTEM MONITOR (btop)   │
    ├──────────────────────┼────────────────────────────┤
    │ 03 DATA RAIN         │ 04 CLOCK                   │
    ├──────────────────────┴────────────────────────────┤
    │ 05 NOW PLAYING · SYNCED LYRICS · SPECTRUM          │
    └───────────────────────────────────────────────────┘

    void dashboard build | attach | respawn | fit | kill | status
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

from .. import config, paths, tokens

SERVER = "void-desktop"
SESSION = "void"
VOID_BIN = paths.PROJECT_DIR / "bin" / "void"
PANES = ["fetch", "sysmon", "rain", "clock", "music", "shell"]


def tmux(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", SERVER, *args], capture_output=True, text=True, check=check)


def conf_file() -> str:
    text = (paths.CONFIG_SRC / "tmux" / "void.tmux.conf").read_text().replace("VOID_BIN", str(VOID_BIN))
    text += "\n" + tokens.tmux_colors()
    dest = paths.GENERATED / "tmux.conf"
    paths.GENERATED.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.read_text() != text:
        dest.write_text(text)
    return str(dest)


def exists() -> bool:
    return shutil.which("tmux") is not None and tmux("has-session", "-t", SESSION).returncode == 0


def pane_cmd(name: str) -> str:
    return f"exec {VOID_BIN} pane {name}"


def build(cols: int = 210, rows: int = 56, layout: str | None = None) -> bool:
    """Create the session if it doesn't exist. Returns True if it was created."""
    if not shutil.which("tmux"):
        raise SystemExit("tmux is not installed (sudo dnf install tmux) — `void install` checks dependencies")
    if exists():
        return False
    layout = layout or config.load()["dashboard"].get("layout", "grid")
    env = ["-e", f"PYTHONPATH={paths.SRC_DIR}", "-e", "COLORTERM=truecolor", "-e", "VOID_DASHBOARD=1"]
    if layout == "grid":
        return _build_grid(cols, rows, env)
    tmux("-f", conf_file(), "new-session", "-d", "-s", SESSION, "-x", str(cols), "-y", str(rows), *env, pane_cmd("fetch"), check=True)
    top = f"{SESSION}:0.0"
    tmux("set-option", "-t", SESSION, "-p", "@void-pane", "fetch")
    # bottom: music (full width), then the middle row, then the two columns
    music = tmux("split-window", "-v", "-l", "35%", "-t", top, "-P", "-F", "#{pane_id}", *env, pane_cmd("music"), check=True).stdout.strip()
    rain = tmux("split-window", "-v", "-l", "35%", "-t", top, "-P", "-F", "#{pane_id}", *env, pane_cmd("rain"), check=True).stdout.strip()
    mon = tmux("split-window", "-h", "-l", "55%", "-t", top, "-P", "-F", "#{pane_id}", *env, pane_cmd("sysmon"), check=True).stdout.strip()
    clock = tmux("split-window", "-h", "-l", "55%", "-t", rain, "-P", "-F", "#{pane_id}", *env, pane_cmd("clock"), check=True).stdout.strip()
    for pid, name in ((music, "music"), (rain, "rain"), (mon, "sysmon"), (clock, "clock")):
        tmux("set-option", "-p", "-t", pid, "@void-pane", name)
    tmux("select-pane", "-t", music)  # keyboard goes to the music controls
    # re-fit whenever a terminal attaches or changes size (Konsole's real size is only known then)
    hook = f"run-shell -b '{VOID_BIN} dashboard fit'"
    tmux("set-hook", "-t", SESSION, "client-attached", hook)
    tmux("set-hook", "-t", SESSION, "client-resized", hook)
    fit()
    return True


def _build_grid(cols: int, rows: int, env: list[str]) -> bool:
    """2x2 tmux grid (the Konsole fallback of the Kitty grid dashboard)."""
    tmux("-f", conf_file(), "new-session", "-d", "-s", SESSION, "-x", str(cols), "-y", str(rows), *env, pane_cmd("shell"), check=True)
    top = f"{SESSION}:0.0"
    tmux("set-option", "-t", SESSION, "-p", "@void-pane", "shell")
    rain = tmux("split-window", "-v", "-l", "50%", "-t", top, "-P", "-F", "#{pane_id}", *env, pane_cmd("rain"), check=True).stdout.strip()
    mon = tmux("split-window", "-h", "-l", "50%", "-t", top, "-P", "-F", "#{pane_id}", *env, pane_cmd("sysmon"), check=True).stdout.strip()
    clock = tmux("split-window", "-h", "-l", "50%", "-t", rain, "-P", "-F", "#{pane_id}", *env, pane_cmd("clock"), check=True).stdout.strip()
    for pid, name in ((rain, "rain"), (mon, "sysmon"), (clock, "clock")):
        tmux("set-option", "-p", "-t", pid, "@void-pane", name)
    tmux("select-pane", "-t", top)
    return True


def _pane_ids() -> dict[str, str]:
    out = tmux("list-panes", "-s", "-t", SESSION, "-F", "#{@void-pane} #{pane_id}").stdout
    return dict(line.split(" ", 1) for line in out.splitlines() if " " in line)


def plan(cols: int, rows: int) -> dict[str, int]:
    """Absolute pane sizes for a window of cols x rows (borders take 1 cell each).

    btop refuses to draw below 80x24 and the Geass fetch needs ~95 columns, so those minimums
    win over proportions; the music pane keeps at least 14 rows (big lyrics need 17+).
    """
    music = max(14, round(rows * 0.33))
    upper = rows - music - 1                     # rows above the music pane (minus its border)
    top = max(min(24, upper - 8), round(upper * 0.68))
    left = max(min(95, cols - 81), round(cols * 0.45))
    return {"music_h": music, "top_h": top, "left_w": left}


def fit() -> None:
    if not exists() or "music" not in _pane_ids():
        return  # the grid layout keeps tmux's even 2x2 split
    size = tmux("display-message", "-p", "-t", SESSION, "#{window_width} #{window_height}").stdout.split()
    if len(size) != 2:
        return
    p = plan(int(size[0]), int(size[1]))
    ids = _pane_ids()
    if "music" in ids:
        tmux("resize-pane", "-t", ids["music"], "-y", str(p["music_h"]))
    if "fetch" in ids:
        tmux("resize-pane", "-t", ids["fetch"], "-y", str(p["top_h"]), "-x", str(p["left_w"]))
    if "rain" in ids:
        tmux("resize-pane", "-t", ids["rain"], "-x", str(p["left_w"]))


def respawn() -> None:
    """Restart every pane (e.g. after `void profile …`), keeping the layout."""
    out = tmux("list-panes", "-s", "-t", SESSION, "-F", "#{pane_id} #{@void-pane}").stdout
    for line in out.splitlines():
        pid, _, name = line.partition(" ")
        if name in PANES:
            tmux("respawn-pane", "-k", "-t", pid, pane_cmd(name))


def kill() -> bool:
    if not shutil.which("tmux"):
        return False
    return tmux("kill-server").returncode == 0


def attach() -> int:
    build()
    os.execvp("tmux", ["tmux", "-L", SERVER, "attach-session", "-t", SESSION])
    return 0  # not reached


def status() -> dict:
    if not exists():
        return {"running": False, "panes": []}
    out = tmux("list-panes", "-s", "-t", SESSION, "-F",
               "#{@void-pane} #{pane_pid} #{pane_current_command} #{pane_width}x#{pane_height} #{pane_dead}").stdout
    panes = []
    for line in out.splitlines():
        name, pid, cmd, size, dead = line.split(" ")
        panes.append({"pane": name, "pid": int(pid), "command": cmd, "size": size, "dead": dead == "1"})
    clients = tmux("list-clients", "-t", SESSION, "-F", "#{client_tty}").stdout.split()
    return {"running": True, "panes": panes, "clients": len(clients)}


# ════════════════════════════════════════════════════════════════════ pane supervisor
def resolve(name: str, cfg: dict) -> list[str]:
    """The command a pane runs, honouring config choices and what is installed."""
    d = cfg["dashboard"]
    py = [sys.executable, "-m", "void.cli"]
    if name == "sysmon":
        want = d.get("system_monitor", "auto")
        if want in ("auto", "btop") and shutil.which("btop"):
            return ["btop"]
        return py + ["sysmon"]
    if name == "shell":
        # a real interactive shell that opens with the Geass fastfetch (the reference's top-left tile)
        return [str(paths.PROJECT_DIR / "bin" / "void-shell")]
    if name == "clock" and d.get("clock") == "tty-clock" and shutil.which("tty-clock"):
        secs = config.profile(config.current_profile(cfg))["clock_seconds"]
        return ["tty-clock", "-c", "-C", "7", "-D"] + (["-s"] if secs else [])
    prof = config.profile(config.current_profile(cfg))
    if name == "rain" and d.get("rain") in ("auto", "cmatrix") and shutil.which("cmatrix") and prof["rain_fps"]:
        # white cmatrix, as in the reference; the minimal profile uses VOID's static rain instead
        return ["cmatrix", "-b", "-C", "white", "-u", str(max(1, min(10, 12 - prof["rain_fps"] // 2)))]
    if name == "rain" and d.get("layout", "grid") == "grid":
        return py + ["rain", "--dense"]
    if name == "fetch":
        return py + ["fetch", "--pane"]
    return py + [name]


def btop_env(cfg: dict) -> dict:
    """btop gets its own XDG_CONFIG_HOME, so your ~/.config/btop stays untouched."""
    root = paths.GENERATED / "btop-xdg"
    (root / "btop" / "themes").mkdir(parents=True, exist_ok=True)
    (root / "btop" / "themes" / "void.theme").write_text(tokens.btop_theme())
    ms = config.profile(config.current_profile(cfg))["btop_ms"]
    (root / "btop" / "btop.conf").write_text("\n".join([
        "# Generated by VOID for the dashboard pane (rewritten on every start).",
        'color_theme = "void"', "theme_background = True", "truecolor = True", "rounded_corners = False",
        'graph_symbol = "braille"',
        f'shown_boxes = "{"cpu proc" if cfg["dashboard"].get("layout", "grid") == "grid" else "cpu mem proc"}"',
        f"update_ms = {ms}",
        'proc_sorting = "cpu lazy"', "proc_gradient = False", "proc_tree = False", "check_temp = True",
        "show_battery = False", "background_update = True", "vim_keys = False", ""]))
    return dict(os.environ, XDG_CONFIG_HOME=str(root))


def run_pane(name: str) -> int:
    """Run a pane program forever: if it exits or crashes it restarts after a short pause."""
    from .term import RESET, fg
    if name not in PANES:
        print(f"unknown pane {name!r} (one of {', '.join(PANES)})", file=sys.stderr)
        return 2
    fails = 0
    while True:
        cfg = config.load()
        cmd = resolve(name, cfg)
        env = btop_env(cfg) if cmd[0] == "btop" else dict(os.environ, PYTHONPATH=str(paths.SRC_DIR))
        if name == "shell":
            env.pop("VOID_FETCHED", None)
            env["VOID_DASHBOARD_FETCH"] = "1"
        t0 = time.monotonic()
        try:
            rc = subprocess.run(cmd, env=env).returncode
        except KeyboardInterrupt:
            rc = 130
        except OSError as e:
            rc = 127
            print(f"cannot start {cmd[0]}: {e}")
        fails = fails + 1 if time.monotonic() - t0 < 5 else 0
        wait = min(30, 2 * (fails + 1))
        sys.stdout.write(f"\x1b[0m\x1b[2J\x1b[H{fg('muted')}{name.upper()} exited ({rc}) — restarting in {wait}s"
                         f"  ·  Ctrl+C here to stop this pane{RESET}\n")
        sys.stdout.flush()
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            return 0


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    if cmd == "build":
        print("created" if build() else "already running")
    elif cmd == "attach":
        return attach()
    elif cmd == "respawn":
        respawn()
    elif cmd == "fit":
        fit()
    elif cmd == "kill":
        print("stopped" if kill() else "not running")
    elif cmd == "status":
        st = status()
        if not st["running"]:
            print("dashboard session: not running")
            return 1
        print(f"dashboard session: running, {st['clients']} attached terminal(s)")
        for p in st["panes"]:
            print(f"  {p['pane']:7} {p['command']:12} {p['size']:>9}  pid {p['pid']}{'  DEAD' if p['dead'] else ''}")
    else:
        print(__doc__)
        return 2
    return 0
