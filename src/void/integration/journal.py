"""Write-ahead journal of every setting VOID changes — the basis of safe, reversible switching.

Two records are kept under ~/.local/state/void-desktop/switch/:

  session.json   the values from just before the CURRENT activation (could be Crimson's look).
                 `void deactivate` puts these back, then archives the file to history/.
  original.json  the values from before VOID first touched each setting, ever. Never overwritten
                 by later activations. `void restore` returns to these.

Each change is recorded *before* it is made, so after a crash or a partly failed activation the
journal still knows how to undo exactly what happened. Reverting a setting that you changed by
hand while VOID was active is skipped (your newer value wins) unless --force is given.

A setting is addressed as (kind, key); each kind has a handler with get(key) and set(key, value).
ABSENT means "the setting did not exist" and set(key, ABSENT) deletes it.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
from pathlib import Path
from typing import Any, Callable

from .. import paths

ABSENT = {"__void__": "absent"}
DIR = paths.STATE_DIR / "switch"


class Handler:
    kind = ""

    def get(self, key: str) -> Any:
        raise NotImplementedError

    def set(self, key: str, value: Any) -> None:
        raise NotImplementedError

    def describe(self, key: str) -> str:
        return f"{self.kind} {key}"


HANDLERS: dict[str, Handler] = {}


def register(cls: type[Handler]) -> type[Handler]:
    HANDLERS[cls.kind] = cls()
    return cls


def show(value: Any) -> str:
    if value == ABSENT:
        return "(unset)"
    s = json.dumps(value) if not isinstance(value, str) else value
    return s if len(s) <= 60 else s[:57] + "…"


def _load(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def _save(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(p)


class Journal:
    def __init__(self, root: Path | None = None):
        self.dir = root or DIR
        self.session_file = self.dir / "session.json"
        self.original_file = self.dir / "original.json"
        self.state_file = self.dir / "state.json"
        self._lock = None

    # ---------------------------------------------------------------- locking / status
    def lock(self) -> "Journal":
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = open(self.dir / ".lock", "w")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("another VOID activate/deactivate/restore is running — wait for it to finish")
        return self

    @property
    def state(self) -> dict:
        return _load(self.state_file, {"status": "inactive"})

    @property
    def status(self) -> str:
        return self.state.get("status", "inactive")

    def set_status(self, status: str, **extra) -> None:
        st = {**self.state, "status": status, "since": dt.datetime.now().isoformat(timespec="seconds"), **extra}
        if status in ("inactive", "active"):
            st.pop("error", None)
        _save(self.state_file, st)

    # ---------------------------------------------------------------- records
    def entries(self) -> list[dict]:
        return _load(self.session_file, [])

    def original(self) -> list[dict]:
        return _load(self.original_file, [])

    def _upsert(self, file: Path, kind: str, key: str, update: Callable[[dict | None], dict | None]) -> None:
        data = _load(file, [])
        for i, e in enumerate(data):
            if e["kind"] == kind and e["key"] == key:
                new = update(e)
                if new is not None:
                    data[i] = new
                break
        else:
            new = update(None)
            if new is None:
                return
            data.append(new)
        _save(file, data)

    def change(self, kind: str, key: str, value: Any, note: str = "") -> bool:
        """Record then apply. Returns True if the live value actually changed."""
        h = HANDLERS[kind]
        current = h.get(key)
        stamp = dt.datetime.now().isoformat(timespec="seconds")
        self._upsert(self.session_file, kind, key, lambda e: (
            {"kind": kind, "key": key, "previous": current, "applied": value, "note": note, "time": stamp}
            if e is None else {**e, "applied": value}))
        self._upsert(self.original_file, kind, key, lambda e: (
            {"kind": kind, "key": key, "value": current, "note": note, "time": stamp} if e is None else None))
        if current == value:
            return False
        h.set(key, value)
        return True

    # ---------------------------------------------------------------- undo
    def _revert(self, items: list[tuple[dict, Any, Any]], force: bool, report: Callable[[str, dict, Any, Any], None]) -> int:
        """items: (entry, target value, value VOID applied). Returns number of failures."""
        failures = 0
        for e, target, applied in items:
            h = HANDLERS.get(e["kind"])
            if h is None:
                report("unknown", e, None, target)
                failures += 1
                continue
            try:
                current = h.get(e["key"])
                if current == target:
                    report("same", e, current, target)
                elif applied is not None and current != applied and not force:
                    report("kept", e, current, target)
                else:
                    h.set(e["key"], target)
                    report("restored", e, current, target)
            except Exception as ex:  # noqa: BLE001 - keep going: undo as much as possible
                report("failed", e, str(ex), target)
                failures += 1
        return failures

    def revert_session(self, force: bool = False, report=lambda *a: None) -> int:
        entries = self.entries()
        fails = self._revert([(e, e["previous"], e["applied"]) for e in reversed(entries)], force, report)
        if entries and not fails:
            hist = self.dir / "history"
            hist.mkdir(parents=True, exist_ok=True)
            self.session_file.replace(hist / f"{dt.datetime.now():%Y%m%d-%H%M%S}-session.json")
        return fails

    def restore_original(self, force: bool = True, report=lambda *a: None) -> int:
        orig = self.original()
        fails = self._revert([(e, e["value"], None) for e in reversed(orig)], force, report)
        if orig and not fails:
            # the desktop is back to its pre-VOID state: the next activation records a fresh original
            hist = self.dir / "history"
            hist.mkdir(parents=True, exist_ok=True)
            self.original_file.replace(hist / f"{dt.datetime.now():%Y%m%d-%H%M%S}-original.json")
        return fails
