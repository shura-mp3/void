"""VOID — monochrome workstation for KDE Plasma.

  switching      activate · deactivate · restore [--list] · status
  dashboard      launch · stop · dashboard build|attach|respawn|kill|status
  panes          music · clock · rain · sysmon · fetch · pane <name>
  look           profile minimal|balanced|showcase · tokens build|check|contrast
  system         inspect · install · health · monitors · wallpaper · core
  apps           konsole apply|remove|status · spotify inspect|status|apply|revert · autostart on|off|status
"""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    cmd, rest = (argv[0], argv[1:]) if argv else ("help", [])
    if cmd == "tokens":
        from . import tokens
        return tokens.main(rest)
    if cmd == "core":
        from . import core
        sys.argv = ["void-core", *rest]
        core.main()
        return 0
    if cmd in ("music", "clock", "rain", "sysmon", "fetch"):
        import importlib
        return importlib.import_module(f".dashboard.{cmd}", __package__).main(rest)
    if cmd == "pane":
        from .dashboard import session
        return session.run_pane(rest[0] if rest else "")
    if cmd == "dashboard":
        from .dashboard import session
        return session.main(rest)
    from .integration import commands
    handler = commands.COMMANDS.get(cmd)
    if handler:
        return handler(rest) or 0
    print(__doc__)
    return 0 if cmd in ("help", "-h", "--help") else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
