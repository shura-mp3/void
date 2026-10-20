"""Real Kitty grid dashboard at 1920x1080. Run under xvfb-run (X display) in a sandboxed $HOME.

Starts the exact command `void launch` uses for the grid layout, waits for the tiles, captures the X
root window with ImageMagick, and prints JSON: which tile ended up in which quadrant (from kitty's
own window list), and whether every pixel is grey.
    python3 grid_check.py OUT.png
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from void import config  # noqa: E402
from void.dashboard import grid  # noqa: E402

out = os.path.abspath(sys.argv[1])
sock = Path(os.environ["HOME"]) / "kitty.sock"
cmd = grid.command(config.load()) + ["-o", "allow_remote_control=yes", "--listen-on", f"unix:{sock}",
                                     "-o", "initial_window_width=1920", "-o", "initial_window_height=1080"]
env = dict(os.environ, LIBGL_ALWAYS_SOFTWARE="1", SHELL="/bin/bash")
k = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=open(Path(os.environ["HOME"]) / "kitty.log", "w"))
time.sleep(10)
subprocess.run(["import", "-window", "root", out], check=True)
ls = subprocess.run(["kitty", "@", "--to", f"unix:{sock}", "ls"], capture_output=True, text=True).stdout
k.terminate()
tiles = {}
for osw in json.loads(ls or "[]"):
    for tab in osw["tabs"]:
        for w in tab["windows"]:
            g = w.get("lines"), w.get("columns")
            tiles[w["title"]] = {"id": w["id"], "lines": g[0], "columns": g[1],
                                 "cmd": " ".join(w.get("foreground_processes", [{}])[0].get("cmdline", [])[:3])}
from PIL import Image  # noqa: E402
im = Image.open(out).convert("RGB")
small = im.resize((480, 270))
px = list(small.get_flattened_data() if hasattr(small, "get_flattened_data") else small.getdata())
print(json.dumps({"tiles": tiles, "nongrey": sum(1 for r, g, b in px if max(r, g, b) - min(r, g, b) > 6),
                  "log": (Path(os.environ["HOME"]) / "kitty.log").read_text()[-400:]}))
