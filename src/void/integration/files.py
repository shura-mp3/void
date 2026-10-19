"""Installing VOID-owned files without ever clobbering someone else's.

Every file VOID writes outside the project is listed with its sha256 in
~/.local/state/void-desktop/installed.json. A later install replaces a file only if it is still
byte-identical to what VOID wrote; `void restore --uninstall` removes only such files.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .. import paths
from ..config import JsonState
from . import ui

MANIFEST = paths.STATE_DIR / "installed.json"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest() -> JsonState:
    return JsonState(MANIFEST, {"files": {}})


def is_ours(p: Path) -> bool:
    rec = _manifest().data["files"].get(str(p))
    return bool(rec) and p.exists() and sha(p) == rec


def install(dest: Path, content: str | bytes, mode: int | None = None, quiet: bool = False) -> bool:
    """Write dest if missing or still ours. Returns True if written; False if unchanged or kept."""
    data = content.encode() if isinstance(content, str) else content
    m = _manifest()
    if dest.exists():
        if dest.read_bytes() == data:
            m.data["files"][str(dest)] = sha(dest)
            m.save()
            return False
        if not is_ours(dest):
            ui.warn(f"kept {short(dest)} — it exists and was not written by VOID (rename it to let VOID install its own)")
            return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".void-tmp")
    tmp.write_bytes(data)
    if mode is not None:
        tmp.chmod(mode)
    tmp.replace(dest)
    m.data["files"][str(dest)] = sha(dest)
    m.save()
    if not quiet:
        ui.ok(f"installed {short(dest)}")
    return True


def uninstall_all() -> list[str]:
    m = _manifest()
    removed = []
    for path, digest in list(m.data["files"].items()):
        p = Path(path)
        if p.exists() and sha(p) == digest:
            p.unlink()
            removed.append(path)
            del m.data["files"][path]
        elif not p.exists():
            del m.data["files"][path]
        else:
            ui.warn(f"kept {short(p)} (edited since VOID installed it)")
    m.save()
    return removed


def short(p: Path | str) -> str:
    return str(p).replace(str(paths.HOME), "~", 1)
