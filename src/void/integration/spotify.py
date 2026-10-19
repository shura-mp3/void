"""VOID Spotify — Spicetify theme + custom app, applied through the journal (`void spotify …`).

  inspect            read-only report: Spotify package/version/state, Spicetify version/config
  status             what is configured and whether Spotify's VOID script reached void-core
  apply / revert     the Spotify part of activate / deactivate on its own
  install-spicetify  download the official Spicetify release (asks first; nothing runs `curl | sh`)

Rules: nothing privileged without an explicit yes (never answered by --yes); Spotify is never
reinstalled or switched to another package format; the first patch of a stock Spotify is asked
for separately; if `spicetify apply` fails the Spicetify settings are rolled back at once.
Spicetify has ONE active theme: while VOID is active it is VOID, and deactivation re-applies
whatever was active before (Crimson's theme, another theme, or stock Spotify).
"""

from __future__ import annotations

import configparser
import hashlib
import io
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

from .. import client, paths
from ..config import JsonState
from . import files, ui
from .journal import ABSENT, Handler, Journal, register

THEME, APP = "VOID", "void"
SRC_THEME = paths.PROJECT_DIR / "spicetify" / "Themes" / THEME
SRC_APP = paths.PROJECT_DIR / "spicetify" / "CustomApps" / APP
MARKER = ".void-desktop"
FAD = "fullAppDisplay.js"          # ships inside every Spicetify release (LGPL-2.1)
FLATPAK_ID = "com.spotify.Client"
FLATPAK_TAIL = "app/com.spotify.Client/x86_64/stable/active/files/extra/share/spotify"
HOME = paths.HOME
CANDIDATES = [  # the list Spicetify itself searches on Linux
    "/opt/spotify", "/opt/spotify/spotify-client", "/usr/share/spotify", "/usr/libexec/spotify",
    "/usr/share/spotify-client", f"/var/lib/flatpak/{FLATPAK_TAIL}", f"{HOME}/.local/share/flatpak/{FLATPAK_TAIL}",
    f"{HOME}/.local/share/spotify-launcher/install/usr/share/spotify",
]
STATE = paths.STATE_DIR / "spotify.json"


# ════════════════════════════════════════════════════════════════════ detection (read-only)
def prefs_version(prefs: Path) -> str:
    try:
        for line in prefs.read_text(errors="replace").splitlines():
            if line.startswith("app.last-launched-version="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def apps_state(app_dir: Path) -> str:
    """Spicetify's own classification: stock / applied / mixed / invalid."""
    try:
        entries = list((app_dir / "Apps").iterdir())
    except OSError:
        return "unreadable"
    spa = sum(1 for e in entries if e.is_file() and e.name.endswith(".spa"))
    dirs = sum(1 for e in entries if e.is_dir())
    return "mixed" if spa and dirs else "stock" if spa else "applied" if dirs else "invalid"


def writable_tree(app_dir: Path) -> bool:
    apps = app_dir / "Apps"
    if not (os.access(app_dir, os.W_OK) and os.access(apps, os.W_OK)):
        return False
    return all(os.access(p, os.W_OK) for p in apps.iterdir())


def detect_spotify() -> list[dict]:
    found: dict[str, dict] = {}
    xdg = paths.XDG_CONFIG

    def add(path: str, method: str, prefs: Path, version: str = "", extra: str = ""):
        p = Path(path)
        if not ((p / "Apps").is_dir() and (p / "spotify").exists()):
            return
        key = str(p.resolve())
        if key in found:
            return
        st = p.stat()
        found[key] = {"method": method, "path": str(p), "prefs": str(prefs) if prefs.exists() else "",
                      "prefs_expected": str(prefs), "version": version or prefs_version(prefs),
                      "owner": "you" if st.st_uid == os.getuid() else ("root" if st.st_uid == 0 else str(st.st_uid)),
                      "writable": writable_tree(p), "state": apps_state(p), "extra": extra}

    flatpak_prefs = HOME / ".var" / "app" / FLATPAK_ID / "config" / "spotify" / "prefs"
    native_prefs = xdg / "spotify" / "prefs"
    if ui.have("flatpak"):
        rc, out = ui.run(["flatpak", "list", "--app", "--columns=application,version,installation"])
        for line in out.splitlines() if rc == 0 else []:
            cols = line.split("\t")
            if cols and cols[0] == FLATPAK_ID:
                inst = cols[2] if len(cols) > 2 else "system"
                base = f"{HOME}/.local/share/flatpak" if inst == "user" else "/var/lib/flatpak"
                add(f"{base}/{FLATPAK_TAIL}", f"flatpak-{inst}", flatpak_prefs, cols[1] if len(cols) > 1 else "")
    if ui.have("rpm"):
        rc, out = ui.run(["rpm", "-qa", "--qf", "%{NAME} %{VERSION}-%{RELEASE}\n"])
        for line in out.splitlines() if rc == 0 else []:
            name, _, ver = line.partition(" ")
            if "spotify" in name.lower() and not name.startswith("lpf-"):
                _, flist = ui.run(["rpm", "-ql", name])
                for f in flist.splitlines():
                    if f.endswith("/Apps"):
                        add(str(Path(f).parent), "rpm", native_prefs, extra=f"package {name} {ver}")
    if ui.have("snap") and ui.run(["snap", "list", "spotify"])[0] == 0:
        found["snap"] = {"method": "snap", "path": "/snap/spotify/current/usr/share/spotify", "prefs": "",
                         "prefs_expected": "", "version": "", "owner": "root", "writable": False,
                         "state": "read-only", "extra": "snap packages are read-only: Spicetify can't patch them"}
    for c in CANDIDATES:
        add(c, "other", flatpak_prefs if "flatpak" in c else native_prefs)
    return list(found.values())


def running_spotify() -> bool:
    rc, out = ui.run(["pgrep", "-a", "-f", "spotify"])
    return rc == 0 and any("spotify" in l.split(" ", 1)[-1].split(" ")[0].lower() and "pgrep" not in l
                           and "void" not in l for l in out.splitlines())


def spicetify_bin() -> str | None:
    return shutil.which("spicetify") or next(
        (str(p) for p in (HOME / ".spicetify" / "spicetify", HOME / ".local" / "bin" / "spicetify") if p.exists()), None)


def config_dir() -> Path:
    return paths.XDG_CONFIG / "spicetify"


def config_file() -> Path:
    return config_dir() / "config-xpui.ini"


def read_ini() -> configparser.ConfigParser | None:
    p = config_file()
    if not p.exists():
        return None
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    try:
        cp.read(p)
    except configparser.Error:
        return None
    return cp


def setting(section: str, key: str, default: str = "") -> str:
    cp = read_ini()
    return cp.get(section, key, fallback=default) if cp else default


def detect_spicetify() -> dict:
    exe = spicetify_bin()
    info = {"binary": exe, "version": "", "config_file": str(config_file()), "config": {}, "themes": [], "backup": False}
    if exe:
        rc, out = ui.run([exe, "-v"])
        info["version"] = out.splitlines()[-1].strip() if rc == 0 and out else "unknown"
    cp = read_ini()
    if cp:
        info["config"] = {s: dict(cp[s]) for s in cp.sections()}
    d = config_dir() / "Themes"
    info["themes"] = sorted(x.name for x in d.iterdir()) if d.is_dir() else []
    for bd in (paths.XDG_STATE / "spicetify" / "Backup", config_dir() / "Backup"):
        if bd.is_dir() and any(x.suffix == ".spa" for x in bd.iterdir()):
            info["backup"] = True
    return info


def inspect() -> dict:
    ui.hdr("Spotify / Spicetify (read-only)")
    installs, sp = detect_spotify(), detect_spicetify()
    if not installs:
        ui.bad("no Spotify installation found (looked at Flatpak, RPM, snap and Spicetify's standard paths)")
    for s in installs:
        print(f"  spotify     {s['method']} {s['version'] or '(version unknown — launch Spotify once)'}  {s['path']}")
        print(f"              state={s['state']} owner={s['owner']} writable={'yes' if s['writable'] else 'no'} "
              f"prefs={'found' if s['prefs'] else 'missing'} {s['extra']}")
    print(f"  spicetify   {sp['binary'] or 'not installed'} {sp['version']}")
    st, ao = sp["config"].get("Setting", {}), sp["config"].get("AdditionalOptions", {})
    if sp["config"]:
        print(f"              theme={st.get('current_theme') or '—'} scheme={st.get('color_scheme') or '—'} "
              f"extensions={ao.get('extensions') or '—'} custom_apps={ao.get('custom_apps') or '—'}")
    print(f"              installed themes: {', '.join(sp['themes']) or '—'}   Spotify-file backup: {'yes' if sp['backup'] else 'no'}")
    if st.get("current_theme") == "Crimson":
        ui.info("Crimson Spotify is the active theme — VOID swaps it out while active and puts it back on deactivate")
    return {"spotify": installs, "spicetify": sp, "running": running_spotify()}


# ════════════════════════════════════════════════════════════════════ journal handler
LIST_KEYS = ("extensions", "custom_apps")


@register
class Spicetify(Handler):
    """key = a config-xpui.ini setting name. Lists (extensions, custom_apps) are python lists."""
    kind = "spicetify"

    def get(self, key):
        sect = "AdditionalOptions" if key in LIST_KEYS else "Setting"
        cp = read_ini()
        if cp is None or not cp.has_option(sect, key):
            return ABSENT if key not in LIST_KEYS else []
        v = cp.get(sect, key)
        return [x for x in v.split("|") if x] if key in LIST_KEYS else v

    def set(self, key, value):
        exe = spicetify_bin()
        if not exe:
            raise RuntimeError("spicetify is not installed")
        if key in LIST_KEYS:
            cur = self.get(key)
            ops = [f"{x}-" for x in cur if x not in value] + [x for x in value if x not in cur]
            if ops:
                ui.run([exe, "config", key, "|".join(ops)], check=True)
        else:
            ui.run([exe, "config", key, "" if value == ABSENT else str(value)], check=True)

    def describe(self, key):
        return f"Spicetify {key}"


# ════════════════════════════════════════════════════════════════════ theme files
def tree_hash(d: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(x for x in d.rglob("*") if x.is_file() and x.name != MARKER):
        h.update(str(f.relative_to(d)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def install_theme_files() -> bool:
    changed = False
    for src, dst in ((SRC_THEME, config_dir() / "Themes" / THEME), (SRC_APP, config_dir() / "CustomApps" / APP)):
        if dst.exists() and not (dst / MARKER).exists():
            raise RuntimeError(f"{dst} exists and was not created by VOID — not overwriting it (rename it, then retry)")
        if dst.exists() and tree_hash(dst) == tree_hash(src):
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        (dst / MARKER).write_text("installed by VOID (void spotify); removed by `void restore --uninstall`\n")
        changed = True
        ui.ok(f"installed {files.short(dst)}")
    return changed


def remove_theme_files() -> None:
    for d in (config_dir() / "Themes" / THEME, config_dir() / "CustomApps" / APP):
        if (d / MARKER).exists():
            shutil.rmtree(d)
            ui.ok(f"removed {files.short(d)}")


# ════════════════════════════════════════════════════════════════════ apply / revert
def _spice(exe: str, *args: str, interactive: bool = True) -> int:
    print(f"    $ spicetify {' '.join(args)}")
    if interactive and sys.stdin.isatty():
        return subprocess.run([exe, *args]).returncode
    rc, out = ui.run([exe, *args], timeout=180)
    for l in out.splitlines()[-8:]:
        print("      " + l)
    return rc


def _target(installs: list[dict], cfg: dict) -> dict | None:
    usable = [s for s in installs if s["method"] != "snap"]
    want = cfg["spicetify"].get("target") or setting("Setting", "spotify_path")
    if want:
        pick = [s for s in usable if s["method"] == want or s["path"].rstrip("/") == str(want).rstrip("/")]
        if pick:
            return pick[0]
    if len(usable) == 1:
        return usable[0]
    if len(usable) > 1:
        ui.warn("several Spotify installations found — set [spicetify] target in config.toml to one of: "
                + ", ".join(f"{s['method']} ({s['path']})" for s in usable))
    return None


def apply(j: Journal, cfg: dict) -> str:
    """The Spotify part of activation. Returns a one-line outcome; never raises for 'not possible'."""
    if not cfg["spicetify"].get("enabled", True):
        return "disabled in config"
    exe = spicetify_bin()
    if not exe:
        ui.warn("Spicetify is not installed, so Spotify keeps its current look.")
        ui.info("to theme Spotify: void spotify install-spicetify   (official release, asks before downloading)")
        return "skipped: Spicetify not installed"
    spot = _target(detect_spotify(), cfg)
    if not spot:
        return "skipped: no usable Spotify installation"
    if spot["state"] in ("mixed", "invalid", "unreadable"):
        ui.warn(f"Spotify's Apps folder is '{spot['state']}' — Spicetify can't safely patch it. "
                "Fix: `spicetify restore` or reinstall/update Spotify, then `void spotify apply`.")
        return f"skipped: Spotify files {spot['state']}"
    if not spot["prefs"]:
        return f"skipped: launch Spotify once so {spot['prefs_expected']} exists"
    ui.ok(f"Spotify {spot['version']} ({spot['method']}, {spot['state']}) · Spicetify {detect_spicetify()['version']}")
    st = JsonState(STATE)
    if not spot["writable"]:
        ui.hdr("Spotify permissions — your approval needed")
        print(f"  Spicetify must write Spotify's UI files in {spot['path']} (owned by {spot['owner']}).")
        print("  Spicetify's documented fix for system-wide installs:")
        print(f"    sudo chmod a+wr {spot['path']}\n    sudo chmod a+wr -R {spot['path']}/Apps")
        print("  Risk: any local account could then change Spotify's UI files. Package updates reset them.")
        if not ui.ask("run these two sudo commands now?", False, privileged=True):
            return "skipped: permission change declined (Spotify untouched)"
        modes = {p: oct(Path(p).stat().st_mode & 0o7777) for p in (spot["path"], f"{spot['path']}/Apps")}
        for c in (["sudo", "chmod", "a+wr", spot["path"]], ["sudo", "chmod", "a+wr", "-R", f"{spot['path']}/Apps"]):
            if subprocess.run(c).returncode != 0:
                return "skipped: chmod failed (Spotify untouched)"
        st.data.setdefault("chmod", modes)
        st.save()
    was_stock = spot["state"] == "stock"
    if was_stock and not detect_spicetify()["backup"]:
        print("  Spotify is unmodified. Spicetify will back up its original UI files, then patch them")
        print("  (`spicetify backup apply`). `void deactivate` returns Spotify to stock with `spicetify restore`.")
        if not ui.ask("let Spicetify patch Spotify now?", True, privileged=True):
            return "skipped: patching declined (Spotify untouched)"
    if not config_file().exists():
        ui.run([exe, "config"])  # first run: Spicetify writes config-xpui.ini
    install_theme_files()
    # point Spicetify at this install if its own detection left the path empty or wrong
    if setting("Setting", "spotify_path").rstrip("/") != spot["path"].rstrip("/"):
        j.change("spicetify", "spotify_path", spot["path"], "Spotify location")
    if setting("Setting", "prefs_path") != spot["prefs"]:
        j.change("spicetify", "prefs_path", spot["prefs"], "Spotify prefs location")
    for k, v in (("current_theme", THEME), ("color_scheme", THEME), ("inject_css", "1"),
                 ("replace_colors", "1"), ("inject_theme_js", "1")):
        j.change("spicetify", k, v, "VOID Spotify theme")
    exts = [e for e in Spicetify().get("extensions")]
    if cfg["spicetify"].get("full_app_display", True) and FAD not in exts:
        exts.append(FAD)
    j.change("spicetify", "extensions", exts, "Full App Display (bundled with Spicetify)")
    apps = [a for a in Spicetify().get("custom_apps") if a != "crimson"]  # crimson-core is paused while VOID runs
    if cfg["spicetify"].get("custom_app", True) and APP not in apps:
        apps.append(APP)
    j.change("spicetify", "custom_apps", apps, "VOID page in Spotify's sidebar")
    if running_spotify() and not ui.ask("Spicetify restarts Spotify to apply the theme (playback stops briefly). Apply now?", True):
        st.data.update({"pending_apply": True})
        st.save()
        return "configured; apply later with: void spotify apply"
    rc = _spice(exe, "backup", "apply") if was_stock and not detect_spicetify()["backup"] else _spice(exe, "apply")
    if rc != 0:
        ui.bad("spicetify apply failed — this Spotify version may not be supported by your Spicetify version yet")
        ui.info("rolling the Spicetify settings back; Spotify keeps working. Try `spicetify upgrade`, then `void spotify apply`")
        revert_settings(j)
        if was_stock:
            _spice(exe, "restore")
        else:
            _spice(exe, "apply")
        return "failed: spicetify apply (settings rolled back)"
    st.data.update({"applied": True, "was_stock": was_stock, "pending_apply": False,
                    "spotify": {k: spot[k] for k in ("method", "path", "version")}})
    st.save()
    return f"applied (VOID theme{', Full App Display' if FAD in exts else ''}{', VOID page' if APP in apps else ''})"


def revert_settings(j: Journal, report=lambda *a: None) -> int:
    """Revert only the Spicetify entries of the current session (used after a failed apply)."""
    entries = [e for e in j.entries() if e["kind"] == "spicetify"]
    return j._revert([(e, e["previous"], e["applied"]) for e in reversed(entries)], False, report)


def before_revert() -> str | None:
    """If Spotify was stock before VOID, un-patch it NOW — `spicetify restore` needs the current
    config (it knows where Spotify is); the journal then puts the previous settings back."""
    st = JsonState(STATE)
    exe = spicetify_bin()
    if not (exe and st.data.get("applied") and st.data.get("was_stock")):
        return None
    if running_spotify() and not ui.ask("return Spotify to its unmodified state now (restarts Spotify)?", True):
        return "Spotify left patched; run `spicetify restore` when convenient"
    rc = _spice(exe, "restore")
    if rc != 0:
        return "`spicetify restore` failed — run it by hand to return Spotify to stock"
    st.data.update({"applied": False})
    st.save()
    return "stock Spotify restored"


def after_revert() -> str:
    """Called after the journal put the previous Spicetify settings back: re-apply the previous theme."""
    st = JsonState(STATE)
    exe = spicetify_bin()
    if not (exe and st.data.get("applied")):
        return "nothing to re-apply"
    if running_spotify() and not ui.ask("re-apply your previous Spotify look now (restarts Spotify)?", True):
        return "previous settings restored; run `spicetify apply` when convenient"
    rc = _spice(exe, "apply")
    if rc != 0:
        return "previous settings restored, but `spicetify apply` failed — run it by hand"
    st.data.update({"applied": False})
    st.save()
    return "previous Spotify theme re-applied"


def bridge_connected(wait: int = 0) -> bool | None:
    deadline = time.monotonic() + wait
    while True:
        r = client.request({"cmd": "status"}, timeout=2)
        if r is None:
            return None
        if (r.get("bridge") or {}).get("connections"):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1)


# ════════════════════════════════════════════════════════════════════ explicit install
def arch() -> str:
    return {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())


def install_spicetify() -> int:
    """Official release tarball into ~/.spicetify (no install script is executed)."""
    if spicetify_bin():
        ui.ok(f"Spicetify already installed: {spicetify_bin()}")
        return 0
    dest = HOME / ".spicetify"
    if dest.exists() and any(dest.iterdir()):
        ui.bad(f"{dest} exists but holds no working spicetify binary — inspect it first; nothing changed")
        return 1
    try:
        req = urllib.request.Request("https://api.github.com/repos/spicetify/cli/releases/latest",
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": "void-desktop"})
        with urllib.request.urlopen(req, timeout=15) as r:
            rel = json.load(r)
    except Exception as e:  # noqa: BLE001
        ui.bad(f"couldn't reach GitHub to find the latest Spicetify release ({e}); nothing changed")
        return 1
    ver = rel["tag_name"].lstrip("v")
    name = f"spicetify-{ver}-linux-{arch()}.tar.gz"
    asset = next((a for a in rel.get("assets", []) if a["name"] == name), None)
    if not asset:
        ui.bad(f"release v{ver} has no {name}; nothing changed")
        return 1
    digest = (asset.get("digest") or "").removeprefix("sha256:") or None
    print(f"  Spicetify v{ver} (third-party, LGPL-2.1): {asset['browser_download_url']}")
    print(f"  checksum: {'sha256 ' + digest if digest else 'GitHub published no digest for this file'}")
    print("  It installs to ~/.spicetify (user level, no sudo). Spotify itself is not changed by this step.")
    if not ui.ask("download and install it?", False, privileged=True):
        return 1
    with urllib.request.urlopen(urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "void-desktop"}),
                                timeout=60) as r:
        data = r.read()
    got = hashlib.sha256(data).hexdigest()
    if digest and got != digest:
        ui.bad(f"checksum mismatch (expected {digest}, got {got}) — not installing")
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        tf.extractall(dest, filter="data")
    exe = dest / "spicetify"
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    link = HOME / ".local" / "bin" / "spicetify"
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.exists():
        link.symlink_to(exe)
    st = JsonState(STATE)
    st.data["spicetify_installed_by_void"] = {"version": ver, "sha256": got, "verified": bool(digest)}
    st.save()
    ui.ok(f"Spicetify v{ver} installed ({dest}); run `void spotify apply` to theme Spotify")
    return 0


def status() -> None:
    sp = detect_spicetify()
    st = JsonState(STATE).data
    s = sp["config"].get("Setting", {})
    a = sp["config"].get("AdditionalOptions", {})
    print(f"  spicetify   {sp['binary'] or 'not installed'} {sp['version']}")
    print(f"  theme       {s.get('current_theme') or '—'} / {s.get('color_scheme') or '—'}")
    print(f"  extensions  {a.get('extensions') or '—'}")
    print(f"  apps        {a.get('custom_apps') or '—'}")
    if s.get("spotify_path"):
        print(f"  spotify     {s['spotify_path']}  state={apps_state(Path(s['spotify_path']))}")
    css = Path(s.get("spotify_path") or "/nonexistent") / "Apps" / "xpui" / "user.css"
    print(f"  applied     {'VOID user.css present' if css.exists() and 'VOID Spotify' in css.read_text(errors='replace') else 'VOID theme not applied'}"
          f"{'  (apply pending)' if st.get('pending_apply') else ''}")
    b = bridge_connected(0)
    print(f"  bridge      {'Spotify connected to void-core' if b else 'void-core not running' if b is None else 'no Spotify connection'}")


def main(argv: list[str]) -> int:
    from . import switch
    cmd = argv[0] if argv else "status"
    if cmd == "inspect":
        inspect()
    elif cmd == "status":
        status()
    elif cmd == "install-spicetify":
        return install_spicetify()
    elif cmd == "apply":
        j = Journal().lock()
        if j.status not in ("active", "failed", "activating"):
            ui.warn("VOID is not active; `void activate` applies Spotify together with the rest")
            return 1
        from ..config import load
        print("  " + apply(j, load()))
    elif cmd == "revert":
        j = Journal().lock()
        first = before_revert()
        revert_settings(j, switch.reporter())
        print("  " + (first or after_revert()))
    else:
        print(__doc__)
        return 2
    return 0
