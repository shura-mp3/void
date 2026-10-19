"""Global shortcuts: Crimson's Meta+Alt keys handed to VOID while VOID is active.

Crimson binds Meta+Alt+D/L/P/[/] to crimsonctl and crimson-lyrics — run while VOID is active they
would start crimson-core next to void-core. Activation sets those bindings to none and puts VOID's
equivalents on the same keys; both changes are journaled, so `void deactivate` gives Crimson its keys
back. KDE's global-shortcut service reads kglobalshortcutsrc when the session starts, so the swap is
complete after the next login (System Settings → Shortcuts shows it).
"""

from __future__ import annotations

from .. import paths
from . import files, kde, ui

APPS = paths.XDG_DATA / "applications"
# (desktop id, name, command args, key) — same keys Crimson used
SHORTCUTS = [
    ("void-dashboard-toggle.desktop", "VOID: Show/Hide Dashboard", ["toggle"], "Meta+Alt+D"),
    ("void-lyrics.desktop", "VOID Lyrics", ["kitty", "lyrics"], "Meta+Alt+L"),
    ("void-profile-cycle.desktop", "VOID: Next Performance Profile", ["profile", "next"], "Meta+Alt+P"),
    ("void-offset-plus.desktop", "VOID: Lyrics Earlier (+100 ms)", ["offset", "+100"], "Meta+Alt+]"),
    ("void-offset-minus.desktop", "VOID: Lyrics Later (-100 ms)", ["offset", "-100"], "Meta+Alt+["),
]
CRIMSON_IDS = ["crimson-dashboard-toggle.desktop", "crimson-lyrics.desktop", "crimson-profile-cycle.desktop",
               "crimson-offset-plus.desktop", "crimson-offset-minus.desktop"]


def key(desktop_id: str) -> str:
    return kde.kkey("kglobalshortcutsrc", f"services>{desktop_id}", "_launch")


def install() -> None:
    bin_void = paths.PROJECT_DIR / "bin" / "void"
    for did, name, args, _ in SHORTCUTS:
        files.install(APPS / did, "\n".join([
            "[Desktop Entry]", "Type=Application", f"Name={name}", f"Exec={bin_void} {' '.join(args)}",
            "Icon=view-media-lyrics" if "lyrics" in did else "preferences-desktop-theme",
            "NoDisplay=true" if "lyrics" not in did else "Categories=AudioVideo;Audio;",
            "X-KDE-GlobalAccel-CommandShortcut=true", ""]), quiet=True)
    if ui.have("update-desktop-database"):
        ui.run(["update-desktop-database", str(APPS)])


def apply(j) -> list[str]:
    """Journal the swap. Returns the Crimson bindings that were set aside."""
    from .journal import ABSENT
    install()
    freed = []
    for did in CRIMSON_IDS:
        cur = kde.kread("kglobalshortcutsrc", f"services>{did}", "_launch")
        if cur != ABSENT and cur.strip().lower() not in ("", "none"):
            j.change("kconfig", key(did), "none", "Crimson shortcut set aside while VOID is active")
            freed.append(f"{cur} ({did.removesuffix('.desktop')})")
    for did, _, _, combo in SHORTCUTS:
        j.change("kconfig", key(did), combo, "VOID global shortcut")
    return freed
