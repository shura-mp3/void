#!/usr/bin/env python3
"""Test stub for kwriteconfig6 / kreadconfig6 (KDE INI with [Group][Sub] headers)."""
import os, sys
from pathlib import Path
args = sys.argv[1:]
file = groups = key = None; groups = []; delete = False; default = ""; value = None
i = 0
while i < len(args):
    a = args[i]
    if a == "--file": file = args[i + 1]; i += 2
    elif a == "--group": groups.append(args[i + 1]); i += 2
    elif a == "--key": key = args[i + 1]; i += 2
    elif a == "--default": default = args[i + 1]; i += 2
    elif a == "--delete": delete = True; i += 1
    elif a == "--type": i += 2
    else: value = a; i += 1
path = Path(file) if file.startswith("/") else Path(os.environ["HOME"]) / ".config" / file
hdr = "".join(f"[{g}]" for g in groups)
data = {}; order = []
cur = None
if path.exists():
    for line in path.read_text().splitlines():
        if line.startswith("["):
            cur = line.strip(); data.setdefault(cur, {}); order.append(cur) if cur not in order else None
        elif "=" in line and cur is not None:
            k, v = line.split("=", 1); data[cur][k] = v
if "kread" in sys.argv[0]:
    print(data.get(hdr, {}).get(key, default)); sys.exit(0)
data.setdefault(hdr, {})
if hdr not in order: order.append(hdr)
if delete: data[hdr].pop(key, None)
else: data[hdr][key] = value
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text("\n".join(f"{g}\n" + "".join(f"{k}={v}\n" for k, v in data[g].items()) for g in order))
