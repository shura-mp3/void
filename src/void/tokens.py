"""VOID design tokens: load config/tokens.toml and render every derived palette file.

    bin/void tokens build     regenerate all outputs
    bin/void tokens check     exit 1 if an output is stale (also run by the test suite)
"""

from __future__ import annotations

import json
import sys
import tomllib
from functools import lru_cache
from pathlib import Path

from . import paths

ANSI_ORDER = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
HEADER = "Generated from config/tokens.toml by `bin/void tokens build` — do not edit by hand."


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> dict:
    with open(path or paths.TOKENS_FILE, "rb") as f:
        return tomllib.load(f)


def pal() -> dict[str, str]:
    return load()["palette"]


def rgb(hexstr: str) -> tuple[int, int, int]:
    h = hexstr.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_csv(hexstr: str) -> str:
    return ",".join(str(c) for c in rgb(hexstr))


def sgr(hexstr: str, bg: bool = False) -> str:
    r, g, b = rgb(hexstr)
    return f"{48 if bg else 38};2;{r};{g};{b}"


def mix(a: str, b: str, t: float) -> str:
    ra, rb = rgb(a), rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ra, rb))


def luminance(hexstr: str) -> float:
    def ch(c: int) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(hexstr)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def resolve(value: str) -> str:
    """A token name ('text') or a literal '#hex' -> '#RRGGBB'."""
    return value if value.startswith("#") else pal()[value]


def ansi(i: int) -> str:
    a = load()["ansi"]
    return a[("bright_" if i >= 8 else "") + ANSI_ORDER[i % 8]]


# ════════════════════════════════════════════════════════════════════ renderers
def konsole_scheme() -> str:
    p, t = pal(), load()["terminal"]
    out = [f"# VOID — Konsole colour scheme. {HEADER}", ""]

    def group(name: str, color: str) -> None:
        out.extend([f"[{name}]", f"Color={rgb_csv(color)}", ""])

    group("Background", p["background"])
    group("BackgroundIntense", p["secondary"])
    group("BackgroundFaint", p["background"])
    group("Foreground", p["text"])
    group("ForegroundIntense", p["highlight"])
    group("ForegroundFaint", p["muted"])
    for i in range(8):
        group(f"Color{i}", ansi(i))
        group(f"Color{i}Intense", ansi(i + 8))
        group(f"Color{i}Faint", mix(ansi(i), p["background"], 0.4))
    out += ["[General]", "Anchor=0.5,0.5", "Blur=false", "ColorRandomization=false", "Description=VOID",
            "FillStyle=Tile", f"Opacity={t['opacity']}", "Wallpaper=", "WallpaperFlipType=NoFlip", "WallpaperOpacity=1", ""]
    return "\n".join(out)


def kde_colors() -> str:
    p, a = pal(), load()["ansi"]
    neg, neu, pos = a["bright_red"], a["bright_yellow"], a["bright_green"]

    def colors(bg: str, alt: str, fg: str, inactive: str, link: str = p["highlight"], active: str = p["highlight"],
               focus: str = p["highlight"], hover: str = p["secondary_text"]) -> dict[str, str]:
        return {"BackgroundAlternate": alt, "BackgroundNormal": bg, "DecorationFocus": focus, "DecorationHover": hover,
                "ForegroundActive": active, "ForegroundInactive": inactive, "ForegroundLink": link,
                "ForegroundNegative": neg, "ForegroundNeutral": neu, "ForegroundPositive": pos,
                "ForegroundVisited": p["secondary_text"], "ForegroundNormal": fg}

    groups = {
        "Colors:Button": colors(p["elevated"], p["border"], p["text"], p["muted"]),
        "Colors:Complementary": colors(p["background"], p["secondary"], p["text"], p["muted"]),
        "Colors:Header": colors(p["background"], p["secondary"], p["text"], p["muted"]),
        "Colors:Header][Inactive": colors(p["background"], p["secondary"], p["secondary_text"], p["muted"]),
        "Colors:Selection": colors(p["text"], "#CCCCCC", p["background"], p["border"], link=p["secondary"],
                                   active="#000000", focus=p["highlight"], hover=p["secondary_text"]),
        "Colors:Tooltip": colors(p["elevated"], p["secondary"], p["text"], p["muted"]),
        "Colors:View": colors(p["background"], p["secondary"], p["text"], p["muted"]),
        "Colors:Window": colors(p["secondary"], p["elevated"], p["text"], p["muted"]),
    }
    out = [f"# VOID Monochrome — KDE colour scheme. {HEADER}", "",
           "[ColorEffects:Disabled]", f"Color={rgb_csv(p['secondary'])}", "ColorAmount=0", "ColorEffect=0",
           "ContrastAmount=0.65", "ContrastEffect=1", "IntensityAmount=0.1", "IntensityEffect=2", "",
           "[ColorEffects:Inactive]", "ChangeSelectionColor=true", f"Color={rgb_csv(p['background'])}",
           "ColorAmount=0.025", "ColorEffect=2", "ContrastAmount=0.1", "ContrastEffect=2", "Enable=false",
           "IntensityAmount=0", "IntensityEffect=0", ""]
    for g, kv in groups.items():
        out.append(f"[{g}]")
        out += [f"{k}={rgb_csv(v)}" for k, v in kv.items()]
        out.append("")
    out += ["[General]", "ColorScheme=VOIDMonochrome", "Name=VOID Monochrome", "shadeSortColumn=true", "",
            "[KDE]", "contrast=4", "",
            "[WM]", f"activeBackground={rgb_csv(p['background'])}", f"activeBlend={rgb_csv(p['highlight'])}",
            f"activeForeground={rgb_csv(p['text'])}", f"inactiveBackground={rgb_csv(p['background'])}",
            f"inactiveBlend={rgb_csv(p['muted'])}", f"inactiveForeground={rgb_csv(p['muted'])}", ""]
    return "\n".join(out)


def btop_theme() -> str:
    p = pal()
    lo, mid, hi = p["border"], p["secondary_text"], p["highlight"]
    kv = {
        "main_bg": p["background"], "main_fg": p["text"], "title": p["highlight"], "hi_fg": p["highlight"],
        "selected_bg": p["elevated"], "selected_fg": p["highlight"], "inactive_fg": p["muted"],
        "graph_text": p["secondary_text"], "meter_bg": p["elevated"], "proc_misc": p["secondary_text"],
        "cpu_box": p["border"], "mem_box": p["border"], "net_box": p["border"], "proc_box": p["border"],
        "div_line": p["border"],
    }
    for g in ("temp", "cpu", "free", "cached", "available", "used", "download", "upload", "process"):
        kv.update({f"{g}_start": lo, f"{g}_mid": mid, f"{g}_end": hi})
    return "\n".join([f"# VOID — btop theme. {HEADER}"] + [f'theme[{k}]="{v}"' for k, v in kv.items()]) + "\n"


def alacritty_theme() -> str:
    p, t = pal(), load()["terminal"]
    lines = [f"# VOID — Alacritty theme. {HEADER}", "# Use it with: [general] import = [\"~/.config/alacritty/void.toml\"]", "",
             "[colors.primary]", f'background = "{p["background"]}"', f'foreground = "{p["text"]}"',
             f'bright_foreground = "{p["highlight"]}"', f'dim_foreground = "{p["muted"]}"', "",
             "[colors.cursor]", f'text = "{p["background"]}"', f'cursor = "{p["highlight"]}"', "",
             "[colors.selection]", f'text = "{p["background"]}"', f'background = "{p["text"]}"', ""]
    for sect, off in (("normal", 0), ("bright", 8)):
        lines.append(f"[colors.{sect}]")
        lines += [f'{n} = "{ansi(i + off)}"' for i, n in enumerate(ANSI_ORDER)]
        lines.append("")
    lines += ["[window]", f"opacity = {t['opacity']}", f"padding = {{ x = {t['padding']}, y = {t['padding']} }}", "",
              "[font]", f"size = {float(t['font_size'])}", f'normal = {{ family = "{t["font"]}" }}', ""]
    return "\n".join(lines)


def tmux_colors() -> str:
    p = pal()
    return "\n".join([
        f"# VOID — tmux colours. {HEADER}",
        f'set -g status-style "bg={p["background"]},fg={p["muted"]}"',
        f'set -g pane-border-style "fg={p["border"]},bg={p["background"]}"',
        f'set -g pane-active-border-style "fg={p["border"]},bg={p["background"]}"',
        f'set -g message-style "bg={p["elevated"]},fg={p["highlight"]}"',
        f'set -g message-command-style "bg={p["elevated"]},fg={p["highlight"]}"',
        f'set -g mode-style "bg={p["text"]},fg={p["background"]}"',
        f'set -g display-panes-colour "{p["muted"]}"',
        f'set -g display-panes-active-colour "{p["highlight"]}"',
        f'set -g clock-mode-colour "{p["highlight"]}"',
        f'set -g window-style "fg={p["text"]},bg={p["background"]}"',
        f'set -g window-active-style "fg={p["text"]},bg={p["background"]}"',
        f'set -g @void-muted "{p["muted"]}"',
        f'set -g @void-hi "{p["highlight"]}"',
        f'set -g @void-border "{p["border"]}"',
        "",
    ])


def cava_config() -> str:
    p = pal()
    return "\n".join([
        f"# VOID — CAVA (standalone: `bin/void cava`). {HEADER}",
        "# The dashboard does not run this file: void-core runs one raw-output CAVA and shares the spectrum.",
        "[general]", "framerate = 30", "bars = 0", "bar_width = 2", "bar_spacing = 1", "sleep_timer = 5", "",
        "[input]", "method = pipewire", "source = auto", "",
        "[output]", "method = ncurses", "",
        "[color]", f"background = '{p['background']}'", f"foreground = '{p['secondary_text']}'",
        "gradient = 1", "gradient_count = 3", f"gradient_color_1 = '{p['border']}'",
        f"gradient_color_2 = '{p['secondary_text']}'", f"gradient_color_3 = '{p['highlight']}'", "",
        "[smoothing]", "noise_reduction = 77", "monstercat = 1", "",
    ])


def spicetify_colors() -> str:
    sp = load()["spotify"]
    width = max(len(k) for k in sp)
    lines = [f"; VOID — Spicetify colour scheme. {HEADER}",
             "; These keys become Spotify's --spice-* / --spice-rgb-* CSS variables.", "", "[VOID]"]
    lines += [f"{k:<{width}} = {resolve(v).lstrip('#').upper()}" for k, v in sp.items()]
    return "\n".join(lines) + "\n"


def fastfetch_config() -> str:
    """fastfetch config template; @LOGO@ is replaced with the absolute logo path when installed."""
    p = pal()
    keys = [("os", "OS"), ("kernel", "KERNEL"), ("uptime", "UPTIME"), ("de", "PLASMA"), ("wm", "KWIN"),
            ("cpu", "CPU"), ("gpu", "GPU"), ("memory", "RAM"), ("disk", "STORAGE"), ("terminal", "TERMINAL"),
            ("display", "DISPLAY")]
    width = max(len(k) for _, k in keys) + 1
    mods: list = ["title", {"type": "separator", "string": "─"}]
    for typ, key in keys:
        m = {"type": typ, "key": f"{key:<{width}}"}
        if typ == "disk":
            m["folders"] = "/"
        mods.append(m)
    mods += ["break", {"type": "colors", "symbol": "block", "paddingLeft": 0}]
    doc = {
        "$schema": "https://github.com/fastfetch-cli/fastfetch/raw/dev/doc/json_schema.json",
        "logo": {"type": "file", "source": "@LOGO@",
                 "color": {"1": sgr(p["highlight"]), "2": sgr(p["muted"]), "3": sgr(p["border"])},
                 "padding": {"top": 1, "left": 2, "right": 4}},
        "display": {"separator": " ▸ ", "disableLinewrap": True,
                    "color": {"keys": sgr(p["muted"]), "title": sgr(p["highlight"]),
                              "output": sgr(p["text"]), "separator": sgr(p["border"])}},
        "modules": mods,
    }
    return f"// VOID — fastfetch. {HEADER}\n" + json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


OUTPUTS = {
    "config/konsole/Void.colorscheme": konsole_scheme,
    "config/kde/VOIDMonochrome.colors": kde_colors,
    "config/btop/void.theme": btop_theme,
    "config/alacritty/void.toml": alacritty_theme,
    "config/tmux/colors.conf": tmux_colors,
    "config/cava/void": cava_config,
    "config/fastfetch/void.jsonc.in": fastfetch_config,
    "spicetify/Themes/VOID/color.ini": spicetify_colors,
}


def stale() -> list[str]:
    return [rel for rel, fn in OUTPUTS.items()
            if not (paths.PROJECT_DIR / rel).exists() or (paths.PROJECT_DIR / rel).read_text() != fn()]


def build() -> list[str]:
    changed = []
    for rel, fn in OUTPUTS.items():
        dest = paths.PROJECT_DIR / rel
        text = fn()
        if not dest.exists() or dest.read_text() != text:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text)
            changed.append(rel)
    return changed


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    if cmd == "build":
        for rel in build():
            print(f"wrote {rel}")
        return 0
    if cmd == "check":
        bad = stale()
        for rel in bad:
            print(f"stale: {rel} (run: bin/void tokens build)", file=sys.stderr)
        return 1 if bad else 0
    if cmd == "contrast":
        p = pal()
        for k, v in p.items():
            print(f"{k:16} {v}  {contrast(v, p['background']):5.2f}:1 on background")
        return 0
    print("usage: void tokens build|check|contrast", file=sys.stderr)
    return 2
