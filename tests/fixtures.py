"""Sandbox homes for the switching tests: a Crimson-styled desktop, or a stock one.

Everything lives in a temporary $HOME; KDE tools, systemctl, Konsole and Spicetify are test
doubles from tests/stubs (Plasma scripting runs VOID's real JavaScript in node).
"""

from __future__ import annotations

import configparser
import json
import os
import subprocess
from pathlib import Path

from _env import ROOT, TESTS, sandbox_env

STUBS = TESTS / "stubs"
SPOTIFY_REL = ".local/share/spotify-launcher/install/usr/share/spotify"


def env_for(home: Path, **extra) -> dict:
    env = sandbox_env(home)
    env["PATH"] = f"{STUBS}:{env['PATH']}"
    env["VOID_YES"] = "1"
    env.pop("WAYLAND_DISPLAY", None)
    env.update(extra)
    return env


def void(home: Path, *args: str, **extra) -> subprocess.CompletedProcess:
    return subprocess.run([str(ROOT / "bin" / "void"), *args], env=env_for(home, **extra), capture_output=True,
                          text=True, timeout=120, stdin=subprocess.DEVNULL)


def kfile(home: Path, name: str) -> Path:
    return home / ".config" / name


def write_ini(path: Path, groups: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"[{g}]\n" + "".join(f"{k}={v}\n" for k, v in kv.items()) for g, kv in groups.items()))


def read_ini(path: Path) -> dict[str, dict[str, str]]:
    """KDE INI as {group: {key: value}}, empty groups dropped (they carry no settings)."""
    out: dict[str, dict[str, str]] = {}
    cur = None
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if line.startswith("["):
            cur = line.strip()
            out.setdefault(cur, {})
        elif "=" in line and cur:
            k, v = line.split("=", 1)
            out[cur][k] = v
    return {g: kv for g, kv in out.items() if kv}


def spicetify_ini(home: Path) -> dict:
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(home / ".config/spicetify/config-xpui.ini")
    return {s: dict(cp[s]) for s in cp.sections()}


def _spotify_install(home: Path, patched: bool) -> Path:
    sp = home / SPOTIFY_REL
    (sp / "Apps").mkdir(parents=True)
    (sp / "spotify").write_text("#!/bin/sh\n")
    for n in ("xpui.spa", "login.spa"):
        data = f"ORIGINAL {n}\n".encode() * 50
        backup = home / ".local/state/spicetify/Backup"
        if patched:
            backup.mkdir(parents=True, exist_ok=True)
            (backup / n).write_bytes(data)
        else:
            (sp / "Apps" / n).write_bytes(data)
    prefs = home / ".config/spotify/prefs"
    prefs.parent.mkdir(parents=True, exist_ok=True)
    prefs.write_text('app.last-launched-version="1.2.93.1"\nautologin.username="NOT-READ"\n')
    return sp


def desktops(home: Path, left_img: str, right_img: str) -> None:
    state = {
        "screens": [{"x": 0, "y": 0, "width": 2560, "height": 1440}, {"x": 2560, "y": 0, "width": 1920, "height": 1080}],
        "desktops": [
            {"screen": 0, "plugin": "org.kde.image", "config": {"Wallpaper/org.kde.image/General": {"Image": left_img, "FillMode": "2"}}},
            {"screen": 1, "plugin": "org.kde.image", "config": {"Wallpaper/org.kde.image/General": {"Image": right_img, "FillMode": "2"}}},
        ],
    }
    (home / "plasma-desktops.json").write_text(json.dumps(state, indent=1))


def crimson_home(home: Path) -> None:
    """A desktop with Crimson Desktop fully active (theme, services, Konsole, Spotify)."""
    write_ini(kfile(home, "kdeglobals"), {"General": {"ColorScheme": "CrimsonNight", "AccentColor": "141,36,69"},
                                          "KDE": {"AnimationDurationFactor": "0.7", "LookAndFeelPackage": "org.kde.breezedark.desktop"},
                                          "Icons": {"Theme": "Papirus-Dark"}})
    write_ini(kfile(home, "plasmarc"), {"Theme": {"name": "default"}})
    write_ini(kfile(home, "kcminputrc"), {"Mouse": {"cursorTheme": "Bibata-Original-Classic"}})
    write_ini(kfile(home, "kwinrc"), {"org.kde.kdecoration2": {"library": "org.kde.breeze", "theme": "Breeze", "BorderSize": "Tiny"},
                                      "Plugins": {"blurEnabled": "true"}})
    write_ini(kfile(home, "breezerc"), {"Common": {"ShadowColor": "60,8,24", "ShadowSize": "ShadowLarge"}})
    write_ini(kfile(home, "kwinrulesrc"), {"General": {"count": "1", "rules": "8d244560-c71b-4a1e-9f2b-0b080dc7a110"},
                                           "8d244560-c71b-4a1e-9f2b-0b080dc7a110": {"Description": "Crimson Dashboard", "wmclass": "crimson-dashboard"}})
    write_ini(kfile(home, "konsolerc"), {"Desktop Entry": {"DefaultProfile": "Crimson OS.profile"}, "MainWindow": {"MenuBar": "Disabled"}})
    # Crimson's global shortcuts as its apply-theme.sh writes them
    write_ini(kfile(home, "kglobalshortcutsrc"), {
        "kwin": {"Overview": "Meta+W,Meta+W,Toggle Overview"},
        "services][crimson-dashboard-toggle.desktop": {"_launch": "Meta+Alt+D"},
        "services][crimson-lyrics.desktop": {"_launch": "Meta+Alt+L"},
        "services][crimson-profile-cycle.desktop": {"_launch": "Meta+Alt+P"},
        "services][crimson-offset-plus.desktop": {"_launch": "Meta+Alt+]"},
        "services][crimson-offset-minus.desktop": {"_launch": "Meta+Alt+["}})
    write_ini(kfile(home, "kscreenlockerrc"), {"Greeter": {"WallpaperPlugin": "org.kde.image"},
                                               "Greeter][Wallpaper][org.kde.image][General": {"Image": "file:///crimson/lock.jpg"}})
    desktops(home, "file:///crimson/left.jpg", "file:///crimson/right.jpg")
    kd = home / ".config/kitty"
    kd.mkdir(parents=True)
    (kd / "kitty.conf").write_text("font_size 12\nmap ctrl+shift+e no_op\n\n"
                                   "# Crimson Desktop theme (remove this line to disable)\ninclude crimson.conf\n")
    (kd / "crimson.conf").write_text("background #0B080D\nmap ctrl+shift+l launch crimson-lyrics\n")
    (home / "systemd-state.json").write_text(json.dumps({
        "crimson-core.service": {"active": True, "enabled": True},
        "crimson-dashboard.service": {"active": True, "enabled": True}}))
    sp = _spotify_install(home, patched=True)
    cfg = home / ".config/spicetify"
    for d in ("Themes/Crimson", "CustomApps/crimson"):
        (cfg / d).mkdir(parents=True)
        (cfg / d / ".crimson-desktop").write_text("crimson")
    (cfg / "Themes/Crimson/user.css").write_text("/* Crimson Spotify */")
    (cfg / "Themes/Crimson/theme.js").write_text("// crimson")
    (cfg / "CustomApps/crimson/index.js").write_text("// crimson app")
    (cfg / "CustomApps/crimson/manifest.json").write_text("{}")
    (cfg / "config-xpui.ini").write_text(
        "[Setting]\n"
        f"spotify_path = {sp}\nprefs_path = {home / '.config/spotify/prefs'}\ncurrent_theme = Crimson\n"
        "color_scheme = Crimson\ninject_theme_js = 1\ninject_css = 1\nreplace_colors = 1\noverwrite_assets = 0\n\n"
        "[Preprocesses]\nexpose_apis = 1\n\n[AdditionalOptions]\nextensions = fullAppDisplay.js|keyboardShortcut.js\n"
        "custom_apps = crimson\n\n[Backup]\nversion = 1.2.93.1\nwith = 2.44.0\n")
    # Spotify currently patched with the Crimson theme
    subprocess.run([str(STUBS / "spicetify"), "apply"], env=env_for(home), check=True, capture_output=True)


def stock_home(home: Path) -> None:
    """Plain Breeze Dark Plasma, unmodified Spotify, Spicetify installed but never used."""
    write_ini(kfile(home, "kdeglobals"), {"KDE": {"LookAndFeelPackage": "org.kde.breezedark.desktop"}})
    desktops(home, "file:///usr/share/wallpapers/Next/left.png", "file:///usr/share/wallpapers/Next/right.png")
    _spotify_install(home, patched=False)


def plasmashell(home: Path) -> subprocess.Popen:
    """A process named plasmashell so VOID believes Plasma is running."""
    link = home / "bin-plasma" / "plasmashell"
    link.parent.mkdir(exist_ok=True)
    if not link.exists():
        os.symlink("/bin/sleep", link)
    return subprocess.Popen([str(link), "600"])


def snapshot(home: Path) -> dict:
    files = ["kdeglobals", "plasmarc", "kcminputrc", "kwinrc", "breezerc", "kwinrulesrc", "konsolerc", "kscreenlockerrc",
             "kglobalshortcutsrc"]
    return {
        "ini": {f: read_ini(kfile(home, f)) for f in files},
        "desktops": json.loads((home / "plasma-desktops.json").read_text())["desktops"],
        "systemd": {u: v for u, v in json.loads((home / "systemd-state.json").read_text()).items()
                    if u.startswith("crimson")} if (home / "systemd-state.json").exists() else {},
        "spicetify": spicetify_ini(home),
        "xpui_css": (home / SPOTIFY_REL / "Apps/xpui/user.css").read_text() if (home / SPOTIFY_REL / "Apps/xpui/user.css").exists() else None,
        "spa": sorted(p.name for p in (home / SPOTIFY_REL / "Apps").glob("*.spa")),
        # VOID's own void.conf stays installed after deactivate (like the Konsole profiles) — compare the rest
        # VOID's own void.conf / void-profile.conf stay installed after deactivate (like the Konsole
        # profiles; `void restore --uninstall` removes them) — everything else must come back
        "kitty": {p.name: p.read_bytes() for p in sorted((home / ".config/kitty").glob("*"))
                  if p.name not in ("void.conf", "void-profile.conf")} or None
                 if (home / ".config/kitty").exists() else None,
    }




def void_tty(home: Path, args: list[str], answers: dict[str, str], timeout: float = 120) -> tuple[int, str]:
    """Run `void` on a pseudo-terminal and answer its questions like a person would.

    answers: {substring of the question: reply}. Unmatched questions get "n" (the safe answer).
    """
    import pty
    import select
    import time
    env = env_for(home)
    env.pop("VOID_YES")
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(str(ROOT / "bin" / "void"), ["void", *args], env)
    out, buf = [], ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r, _, _ = select.select([fd], [], [], 0.5)
        if not r:
            continue
        try:
            chunk = os.read(fd, 4096).decode(errors="replace")
        except OSError:
            break
        if not chunk:
            break
        out.append(chunk)
        buf += chunk
        if buf.rstrip().endswith(("[Y/n]", "[y/N]")):
            q = buf.rsplit("?", 2)[-2] if "?" in buf else buf
            reply = next((a for k, a in answers.items() if k in q), "n")
            os.write(fd, (reply + "\n").encode())
            buf = ""
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), "".join(out)
