"""Integration commands for `void <command>`."""

from __future__ import annotations


def _switch(name):
    def run(argv):
        from . import switch
        return getattr(switch, name)(argv)
    return run


def _system(name):
    def run(argv):
        from . import system
        return getattr(system, name)(argv)
    return run


def _monitors(argv):
    from . import monitors
    res = monitors.detect()
    monitors.print_table(res)
    if "--save" in argv:
        monitors.save(res)
    return 0 if res.get("target") else 1


def _wallpaper(argv):
    """void wallpaper [--pick FILE | --left FILE --right FILE]   rank the pack, render both screens (sets nothing)
    void wallpaper verify                                      read both wallpapers back from Plasma"""
    import json
    from .. import config, paths
    from . import monitors, ui, wallpaper

    def opt(name):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else ""
    if argv and argv[0] == "verify":
        try:
            res = json.loads(paths.WALLPAPER_STATE.read_text())
        except (OSError, ValueError):
            ui.bad("no VOID wallpapers recorded yet (void wallpaper, then void activate)")
            return 1
        probs = wallpaper.verify(res)
        for name, v in res.get("screens", {}).items():
            print(f"  {name:10} at {v['x']},{v['y']}  {v['image']}")
        for pr in probs:
            ui.bad(pr)
        if not probs:
            ui.ok("Plasma shows the VOID wallpaper on every monitor")
        return 1 if probs else 0
    mon = monitors.detect()
    monitors.print_table(mon)
    res = wallpaper.prepare(config.load(), [o for o in mon["outputs"] if o["enabled"]], mon.get("target"),
                            picks={"all": opt("--pick"), "left": opt("--left"), "right": opt("--right")}, interactive=False)
    if res:
        print("  `void activate` applies them (run it again after changing the pick while VOID is active)")
    return 0 if res else 1


def _konsole(argv):
    from . import konsole, ui
    cmd = argv[0] if argv else "status"
    if cmd == "apply":
        konsole.install()
        ui.info("profiles installed; `void activate` makes VOID the default profile")
    else:
        for f in (konsole.KONSOLE_DIR / "Void.colorscheme", konsole.KONSOLE_DIR / konsole.PROFILE,
                  konsole.KONSOLE_DIR / konsole.DASH_PROFILE):
            print(f"  {f}: {'installed' if f.exists() else 'missing'}")
    return 0


def _kitty(argv):
    from . import kitty
    return kitty.main(argv)


def _spotify(argv):
    from . import spotify
    return spotify.main(argv)


COMMANDS = {
    "activate": _switch("activate"),
    "deactivate": _switch("deactivate"),
    "restore": _switch("restore"),
    "launch": _switch("launch"),
    "stop": _switch("stop"),
    "profile": _switch("profile"),
    "toggle": _switch("toggle"),
    "offset": _switch("offset"),
    "autostart": _switch("autostart"),
    "status": _switch("status"),
    "inspect": _system("inspect"),
    "install": _system("install"),
    "health": _system("health"),
    "doctor": _system("health"),
    "monitors": _monitors,
    "wallpaper": _wallpaper,
    "konsole": _konsole,
    "kitty": _kitty,
    "spotify": _spotify,
}
