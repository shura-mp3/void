"""VOID ⇄ previous desktop (e.g. Crimson): activate, deactivate, restore, launch, stop, profile.

  void activate     [--yes] [--no-launch] [--no-spotify] [--no-wallpaper]
  void deactivate   [--yes] [--force]      back to exactly what was there before `activate`
  void restore      [--yes] [--uninstall] [--files] [--list]
                    back to the desktop as it was before VOID was EVER activated
  void launch       [--autostart]          open the dashboard on the right-hand monitor
  void stop                                close dashboard + void-core
  void profile      minimal | balanced | showcase
  void autostart    on | off | status
  void status

Every setting change goes through the journal (see journal.py): recorded before it is made,
idempotent when repeated, and undoable after a partial failure.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tarfile
import time
from pathlib import Path

from .. import client, config, paths, tokens
from ..dashboard import session
from . import files, kde, kitty, konsole, monitors, services, shortcuts, spotify, ui, wallpaper
from .journal import ABSENT, HANDLERS, Journal, show

DASH_PID = paths.STATE_DIR / "dashboard-window.pid"
AUTOSTART = paths.XDG_CONFIG / "autostart" / "void-dashboard.desktop"
BACKUPS = paths.STATE_DIR / "backups"
# whole config files archived before every activation (last-resort safety net; `void restore --files`)
CONFIG_FILES = [
    ".config/kdeglobals", ".config/kwinrc", ".config/kwinrulesrc", ".config/breezerc", ".config/plasmarc",
    ".config/kcminputrc", ".config/kscreenlockerrc", ".config/konsolerc", ".config/kitty/kitty.conf",
    ".config/kglobalshortcutsrc",
    ".config/plasma-org.kde.plasma.desktop-appletsrc", ".config/spicetify/config-xpui.ini",
    ".config/autostart",
]


def reporter():
    def report(outcome: str, e: dict, current, target) -> None:
        what = HANDLERS[e["kind"]].describe(e["key"]) if e["kind"] in HANDLERS else f"{e['kind']} {e['key']}"
        if outcome == "restored":
            ui.ok(f"{what} → {show(target)}")
        elif outcome == "same":
            ui.info(f"{what} already {show(target)}")
        elif outcome == "kept":
            ui.warn(f"{what}: kept your newer value {show(current)} (VOID set {show(e.get('applied'))}; --force reverts it)")
        elif outcome == "failed":
            ui.bad(f"{what}: {current}")
        else:
            ui.bad(f"{what}: unknown setting kind")
    return report


def archive_configs(label: str) -> Path:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    dest = BACKUPS / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}.tar.gz"
    present = [p for p in CONFIG_FILES if (paths.HOME / p).exists()]
    with tarfile.open(dest, "w:gz") as tf:
        for p in present:
            tf.add(paths.HOME / p, arcname=p)
    (dest.with_suffix("").with_suffix(".json")).write_text(
        json.dumps({"created": time.strftime("%F %T"), "label": label, "home": str(paths.HOME),
                                  "existed": present, "absent": [p for p in CONFIG_FILES if p not in present]}, indent=2))
    for old in sorted(BACKUPS.glob("*-activate.tar.gz"))[:-10]:  # keep the last 10 activation archives
        old.unlink()
        old.with_suffix("").with_suffix(".json").unlink(missing_ok=True)
    return dest


def write_shell_env(cfg: dict) -> None:
    env = paths.GENERATED / "shell.env"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text(f"VOID_STARTUP_FETCH={1 if cfg['konsole'].get('startup_fetch', True) else 0}\nexport VOID_STARTUP_FETCH\n")


# ════════════════════════════════════════════════════════════════════ activate
def activate(argv: list[str]) -> int:
    opts = set(argv)
    if "--yes" in opts or "-y" in opts:
        ui.ASSUME_YES = True
    cfg = config.load()
    j = Journal().lock()
    ui.hdr("VOID — activate")
    try:
        kde.kwrite_bin()
    except RuntimeError as e:
        ui.bad(str(e))
        return 1
    crim = services.crimson_state(cfg)
    mon = monitors.detect(cfg)
    target = mon.get("target")
    print(f"  current state : {j.status}{'  (re-applying — safe, nothing is recorded twice)' if j.status == 'active' else ''}")
    print(f"  dashboard on  : {target['name'] + ' at ' + str(target['x']) + ',' + str(target['y']) if target else 'no monitor detected'}")
    print(f"  Crimson       : {'project found' if crim['project'] else 'project not found'}"
          f"{', services running (will be paused, then restored on deactivate)' if crim['running'] else ''}")
    print("  will apply    : VOID Monochrome colours (global — both monitors), Breeze style + window decoration,")
    print("                  wallpapers on both monitors + lock screen, dashboard window rule, Konsole + Kitty,")
    print(f"                  void-core{', VOID Spotify theme' if cfg['spicetify'].get('enabled', True) and '--no-spotify' not in opts else ''}")
    print("  undo          : void deactivate   (or: void restore — to before VOID was ever used)")
    if not ui.ask("activate VOID now?", True):
        return 0

    first = not j.original()
    arc = archive_configs("activate")
    ui.ok(f"config archive: {files.short(arc)}" + ("  (first activation: your original desktop)" if first else ""))
    j.set_status("activating", archive=str(arc), **({"original_archive": str(arc)} if first else {}))
    spotify_outcome = "not attempted"
    try:
        ui.hdr("Crimson")
        for unit in services.CRIMSON_UNITS:
            if cfg["crimson"].get("pause_services", True) and services.unit_exists(unit):
                st = HANDLERS["service"].get(unit)
                if st["active"] or st["enabled"]:
                    j.change("service", unit, {"active": False, "enabled": False}, "paused while VOID is active")
                    ui.ok(f"paused {unit} (restored on deactivate)")
        if not crim["running"]:
            ui.info("no Crimson services running")

        ui.hdr("KDE Plasma")
        kde.install_files()
        k = cfg["kde"]
        if k.get("color_scheme", True):
            j.change("colorscheme", "global", {"scheme": kde.SCHEME, "accent": ABSENT, "accent_from_wallpaper": "false"},
                     "VOID Monochrome colour scheme")
            ui.ok("colour scheme: VOID Monochrome (accent from the scheme, not from the wallpaper)")
        if k.get("plasma_style", True):
            j.change("desktoptheme", "plasma", "default", "Breeze Plasma style follows VOID colours")
            ui.ok("Plasma style: Breeze (panels, task manager, launcher, tray, notifications take VOID's colours)")
        if k.get("window_decoration", True):
            for f, g, key, v in kde.decoration_settings():
                j.change("kconfig", kde.kkey(f, g, key), v, "window decoration")
            ui.ok("window decoration: Breeze, hairline borders, neutral shadows, restrained animations")
        cursor = kde.monochrome_cursor() if k.get("cursor", "auto") == "auto" else (k.get("cursor") or None)
        if cursor:
            j.change("cursortheme", "cursor", cursor, "monochrome cursor")
            ui.ok(f"cursor: {cursor}")
        font = kde.mono_font()
        if font:
            j.change("kconfig", kde.kkey("kdeglobals", "General", "fixed"), f"{font},10,-1,5,400,0,0,0,0,0,0,0,0,0,0,1",
                     "monospace font")
            ui.ok(f"fixed-width font: {font}")

        ui.hdr("monitor & wallpaper")
        monitors.save(mon)
        monitors.print_table(mon)
        if target and k.get("wallpaper", True) and "--no-wallpaper" not in opts:
            if kde.plasma_running():
                outs = [o for o in mon["outputs"] if o["enabled"]]
                res = wallpaper.prepare(cfg, outs, target)
                if res:
                    for name, v in res["screens"].items():
                        role = "right / dashboard" if name == target["name"] else "left"
                        j.change("wallpaper", f"{v['x']},{v['y']}", wallpaper.plasma_value(v["image"]),
                                 f"{role} monitor wallpaper ({name})")
                    problems = wallpaper.verify(res)
                    if problems:
                        raise RuntimeError("wallpaper not applied as expected: " + "; ".join(problems))
                    ui.ok(f"wallpapers applied and read back from Plasma on {len(res['screens'])} monitor(s) "
                          f"({res['mode']}): " + ", ".join(res["screens"]))
                    if k.get("lockscreen", True):
                        for f, g, key, v in kde.lockscreen_settings(res["lock"]):
                            j.change("kconfig", kde.kkey(f, g, key), v, "lock screen")
                        ui.ok("lock screen: monochrome wallpaper")
            else:
                ui.warn("plasmashell is not running — wallpaper skipped (run `void activate` again inside Plasma)")
        if target and k.get("dashboard_window_rule", True):
            for f, g, key, v in kde.dashboard_rule(target):
                j.change("kconfig", kde.kkey(f, g, key), v, "dashboard window rule")
            rules, count = kde.rules_list_with(kde.RULE_ID)
            j.change("kconfig", kde.kkey("kwinrulesrc", "General", "rules"), rules, "dashboard window rule")
            j.change("kconfig", kde.kkey("kwinrulesrc", "General", "count"), count, "dashboard window rule")
            ui.ok(f"KWin rule: dashboard window → {target['name']} ({target['logical_width']}x{target['logical_height']}), "
                  "below other windows, no border")

        ui.hdr("Konsole")
        konsole.install()
        write_shell_env(cfg)
        if cfg["konsole"].get("set_default_profile", True):
            j.change("kconfig", konsole.default_profile_key(), konsole.PROFILE, "Konsole default profile")
            ui.ok("new Konsole windows open the VOID profile (your other profiles are unchanged)")
        if cfg["kitty"].get("enabled", True) and kitty.wanted():
            ui.hdr("Kitty")
            kitty.install()
            j.change("kitty", str(kitty.CONF), True, "VOID Kitty theme")
            kitty.reload()
            ui.ok("Kitty: VOID theme included last in kitty.conf (Crimson's include stays; VOID's wins), "
                  "VOID shell layer, Ctrl+Shift+L → void music")

        if cfg["kde"].get("shortcuts", True):
            ui.hdr("global shortcuts")
            freed = shortcuts.apply(j)
            if freed:
                ui.ok("Crimson's keys set aside while VOID is active: " + ", ".join(freed))
            ui.ok("Meta+Alt+D dashboard · Meta+Alt+L lyrics (Kitty) · Meta+Alt+P profile · Meta+Alt+[ / ] lyric timing")
            ui.info("global shortcuts switch over completely after your next login (KDE reads them at login)")

        ui.hdr("void-core")
        services.install_units()
        if ui.have("systemctl") and services.unit_exists("void-core.service"):
            j.change("service", "void-core.service", {"active": True, "enabled": False}, "VOID backend")
        else:
            client.start_core()
        ui.ok("void-core running (Spotify MPRIS, lyrics, spectrum)")

        if "--no-spotify" not in opts:
            ui.hdr("Spotify")
            spotify_outcome = spotify.apply(j, cfg)
            ui.info(f"Spotify: {spotify_outcome}")
        kde.kwin_reconfigure()
    except (Exception, KeyboardInterrupt) as e:  # noqa: BLE001 - the journal knows exactly what to undo
        j.set_status("failed", error=f"{type(e).__name__}: {e}")
        ui.bad(f"activation stopped: {e}")
        ui.info("everything applied so far is journaled.  undo it: void deactivate   ·   try again: void activate")
        return 1
    j.set_status("active", spotify=spotify_outcome, monitor=(target or {}).get("name"))
    ui.hdr("VOID active")
    if "--no-launch" not in opts:
        launch([])
    print("  Konsole: open a new window (Ctrl+Alt+T) for the VOID profile · dashboard: void launch · undo: void deactivate")
    return 0


# ════════════════════════════════════════════════════════════════════ deactivate / restore
def deactivate(argv: list[str]) -> int:
    opts = set(argv)
    if "--yes" in opts or "-y" in opts:
        ui.ASSUME_YES = True
    j = Journal().lock()
    entries = j.entries()
    if not entries:
        ui.say(f"VOID is not active (state: {j.status}) — nothing to undo")
        if j.status != "inactive":
            j.set_status("inactive")
        return 0
    ui.hdr("VOID — deactivate")
    print(f"  state {j.status}: {len(entries)} recorded change(s) will be undone, newest first")
    if not ui.ask("deactivate VOID?", True):
        return 0
    j.set_status("deactivating")
    stop([])
    had_spotify = any(e["kind"] == "spicetify" for e in entries)
    unpatched = spotify.before_revert() if had_spotify else None
    fails = j.revert_session(force="--force" in opts, report=reporter())
    if had_spotify:
        ui.info("Spotify: " + (unpatched or spotify.after_revert()))
    kde.kwin_reconfigure()
    kitty.reload()
    if fails:
        j.set_status("failed", error=f"{fails} setting(s) could not be restored")
        ui.bad(f"{fails} setting(s) could not be restored — fix the cause above, then run `void deactivate` again")
        return 1
    j.set_status("inactive")
    ui.hdr("VOID inactive")
    print("  your previous desktop is back (Crimson services restarted if they were running before).")
    return 0


def restore(argv: list[str]) -> int:
    opts = set(argv)
    if "--yes" in opts or "-y" in opts:
        ui.ASSUME_YES = True
    if "--list" in opts:
        for p in sorted(BACKUPS.glob("*.tar.gz")):
            print(f"  {p.name}")
        return 0
    j = Journal()
    if j.entries():
        rc = deactivate([a for a in argv if a in ("--yes", "-y")])
        if rc:
            return rc
    j.lock()
    orig = j.original()
    ui.hdr("VOID — restore the pre-VOID desktop")
    if orig:
        print(f"  {len(orig)} setting(s) go back to their values from before VOID was first activated:")
        for e in orig:
            h = HANDLERS.get(e["kind"])
            print(f"    {h.describe(e['key']) if h else e['key']}: {show(e['value'])}")
        ui.warn("this also reverts settings that another theme (e.g. Crimson) changed after VOID's first activation")
        if ui.ask("restore these?", True):
            fails = j.restore_original(force=True, report=reporter())
            if fails:
                ui.bad(f"{fails} setting(s) failed — see above")
                return 1
            if any(e["kind"] == "spicetify" for e in orig) and spotify.spicetify_bin():
                # Spicetify's settings are back to pre-VOID; re-apply them so Spotify shows that look
                exe = spotify.spicetify_bin()
                if spotify.Spicetify().get("current_theme") not in (ABSENT, ""):
                    if not spotify.running_spotify() or ui.ask("re-apply that Spotify look now (restarts Spotify)?", True):
                        rc = spotify._spice(exe, "apply")
                        ui.info("Spotify: " + ("pre-VOID theme re-applied" if rc == 0 else "`spicetify apply` failed — run it by hand"))
            kde.kwin_reconfigure()
    else:
        ui.info("no recorded original values — nothing to restore (VOID was never activated, or already restored)")
    if "--files" in opts:
        st = j.state
        arc = Path(st.get("original_archive") or "")
        if not arc.exists():
            ui.bad("no original config archive recorded")
            return 1
        ui.warn(f"--files extracts whole config files from {files.short(arc)} over the current ones.")
        ui.warn("Any change made since then to those files is lost. Log out and back in afterwards.")
        if ui.ask("extract it?", False):
            with tarfile.open(arc) as tf:
                tf.extractall(paths.HOME, filter="data")
            ui.ok("config files restored from the archive — log out and back in")
    if "--uninstall" in opts:
        ui.hdr("uninstall VOID's installed files")
        autostart(["off"])
        session.kill()
        if spotify.Spicetify().get("current_theme") != spotify.THEME:
            spotify.remove_theme_files()
        for f in files.uninstall_all():
            ui.ok(f"removed {files.short(f)}")
        services.systemctl("daemon-reload")
        ui.info("the project folder, your config.toml, caches and backups are kept; delete them by hand if wanted")
    return 0


# ════════════════════════════════════════════════════════════════════ dashboard window
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
    except OSError:
        return True
    return any(t in cmd for t in ("konsole", "kitty", "alacritty"))


def dashboard_window_pid() -> int | None:
    try:
        pid = int(DASH_PID.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if _pid_alive(pid) else None


def ensure_core() -> None:
    if client.request({"cmd": "ping"}, timeout=1):
        return
    if services.unit_exists("void-core.service"):
        services.systemctl("start", "void-core.service")
    else:
        client.start_core()


def launch(argv: list[str], cfg: dict | None = None) -> int:
    cfg = cfg or config.load()
    if "--autostart" in argv:
        if Journal().status != "active":
            return 0  # VOID not active: the login autostart does nothing
        for _ in range(60):  # wait for Plasma to bring up the session
            if kde.plasma_running():
                break
            time.sleep(1)
        time.sleep(3)
    ensure_core()
    session.build()
    pid = dashboard_window_pid()
    if pid:
        ui.ok(f"dashboard already open (pid {pid}) — not starting a second one")
        return 0
    term = cfg["dashboard"].get("terminal", "auto")
    if Journal().status != "active":
        ui.info("VOID is not active: the dashboard opens as a normal window (activate for right-monitor placement)")
    konsole.install()
    if term in ("auto", "konsole") and ui.have("konsole"):
        cmd = ["konsole", "--separate", "--hide-menubar", "--hide-tabbar", "--profile", "VOID Dashboard"]
    elif term in ("auto", "kitty") and ui.have("kitty"):
        t = tokens.load()["terminal"]
        kitty.install()
        confs = (["--config", str(kitty.CONF)] if kitty.CONF.exists() else []) + ["--config", str(kitty.THEME)]
        cmd = ["kitty", *confs, "--class", "void-dashboard", "--title", kde.DASH_TITLE,
               "-o", f"font_size={t['dashboard_font_size']}", "-o", "hide_window_decorations=yes",
               "-o", "tab_bar_min_tabs=99", "-o", "window_padding_width=2",
               str(paths.PROJECT_DIR / "bin" / "void"), "dashboard", "attach"]
    elif term in ("auto", "alacritty") and ui.have("alacritty"):
        cmd = ["alacritty", "--config-file", konsole.alacritty_dashboard_config(), "--class", "void-dashboard",
               "-e", str(paths.PROJECT_DIR / "bin" / "void"), "dashboard", "attach"]
    else:
        ui.warn("no supported terminal (Konsole / Kitty / Alacritty) found — attach by hand:  tmux -L void-desktop attach -t void")
        return 1
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    DASH_PID.parent.mkdir(parents=True, exist_ok=True)
    DASH_PID.write_text(str(p.pid))
    ui.ok(f"dashboard opened ({cmd[0]}, pid {p.pid})")
    return 0


def stop(argv: list[str]) -> int:
    pid = dashboard_window_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        ui.ok("dashboard window closed")
    DASH_PID.unlink(missing_ok=True)
    if session.kill():
        ui.ok("dashboard panes stopped")
    if services.unit_exists("void-core.service") and HANDLERS["service"].get("void-core.service")["active"]:
        services.systemctl("stop", "void-core.service")
        ui.ok("void-core stopped")
    rc, out = ui.run(["pgrep", "-f", r"python[0-9.]* -m void\.core"])
    for pid_s in out.split() if rc == 0 else []:
        os.kill(int(pid_s), signal.SIGTERM)
        ui.ok(f"void-core (pid {pid_s}) stopped")
    return 0


# ════════════════════════════════════════════════════════════════════ profile / autostart / status
def toggle(argv: list[str]) -> int:
    """Show/hide the dashboard window (Meta+Alt+D). The panes and void-core keep running when hidden."""
    pid = dashboard_window_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        DASH_PID.unlink(missing_ok=True)
        ui.ok("dashboard hidden (void-core keeps running)")
        return 0
    return launch([])


def offset(argv: list[str]) -> int:
    """Lyric timing for the current track: void offset +100 | -100 | reset"""
    arg = argv[0] if argv else ""
    msg = {"cmd": "offset", "reset": True} if arg == "reset" else None
    if msg is None:
        try:
            msg = {"cmd": "offset", "delta": int(arg)}
        except ValueError:
            print("usage: void offset +100 | -100 | reset")
            return 2
    r = client.request(msg, timeout=2)
    if not r or not r.get("ok"):
        ui.bad("no track playing, or void-core is not running")
        return 1
    ui.ok(f"lyric offset for this track: {r['offset_ms']:+d} ms")
    return 0


def profile(argv: list[str]) -> int:
    name = argv[0] if argv else ""
    if name == "next":
        order = list(config.PERFORMANCE)
        name = order[(order.index(config.current_profile()) + 1) % len(order)]
    if name not in config.PERFORMANCE:
        print(f"current profile: {config.current_profile()}  (choose: {' | '.join(config.PERFORMANCE)})")
        return 0 if not name else 2
    r = client.request({"cmd": "ui", "performance": name}, timeout=2)
    if not r:
        st = config.JsonState(paths.UI_STATE_FILE)
        st.data["performance"] = name
        st.save()
    if session.exists():
        session.respawn()
    if kitty.PROFILE.exists():
        kitty.write_profile(name)
        kitty.reload()
    ui.ok(f"profile: {name}  ({', '.join(f'{k}={v}' for k, v in config.PERFORMANCE[name].items())})")
    return 0


def autostart(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    if cmd == "on":
        files.install(AUTOSTART, "\n".join([
            "[Desktop Entry]", "Type=Application", "Name=VOID dashboard",
            "Comment=Opens the VOID dashboard on the right-hand monitor at login (only while VOID is active)",
            f"Exec={paths.PROJECT_DIR / 'bin' / 'void'} launch --autostart", "X-KDE-AutostartScript=false",
            "NoDisplay=true", ""]))
        ui.ok("autostart on — the dashboard opens at login while VOID is active (void autostart off to stop)")
    elif cmd == "off":
        if AUTOSTART.exists() and files.is_ours(AUTOSTART):
            AUTOSTART.unlink()
            ui.ok("autostart off")
        elif AUTOSTART.exists():
            ui.warn(f"{files.short(AUTOSTART)} was edited — remove it by hand")
        else:
            ui.info("autostart already off")
    else:
        print(f"autostart: {'on' if AUTOSTART.exists() else 'off'}")
    return 0


def status(argv: list[str]) -> int:
    j = Journal()
    st = j.state
    print(f"VOID       {st.get('status', 'inactive')}{'  since ' + st['since'] if st.get('since') else ''}")
    if st.get("error"):
        print(f"           last error: {st['error']}")
    print(f"journal    {len(j.entries())} change(s) this activation · {len(j.original())} original value(s) on record")
    r = client.request({"cmd": "status"}, timeout=1)
    if r:
        tr = (r.get("player") or {}).get("track") or {}
        print(f"void-core  running · {r['ui']['effective_performance']} · player {'—' if not tr.get('title') else tr['title'] + ' — ' + tr.get('artist', '')}"
              f" · lyrics {r.get('lyrics_status')}")
    else:
        print("void-core  not running")
    d = session.status()
    print(f"dashboard  {'running, ' + str(len(d['panes'])) + ' panes' if d['running'] else 'not running'}"
          f"{' · window pid ' + str(dashboard_window_pid()) if dashboard_window_pid() else ''}")
    print(f"profile    {config.current_profile()}   autostart {'on' if AUTOSTART.exists() else 'off'}")
    if st.get("spotify"):
        print(f"spotify    {st['spotify']}")
    return 0

