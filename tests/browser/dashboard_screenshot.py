"""Render the real dashboard to a PNG (docs/screenshots/dashboard.png). Runs INSIDE dbus-run-session.

Fake Spotify (MPRIS) + mock LRCLIB + real void-core + the real tmux dashboard; a tmux client is
attached on a 210x56 pseudo-terminal, its output is replayed into pyte (a terminal emulator), and the
resulting cells are drawn as HTML and screenshotted with headless Chromium. Fonts differ from Konsole's.
    python3 dashboard_screenshot.py OUT.png      (needs: pyte, node + playwright-core via NODE_PATH)
"""
import fcntl
import html
import os
import pty
import struct
import subprocess
import sys
import termios
import threading
import time
from http.server import HTTPServer
from pathlib import Path

import pyte

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
import mock_lrclib  # noqa: E402

COLS, ROWS = 210, 56
out_png = sys.argv[1]
srv = HTTPServer(("127.0.0.1", 0), mock_lrclib.H)
srv.hits = []
threading.Thread(target=srv.serve_forever, daemon=True).start()
cfgdir = Path(os.environ["XDG_CONFIG_HOME"]) / "void-desktop"
cfgdir.mkdir(parents=True, exist_ok=True)
(cfgdir / "config.toml").write_text(f'[lyrics]\nlrclib_url = "http://127.0.0.1:{srv.server_port}"\n[spicetify]\nbridge = false\n')
procs = [subprocess.Popen([sys.executable, str(HERE.parent / "fake_spotify.py")])]
time.sleep(0.8)
procs.append(subprocess.Popen([sys.executable, "-m", "void.core"], stderr=subprocess.DEVNULL))
time.sleep(1.5)
subprocess.run([str(ROOT / "bin/void"), "dashboard", "build"], check=True)
pid, fd = pty.fork()
if pid == 0:
    os.environ["TERM"] = "xterm-256color"
    os.execvp("tmux", ["tmux", "-L", "void-desktop", "attach", "-t", "void"])
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
screen = pyte.Screen(COLS, ROWS)
stream = pyte.ByteStream(screen)
end = time.monotonic() + 9          # long enough for fetch, btop, the first lyric lines
while time.monotonic() < end:
    import select
    r, _, _ = select.select([fd], [], [], 0.2)
    if r:
        try:
            stream.feed(os.read(fd, 65536))
        except OSError:
            break
subprocess.run(["tmux", "-L", "void-desktop", "kill-server"])
for p in procs:
    p.terminate()
srv.shutdown()


def colour(c, default):
    if c == "default":
        return default
    if len(c) == 6 and all(x in "0123456789abcdefABCDEF" for x in c):
        return "#" + c
    names = {"black": "#1B1B1B", "red": "#B8B8B8", "green": "#9C9C9C", "brown": "#CCCCCC", "blue": "#8C8C8C",
             "magenta": "#A6A6A6", "cyan": "#969696", "white": "#D6D6D6"}  # VOID Konsole palette
    return names.get(c, default)


rows = []
for y in range(ROWS):
    line, cur, buf = [], None, ""
    for x in range(COLS):
        ch = screen.buffer[y][x]
        style = (colour(ch.fg, "#E5E5E5"), colour(ch.bg, "#080808"), ch.bold)
        if ch.reverse:
            style = (style[1], style[0], style[2])
        if style != cur and buf:
            line.append((cur, buf))
            buf = ""
        cur = style
        buf += ch.data or " "
    line.append((cur, buf))
    rows.append("".join(f'<span style="color:{f};background:{b};{"font-weight:700" if bo else ""}">{html.escape(t)}</span>'
                        for (f, b, bo), t in line))
page = ("<!doctype html><meta charset=utf-8><style>body{margin:0;background:#080808}"
        "pre{margin:0;font:13.6px/19.2px 'DejaVu Sans Mono',monospace;letter-spacing:0;padding:2px 3px}</style><pre>"
        + "\n".join(rows) + "</pre>")
tmp = Path(os.environ["HOME"]) / "dash.html"
tmp.write_text(page)
js = f"""const {{ chromium }} = require("playwright-core");
(async () => {{ const b = await chromium.launch({{ executablePath: process.env.CHROMIUM }});
const p = await b.newPage({{ viewport: {{ width: 1920, height: 1080 }} }});
await p.goto("file://{tmp}"); await p.screenshot({{ path: "{os.path.abspath(out_png)}" }}); await b.close(); }})();"""
subprocess.run(["node", "-e", js], check=True)
print("wrote", out_png)
