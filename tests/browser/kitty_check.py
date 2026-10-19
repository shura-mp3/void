"""Real Kitty, real pixels. Runs INSIDE `dbus-run-session` with $DISPLAY on an Xvfb server.

Fake Spotify (MPRIS) + mock LRCLIB + the real void-core; Kitty starts with VOID's generated
config (`void kitty` command line: your kitty.conf → void.conf) and runs `void lyrics`. After a few
seconds the X root window is captured; the script prints JSON with what it found:
  * colours: every pixel's grey-ness (VOID must be monochrome), background colour
  * whether void-core saw a lyrics client
    python3 kitty_check.py OUT.png
"""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "src"))
import mock_lrclib  # noqa: E402

out_png = os.path.abspath(sys.argv[1])
srv = HTTPServer(("127.0.0.1", 0), mock_lrclib.H)
srv.hits = []
threading.Thread(target=srv.serve_forever, daemon=True).start()
cfgdir = Path(os.environ["XDG_CONFIG_HOME"]) / "void-desktop"
cfgdir.mkdir(parents=True, exist_ok=True)
(cfgdir / "config.toml").write_text(f'[lyrics]\nlrclib_url = "http://127.0.0.1:{srv.server_port}"\n'
                                   '[spicetify]\nbridge = false\n[audio]\nenabled = false\n')
procs = [subprocess.Popen([sys.executable, str(HERE.parent / "fake_spotify.py")])]
time.sleep(0.8)
procs.append(subprocess.Popen([sys.executable, "-m", "void.core"], stderr=subprocess.DEVNULL))
time.sleep(1.5)

from void.integration import kitty  # noqa: E402  (after XDG vars are final)
cmd = kitty.command("lyrics")
env = dict(os.environ, LIBGL_ALWAYS_SOFTWARE="1", KITTY_DISABLE_WAYLAND="1")
k = subprocess.Popen(cmd + ["--no-big"], env=env, stdout=subprocess.DEVNULL, stderr=open(Path(os.environ["HOME"]) / "kitty.log", "w"))
time.sleep(9)
subprocess.run(["import", "-window", "root", out_png], check=True)
from void import client  # noqa: E402
status = client.request({"cmd": "status"}, timeout=2) or {}
k.terminate()
for p in procs:
    p.terminate()
srv.shutdown()

from PIL import Image  # noqa: E402
im = Image.open(out_png).convert("RGB")
px = list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())
nongrey = sum(1 for r, g, b in px if max(r, g, b) - min(r, g, b) > 6)
from collections import Counter  # noqa: E402
common = Counter(px).most_common(3)
print(json.dumps({"cmd": cmd[:6], "size": im.size, "nongrey_pixels": nongrey, "total": len(px),
                  "most_common": common, "core_clients": status.get("clients"), "lyrics": status.get("lyrics_status"),
                  "kitty_log": (Path(os.environ["HOME"]) / "kitty.log").read_text()[-600:]}))
