"""Monitor detection via KScreen (kscreen-doctor). Read-only: VOID never changes resolution,
refresh rate, scaling or arrangement.

The dashboard monitor is the physically right-most enabled output by KScreen position — never
guessed from connector names. Override with [dashboard] monitor = "DP-2" in config.toml.
"""

from __future__ import annotations

import json
import re

from .. import config, paths
from . import ui

TARGET = (1920, 1080)


def from_json(raw: str) -> list[dict]:
    data = json.loads(raw)
    outs = []
    for o in data.get("outputs", []):
        if not o.get("connected", True):
            continue
        mode = next((m for m in o.get("modes", []) if str(m.get("id")) == str(o.get("currentModeId"))), {})
        msize = mode.get("size") or o.get("size") or {}
        w, h = int(msize.get("width", 0)), int(msize.get("height", 0))
        scale = float(o.get("scale", 1.0) or 1.0)
        rot = int(o.get("rotation", 1) or 1)  # 1 none, 2 left(90), 4 inverted, 8 right(270)
        lw, lh = (h, w) if rot in (2, 8) else (w, h)
        outs.append({
            "name": o.get("name"), "enabled": bool(o.get("enabled", False)),
            "x": int((o.get("pos") or {}).get("x", 0)), "y": int((o.get("pos") or {}).get("y", 0)),
            "width": w, "height": h, "logical_width": round(lw / scale), "logical_height": round(lh / scale),
            "refresh": round(float(mode.get("refreshRate", 0) or 0), 2), "scale": scale, "rotation": rot,
            "primary": o.get("priority") == 1 or bool(o.get("primary")),
        })
    return outs


def from_text(raw: str) -> list[dict]:
    raw = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    outs = []
    for block in re.split(r"\n(?=Output:)", raw):
        m = re.match(r"Output:\s+\d+\s+(\S+)", block)
        if not m or " connected" not in block:
            continue
        geo = re.search(r"Geometry:\s*(-?\d+),(-?\d+)\s+(\d+)x(\d+)", block)
        scale = re.search(r"Scale:\s*([\d.]+)", block)
        cur = re.search(r"\d+:(\d+)x(\d+)@([\d.]+)\*", block)
        prio = re.search(r"priority\s+(\d+)", block)
        outs.append({
            "name": m.group(1), "enabled": " enabled" in block.split("\n")[0],
            "x": int(geo.group(1)) if geo else 0, "y": int(geo.group(2)) if geo else 0,
            "width": int(cur.group(1)) if cur else 0, "height": int(cur.group(2)) if cur else 0,
            "logical_width": int(geo.group(3)) if geo else 0, "logical_height": int(geo.group(4)) if geo else 0,
            "refresh": float(cur.group(3)) if cur else 0.0, "scale": float(scale.group(1)) if scale else 1.0,
            "rotation": 1, "primary": bool(prio and prio.group(1) == "1"),
        })
    return outs


def detect(cfg: dict | None = None) -> dict:
    cfg = cfg or config.load()
    res = {"outputs": [], "target": None, "method": None, "arrangement": "none", "notes": []}
    if not ui.have("kscreen-doctor"):
        res["error"] = "kscreen-doctor not found (part of Plasma's kscreen package)"
        return res
    rc, out = ui.run(["kscreen-doctor", "-j"])
    outs = []
    if rc == 0 and out.lstrip().startswith("{"):
        try:
            outs, res["method"] = from_json(out[out.index("{"):]), "kscreen-doctor -j"
        except (ValueError, KeyError, TypeError):
            outs = []
    if not outs:
        rc, out = ui.run(["kscreen-doctor", "-o"])
        outs, res["method"] = from_text(out), "kscreen-doctor -o"
    res["outputs"] = outs
    enabled = [o for o in outs if o["enabled"]]
    want = cfg["dashboard"].get("monitor", "auto")
    target = None
    if want and want != "auto":
        target = next((o for o in enabled if o["name"] == want), None)
        if not target:
            res["notes"].append(f"configured monitor {want!r} not found; using the right-most")
    if not target and enabled:
        xs = {o["x"] for o in enabled}
        res["arrangement"] = "horizontal" if len(xs) > 1 else ("vertical" if len(enabled) > 1 else "single")
        target = max(enabled, key=lambda o: (o["x"], o["y"])) if len(xs) > 1 else max(enabled, key=lambda o: o["y"])
        if len(enabled) == 1:
            res["notes"].append("only one monitor is enabled — the dashboard uses it")
        elif res["arrangement"] == "vertical":
            res["notes"].append("monitors are stacked, not side by side — using the lower one")
    res["target"] = target
    if target and (target["width"], target["height"]) != TARGET:
        res["notes"].append(f"{target['name']} runs {target['width']}x{target['height']} (VOID is tuned for 1920x1080 "
                            "and adapts; your display settings are left as they are)")
    return res


def save(res: dict) -> None:
    st = config.JsonState(paths.MONITORS_FILE)
    st.data = res
    st.save()


def print_table(res: dict) -> None:
    if res.get("error"):
        ui.bad(res["error"])
        return
    tgt = (res.get("target") or {}).get("name")
    print(f"  detected with {res['method']}   arrangement: {res['arrangement']}")
    for o in res["outputs"]:
        role = "DASHBOARD →" if o["name"] == tgt else ""
        print(f"  {role:12}{o['name']:10} {o['width']}x{o['height']}@{o['refresh']:<7} logical {o['logical_width']}x"
              f"{o['logical_height']:<5} at {o['x']},{o['y']}  scale {o['scale']}{'  primary' if o['primary'] else ''}"
              f"{'' if o['enabled'] else '  (disabled)'}")
    for n in res["notes"]:
        ui.info(n)
