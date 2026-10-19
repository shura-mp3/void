"""Konsole: the VOID colour scheme and two profiles, plus Alacritty theme files if Alacritty exists.

  VOID              everyday profile: VOID colours, VOID shell layer (bin/void-shell) on top of
                    your normal shell, Geass fastfetch once per window. Made the default profile
                    only while VOID is active (konsolerc DefaultProfile is journaled).
  VOID Dashboard    used only by `void launch`: smaller font, fixed title VOID//DASHBOARD (the
                    KWin rule matches it), attaches to the tmux dashboard.

Existing profiles — including Crimson's — are never edited. tmux is never started automatically
in ordinary Konsole windows.
"""

from __future__ import annotations

from .. import paths, tokens
from . import files, kde, ui

KONSOLE_DIR = paths.XDG_DATA / "konsole"
PROFILE = "VOID.profile"
DASH_PROFILE = "VOID Dashboard.profile"


def _font(size: int) -> str:
    fam = kde.mono_font() or "Monospace"
    return f"{fam},{size},-1,5,400,0,0,0,0,0,0,0,0,0,0,1"


def profile_text(dashboard: bool = False) -> str:
    t = tokens.load()["terminal"]
    bin_dir = paths.PROJECT_DIR / "bin"
    lines = [
        "# VOID — Konsole profile (installed by VOID; edits are kept: VOID won't overwrite a changed file).",
        "[Appearance]", "ColorScheme=Void", f"Font={_font(t['dashboard_font_size'] if dashboard else t['font_size'])}",
        "LineSpacing=0", "UseFontLineChararacters=true", "AntiAliasFonts=true", "BoldIntense=true", "",
        "[Cursor Options]", "CursorShape=0", "UseCustomCursorColor=false", "",
        "[General]",
        f"Command={bin_dir / 'void'} dashboard attach" if dashboard else f"Command={bin_dir / 'void-shell'}",
        "Environment=TERM=xterm-256color,COLORTERM=truecolor",
        "LocalTabTitleFormat=" + (kde.DASH_TITLE if dashboard else "VOID // %d : %n"),
        "RemoteTabTitleFormat=" + (kde.DASH_TITLE if dashboard else "VOID // %h : %u"),
        f"Name={'VOID Dashboard' if dashboard else 'VOID'}", "Parent=FALLBACK/",
        f"TerminalMargin={4 if dashboard else t['padding']}", "TerminalCenter=true",
        "TerminalColumns=140", "TerminalRows=40", "ShowTerminalSizeHint=false", "",
        "[Interaction Options]", "AutoCopySelectedText=false", "TrimLeadingSpacesInSelectedText=true", "",
        "[Scrolling]", f"HistoryMode={0 if dashboard else 1}", "HistorySize=10000", "ScrollBarPosition=2", "",
        "[Terminal Features]", "BlinkingCursorEnabled=false", "UrlHintsModifiers=0", "",
    ]
    return "\n".join(lines)


def install() -> None:
    files.install(KONSOLE_DIR / "Void.colorscheme", tokens.konsole_scheme())
    files.install(KONSOLE_DIR / PROFILE, profile_text())
    files.install(KONSOLE_DIR / DASH_PROFILE, profile_text(dashboard=True))
    if ui.have("alacritty"):
        files.install(paths.XDG_CONFIG / "alacritty" / "void.toml", tokens.alacritty_theme())
        ui.info('Alacritty: theme at ~/.config/alacritty/void.toml — your alacritty.toml is untouched '
                '(add it under [general] import = ["~/.config/alacritty/void.toml"] if you want it everywhere)')


def default_profile_key() -> str:
    return kde.kkey("konsolerc", "Desktop Entry", "DefaultProfile")


def alacritty_dashboard_config() -> str:
    """Full config for the dashboard window when Alacritty is used instead of Konsole."""
    t = tokens.load()["terminal"]
    lines = [f"# VOID dashboard window (Alacritty). {tokens.HEADER}", ""] + tokens.alacritty_colors() + [
        "[window]", f'title = "{kde.DASH_TITLE}"', "dynamic_title = false", 'decorations = "None"',
        f"opacity = {t['opacity']}", "padding = { x = 4, y = 4 }", "",
        "[font]", f"size = {float(t['dashboard_font_size'])}", f'normal = {{ family = "{t["font"]}" }}', ""]
    dest = paths.GENERATED / "alacritty-dashboard.toml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines))
    return str(dest)
