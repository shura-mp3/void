"""The real VOID Spotify theme.js + custom app in headless Chromium against the real void-core bridge.

Skipped unless NODE_PATH points at a node_modules with react@18, react-dom@18 and playwright-core,
and a Chromium headless shell exists (set CHROMIUM=/path/to/headless_shell if it's elsewhere).
"""

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import _env

NM = os.environ.get("NODE_PATH", "").split(":")[0]
CHROMIUM = os.environ.get("CHROMIUM", "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell")
READY = bool(NM) and all((Path(NM) / m).is_dir() for m in ("react", "react-dom", "playwright-core")) \
    and Path(CHROMIUM).exists() and shutil.which("node") and shutil.which("dbus-run-session")


@unittest.skipUnless(READY, "needs NODE_PATH (react, react-dom, playwright-core), node, Chromium, dbus-run-session")
class SpotifyPageTests(unittest.TestCase):
    def test_void_page_links_to_core_and_shows_word_sync(self):
        with _env.new_home() as t:
            env = dict(_env.sandbox_env(Path(t)), NODE_PATH=NM, CHROMIUM=CHROMIUM)
            r = subprocess.run(["dbus-run-session", "--", sys.executable, str(_env.TESTS / "browser/run_spotify_page_check.py"),
                                str(Path(t) / "page.png")], env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        self.assertIn('"currentColours":["rgb(242, 242, 242)","rgb(242, 242, 242)","rgb(119, 119, 119)"', r.stdout)
