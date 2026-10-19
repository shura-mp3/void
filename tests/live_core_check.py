"""Runs INSIDE `dbus-run-session`: fake Spotify (MPRIS) + mock LRCLIB + the real void-core.

Exits 0 when void-core follows the player, fetches synced lyrics, survives a track change and
serves play/pause; prints what it saw. Used by tests/test_backend.py (LiveCoreTests).
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
sys.path.insert(0, str(HERE))
import mock_lrclib  # noqa: E402

srv = HTTPServer(("127.0.0.1", 0), mock_lrclib.H)
srv.hits = []
threading.Thread(target=srv.serve_forever, daemon=True).start()
cfg = Path(os.environ["HOME"]) / "void-test.toml"
cfg.write_text(f'[lyrics]\nlrclib_url = "http://127.0.0.1:{srv.server_port}"\n[spicetify]\nbridge_port = 0\n'
               '[audio]\nenabled = false\n')

procs = [subprocess.Popen([sys.executable, str(HERE / "fake_spotify.py")])]
time.sleep(0.8)
procs.append(subprocess.Popen([sys.executable, "-m", "void.core", "--config", str(cfg)]))
sock_path = Path(os.environ["XDG_RUNTIME_DIR"]) / "void-desktop" / "core.sock"
seen: dict = {}
ok = False
try:
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.1)
    s = socket.socket(socket.AF_UNIX)
    s.connect(str(sock_path))
    s.settimeout(0.5)
    buf = b""
    deadline = time.monotonic() + 12
    stage = "first"
    while time.monotonic() < deadline:
        try:
            buf += s.recv(65536)
        except socket.timeout:
            pass
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            m = json.loads(line)
            seen.setdefault(m["t"], []).append(m)
            if m["t"] == "lyrics" and m.get("status") == "synced" and stage == "first":
                print(f"synced lyrics: {len(m['lines'])} lines, words={m['has_words']}, source={m['source']}")
                stage = "next"
                s.sendall(b'{"cmd":"next"}\n')
            elif m["t"] == "lyrics" and stage == "next" and m.get("status") in ("none", "plain", "instrumental"):
                print(f"after Next: lyrics status {m['status']} (track without lyrics in the mock)")
                stage = "pause"
                s.sendall(b'{"cmd":"play_pause"}\n')
            elif m["t"] == "player" and stage == "pause" and m.get("status") == "Paused":
                print(f"paused at {m['pos_ms']:.0f} ms of {m['track']['title']!r}")
                s.sendall(b'{"cmd":"status","id":7}\n')
                stage = "status"
            elif m["t"] == "reply" and stage == "status":
                print(f"status: lyrics={m['lyrics_status']} profile={m['ui']['effective_performance']} clients={m['clients']}")
                ok = True
                deadline = 0
finally:
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(6)
        except subprocess.TimeoutExpired:
            p.kill()
    srv.shutdown()
print("topics seen:", {k: len(v) for k, v in seen.items()})
sys.exit(0 if ok else 1)
