"""Runs INSIDE `dbus-run-session`: fake Spotify + mock LRCLIB + real void-core (bridge on a free port),
then spotify_page.js in headless Chromium. Exits 0 when the VOID page links to void-core, shows the
synced word lyrics and the offset round-trips. Needs NODE_PATH with react, react-dom, playwright-core.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import mock_lrclib  # noqa: E402

srv = HTTPServer(("127.0.0.1", 0), mock_lrclib.H)
srv.hits = []
threading.Thread(target=srv.serve_forever, daemon=True).start()
s = socket.socket()
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()
cfg = Path(os.environ["HOME"]) / "void-test.toml"
cfg.write_text(f'[lyrics]\nlrclib_url = "http://127.0.0.1:{srv.server_port}"\n[spicetify]\nbridge_port = {port}\n[audio]\nenabled = false\n')
procs = [subprocess.Popen([sys.executable, str(HERE.parent / "fake_spotify.py")])]
time.sleep(0.8)
procs.append(subprocess.Popen([sys.executable, "-m", "void.core", "--config", str(cfg)]))
time.sleep(2.5)
shot = sys.argv[1] if len(sys.argv) > 1 else str(Path(os.environ["HOME"]) / "spotify-page.png")
try:
    r = subprocess.run(["node", str(HERE / "spotify_page.js"), str(port), shot], capture_output=True, text=True, timeout=90)
finally:
    for p in procs:
        p.terminate()
    srv.shutdown()
print(r.stdout[-3000:], r.stderr[-3000:])
if r.returncode != 0:
    sys.exit(1)
res = json.loads(r.stdout.strip().splitlines()[-1])
ok = res.get("linked") and res.get("offsetShown") and not res.get("errors") and "void-profile-balanced" in res.get("htmlClass", "")
sys.exit(0 if ok else 1)
