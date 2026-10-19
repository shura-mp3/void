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
    """void wallpaper [--pick FILE] — rank the pack and make the monochrome copies (does not set it)."""
    from .. import config
    from . import monitors, wallpaper
    pick = argv[argv.index("--pick") + 1] if "--pick" in argv and argv.index("--pick") + 1 < len(argv) else None
    res = wallpaper.prepare(config.load(), monitors.detect().get("target"), pick=pick, interactive=False)
    if res:
        print("  `void activate` sets it on the right-hand monitor (re-run activate after changing the pick)")
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
    "autostart": _switch("autostart"),
    "status": _switch("status"),
    "inspect": _system("inspect"),
    "install": _system("install"),
    "health": _system("health"),
    "doctor": _system("health"),
    "monitors": _monitors,
    "wallpaper": _wallpaper,
    "konsole": _konsole,
    "spotify": _spotify,
}
