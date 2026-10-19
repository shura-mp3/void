"""Kitty: VOID's Kitty configuration (a monochrome port of Crimson Desktop's), launch modes, and
the reversible "every Kitty is VOID" switch used by activation.

  void kitty [shell|lyrics|music|cava|fetch|dashboard]   (also scripts/launch-kitty.sh)
      opens Kitty with your kitty.conf + VOID's void.conf on top — works whether or not VOID is
      active and never edits kitty.conf.

Kitty applies settings in order, so a block appended at the END of kitty.conf overrides anything
before it — including Crimson's `include crimson.conf`, which stays where it is. Deactivation removes
only VOID's marked block; the rest of kitty.conf (and any edit you made meanwhile) is left alone.
Running Kitty windows reload their config on SIGUSR1.
"""

from __future__ import annotations

from pathlib import Path

from .. import paths
from . import files, ui
from .journal import ABSENT, Handler, register

KITTY_DIR = paths.XDG_CONFIG / "kitty"
CONF = KITTY_DIR / "kitty.conf"
THEME = KITTY_DIR / "void.conf"
PROFILE = KITTY_DIR / "void-profile.conf"   # background opacity per VOID profile (like crimson-profile.conf)
BEGIN = "# >>> VOID — added by `void activate`, removed by `void deactivate` (keep it last: later lines win)"
END = "# <<< VOID"
BLOCK = f"{BEGIN}\ninclude void.conf\n{END}\n"


def wanted() -> bool:
    """Theme Kitty when it is installed or has a config directory."""
    return ui.have("kitty") or KITTY_DIR.is_dir()


def theme_text() -> str:
    text = (paths.CONFIG_SRC / "kitty" / "void.conf.in").read_text()
    return text.replace("@VOID_BIN@", str(paths.PROJECT_DIR / "bin" / "void")) \
               .replace("@VOID_SHELL@", str(paths.PROJECT_DIR / "bin" / "void-shell"))


def install() -> None:
    files.install(THEME, theme_text())
    write_profile()


def write_profile(profile: str | None = None) -> None:
    """Opacity for the current VOID profile: minimal = opaque (cheapest to composite)."""
    from .. import config, tokens
    profile = profile or config.current_profile()
    op = 1.0 if profile == "minimal" else tokens.load()["terminal"]["opacity"]
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(f"# written by VOID (`void profile`) — {profile} profile\nbackground_opacity {op}\n")


def reload() -> None:
    """Running Kitty windows re-read their config on SIGUSR1."""
    if ui.run(["pgrep", "-x", "kitty"])[0] == 0:
        ui.run(["pkill", "-USR1", "-x", "kitty"])


MODES = {
    "shell": ([], []),
    "lyrics": (["--class", "void-lyrics", "--title", "VOID // LYRICS"], ["lyrics"]),
    "music": (["--class", "void-music", "--title", "VOID // MUSIC"], ["music"]),
    "cava": (["--class", "void-cava", "--title", "VOID // SPECTRUM"], ["cava"]),
    "fetch": (["--hold", "--title", "VOID // GEASS"], ["fetch"]),
}


def command(mode: str = "shell") -> list[str]:
    """The kitty command line for a VOID launch mode (your kitty.conf, then VOID's on top)."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r} (one of {', '.join(MODES)}, dashboard)")
    install()
    confs = (["--config", str(CONF)] if CONF.exists() else []) + ["--config", str(THEME)]
    extra, args = MODES[mode]
    tail = [str(paths.PROJECT_DIR / "bin" / "void"), *args] if args else []
    return ["kitty", *confs, *extra, *tail]


def main(argv: list[str]) -> int:
    import subprocess
    mode = argv[0] if argv else "shell"
    if mode in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if not ui.have("kitty"):
        if mode in ("lyrics", "music") and ui.have("konsole"):
            # the Meta+Alt+L shortcut still works without Kitty: same view in a VOID Konsole window
            subprocess.Popen(["konsole", "--profile", "VOID", "-e", str(paths.PROJECT_DIR / "bin" / "void"), mode],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            ui.info(f"kitty is not installed — opened {mode} in Konsole")
            return 0
        ui.bad("kitty is not installed")
        return 1
    if mode == "dashboard":
        from .. import config
        from . import switch
        cfg = config.load()
        cfg["dashboard"]["terminal"] = "kitty"
        return switch.launch([], cfg=cfg)
    try:
        cmd = command(mode)
    except ValueError as e:
        ui.bad(str(e))
        return 2
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    ui.ok(f"kitty ({mode}) opened")
    return 0


def _strip(text: str) -> str:
    out, skip = [], False
    for line in text.splitlines(keepends=True):
        if line.rstrip("\n") == BEGIN:
            skip = True
            continue
        if skip and line.rstrip("\n") == END:
            skip = False
            continue
        if not skip:
            out.append(line)
    return "".join(out)


@register
class KittyInclude(Handler):
    """key = path of kitty.conf. value: True (VOID block present), False (absent), ABSENT (no file)."""
    kind = "kitty"

    def get(self, key):
        p = Path(key)
        if not p.exists():
            return ABSENT
        return BEGIN in p.read_text().splitlines()

    def set(self, key, value):
        p = Path(key)
        cur = p.read_text() if p.exists() else ""
        base = _strip(cur)
        if value is True:
            new = base + ("" if not base or base.endswith("\n") else "\n") + BLOCK
        else:
            new = base
            if value == ABSENT and not new.strip():
                p.unlink(missing_ok=True)
                return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new)

    def describe(self, key):
        return "Kitty theme (VOID block in kitty.conf)"
