"""KDE Plasma: config access through KDE's own tools, and the VOID Monochrome look.

Everything goes through supported interfaces: kreadconfig6/kwriteconfig6 for settings,
plasma-apply-colorscheme / -desktoptheme / -cursortheme to repaint running apps, Plasma's
desktop scripting (evaluateScript over D-Bus) for wallpapers, and KWin's reconfigure call.
Plasma and KWin themselves are never replaced or modified.

Colour scheme: KDE's colour scheme is global — it recolours apps on BOTH monitors. Only the
wallpaper and the dashboard are specific to the right-hand monitor.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .. import paths, tokens
from . import files, ui
from .journal import ABSENT, Handler, register

SCHEME = "VOIDMonochrome"
SENTINEL = "__VOID_ABSENT__"
RULE_ID = "void-dashboard-0808f2f2"
DASH_TITLE = "VOID//DASHBOARD"


def tool(*names: str) -> str | None:
    return next((shutil.which(n) for n in names if shutil.which(n)), None)


def kwrite_bin() -> str:
    b = tool("kwriteconfig6", "kwriteconfig5")
    if not b:
        raise RuntimeError("kwriteconfig6 not found — is this KDE Plasma? (package: kf6-kconfig)")
    return b


def kread_bin() -> str:
    b = tool("kreadconfig6", "kreadconfig5")
    if not b:
        raise RuntimeError("kreadconfig6 not found — is this KDE Plasma? (package: kf6-kconfig)")
    return b


def _groups(groups: str) -> list[str]:
    out = []
    for g in groups.split(">"):
        out += ["--group", g]
    return out


def kread(file: str, groups: str, key: str):
    rc, out = ui.run([kread_bin(), "--file", file, *_groups(groups), "--key", key, "--default", SENTINEL])
    if rc != 0:
        raise RuntimeError(f"kreadconfig failed: {out}")
    return ABSENT if out == SENTINEL else out


def kwrite(file: str, groups: str, key: str, value) -> None:
    if value == ABSENT:
        args = [kwrite_bin(), "--file", file, *_groups(groups), "--key", key, "--delete"]
    else:
        args = [kwrite_bin(), "--file", file, *_groups(groups), "--key", key, str(value)]
    ui.run(args, check=True)


def kkey(file: str, groups: str, key: str) -> str:
    """Journal key for a KConfig entry: file::Group>Sub::Key."""
    return f"{file}::{groups}::{key}"


@register
class KConfig(Handler):
    kind = "kconfig"

    def get(self, key):
        return kread(*key.split("::"))

    def set(self, key, value):
        kwrite(*key.split("::"), value)

    def describe(self, key):
        f, g, k = key.split("::")
        return f"{f} [{g.replace('>', '][')}] {k}"


def qdbus(service: str, path: str, method: str, *args: str) -> tuple[int, str]:
    q = tool("qdbus6", "qdbus-qt6", "qdbus")
    if q:
        return ui.run([q, service, path, method, *args])
    return ui.run(["gdbus", "call", "--session", "--dest", service, "--object-path", path, "--method", method, *args])


def plasma_eval(js: str) -> str:
    rc, out = qdbus("org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", js)
    if rc != 0:
        raise RuntimeError(f"Plasma scripting failed (is plasmashell running?): {out[-300:]}")
    return out


def kwin_reconfigure() -> None:
    qdbus("org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure")


def plasma_running() -> bool:
    return ui.run(["pgrep", "-x", "plasmashell"])[0] == 0


# ════════════════════════════════════════════════════════════════════ look handlers
def _hex(rgbcsv: str) -> str:
    try:
        return "#" + "".join(f"{int(x):02X}" for x in rgbcsv.split(",")[:3])
    except ValueError:
        return rgbcsv


@register
class ColorScheme(Handler):
    """The global colour scheme together with the accent colour (Crimson sets a crimson accent,
    which would otherwise tint VOID's selection and focus colours)."""
    kind = "colorscheme"

    def get(self, key):
        scheme = kread("kdeglobals", "General", "ColorScheme")
        if scheme == ABSENT:
            lnf = kread("kdeglobals", "KDE", "LookAndFeelPackage")
            scheme = "BreezeDark" if lnf != ABSENT and "dark" in lnf.lower() else "BreezeLight"
        return {"scheme": scheme, "accent": kread("kdeglobals", "General", "AccentColor"),
                "accent_from_wallpaper": kread("kdeglobals", "General", "accentColorFromWallpaper")}

    def set(self, key, value):
        kwrite("kdeglobals", "General", "accentColorFromWallpaper", value.get("accent_from_wallpaper", ABSENT))
        accent = value.get("accent", ABSENT)
        if accent == ABSENT:
            kwrite("kdeglobals", "General", "AccentColor", ABSENT)
        args = ["plasma-apply-colorscheme"] + (["--accent-color", _hex(accent)] if accent != ABSENT else []) + [value["scheme"]]
        rc, out = ui.run(args)
        if rc != 0 and "already" not in out.lower():
            raise RuntimeError(f"plasma-apply-colorscheme {value['scheme']}: {out[-200:]}")

    def describe(self, key):
        return "KDE colour scheme + accent"


@register
class DesktopTheme(Handler):
    kind = "desktoptheme"

    def get(self, key):
        v = kread("plasmarc", "Theme", "name")
        return "default" if v == ABSENT else v

    def set(self, key, value):
        ui.run(["plasma-apply-desktoptheme", "default" if value == ABSENT else value], check=True)

    def describe(self, key):
        return "Plasma style"


@register
class CursorTheme(Handler):
    kind = "cursortheme"

    def get(self, key):
        v = kread("kcminputrc", "Mouse", "cursorTheme")
        return "breeze_cursors" if v == ABSENT else v

    def set(self, key, value):
        ui.run(["plasma-apply-cursortheme", "breeze_cursors" if value == ABSENT else value], check=True)

    def describe(self, key):
        return "cursor theme"


# ════════════════════════════════════════════════════════════════════ what VOID applies
def install_files() -> None:
    files.install(paths.XDG_DATA / "color-schemes" / f"{SCHEME}.colors", tokens.kde_colors())


def monochrome_cursor() -> str | None:
    """A cursor theme that is already installed and monochrome (never downloads one)."""
    for name in ("Bibata-Modern-Classic", "breeze_cursors", "Breeze_Light"):
        for base in (paths.HOME / ".local/share/icons", paths.HOME / ".icons", Path("/usr/share/icons")):
            if (base / name / "cursors").is_dir():
                return name
    return None


def mono_font() -> str | None:
    rc, out = ui.run(["fc-list", ":", "family"]) if ui.have("fc-list") else (1, "")
    fams = {f.strip() for line in out.splitlines() for f in line.split(",")}
    want = tokens.load()["terminal"]["font"]
    return want if want in fams else None


def decoration_settings() -> list[tuple[str, str, str, str]]:
    """Breeze window decoration tuned for VOID: hairline borders, neutral black shadows."""
    return [
        ("kwinrc", "org.kde.kdecoration2", "library", "org.kde.breeze"),
        ("kwinrc", "org.kde.kdecoration2", "theme", "Breeze"),
        ("kwinrc", "org.kde.kdecoration2", "BorderSize", "Tiny"),
        ("kwinrc", "org.kde.kdecoration2", "BorderSizeAuto", "false"),
        ("breezerc", "Common", "OutlineIntensity", "OutlineLow"),
        ("breezerc", "Common", "ShadowColor", "0,0,0"),
        ("breezerc", "Common", "ShadowSize", "ShadowMedium"),
        ("breezerc", "Common", "ShadowStrength", "170"),
        ("breezerc", "Windeco", "DrawBorderOnMaximizedWindows", "false"),
        ("breezerc", "Windeco", "DrawTitleBarSeparator", "false"),
        ("breezerc", "Windeco", "TitleAlignment", "AlignLeft"),
        ("kdeglobals", "KDE", "AnimationDurationFactor", "0.7"),  # restrained, not removed
    ]


def dashboard_rule(geometry: dict) -> list[tuple[str, str, str, str]]:
    """KWin window rule placing the dashboard Konsole window on the right-hand monitor.

    Wayland clients cannot position their own windows; a rule is KWin's supported mechanism.
    Matches only windows whose title contains VOID//DASHBOARD (the dashboard profile's fixed title).
    The class pattern is written to match whether or not KWin anchors regular expressions
    (Konsole's Wayland class is org.kde.konsole).
    """
    g = RULE_ID
    x, y, w, h = geometry["x"], geometry["y"], geometry["logical_width"], geometry["logical_height"]
    kv = [
        ("Description", "VOID dashboard on the right-hand monitor (VOID)"),
        ("wmclass", ".*(konsole|kitty|alacritty|void-dashboard).*"), ("wmclassmatch", "3"), ("wmclasscomplete", "false"),
        ("title", DASH_TITLE), ("titlematch", "2"),
        ("position", f"{x},{y}"), ("positionrule", "3"),
        ("size", f"{w},{h}"), ("sizerule", "3"),
        ("maximizehoriz", "true"), ("maximizehorizrule", "3"),
        ("maximizevert", "true"), ("maximizevertrule", "3"),
        ("noborder", "true"), ("noborderrule", "2"),
        ("skiptaskbar", "true"), ("skiptaskbarrule", "2"),
        ("skipswitcher", "true"), ("skipswitcherrule", "2"),
        ("skippager", "true"), ("skippagerrule", "2"),
        ("below", "true"), ("belowrule", "2"),
    ]
    return [("kwinrulesrc", g, k, v) for k, v in kv]


def rules_list_with(rule: str) -> tuple[str, str]:
    cur = kread("kwinrulesrc", "General", "rules")
    items = [r for r in ("" if cur == ABSENT else cur).split(",") if r]
    if rule not in items:
        items.append(rule)
    return ",".join(items), str(len(items))


def lockscreen_settings(image: str) -> list[tuple[str, str, str, str]]:
    return [
        ("kscreenlockerrc", "Greeter", "WallpaperPlugin", "org.kde.image"),
        ("kscreenlockerrc", "Greeter>Wallpaper>org.kde.image>General", "Image", f"file://{image}"),
    ]


def detect() -> dict:
    """Read-only facts for `void inspect`."""
    v = {}
    for cmd in (["plasmashell", "--version"], ["kwin_wayland", "--version"]):
        rc, out = ui.run(cmd) if ui.have(cmd[0]) else (1, "")
        v[cmd[0]] = out.splitlines()[-1] if rc == 0 and out else "not found"
    try:
        v["color_scheme"] = ColorScheme().get("")
        v["plasma_style"] = DesktopTheme().get("")
        v["cursor"] = CursorTheme().get("")
        v["kwin_rules"] = kread("kwinrulesrc", "General", "rules")
    except RuntimeError as e:
        v["error"] = str(e)
    v["tools"] = {t: bool(ui.have(t)) for t in ("kwriteconfig6", "kreadconfig6", "plasma-apply-colorscheme",
                                               "plasma-apply-desktoptheme", "plasma-apply-cursortheme",
                                               "kscreen-doctor", "qdbus6", "konsole")}
    return v

