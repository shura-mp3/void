"""Backend tests: LRC parsing, lyrics lookup (incl. Crimson's cache), MPRIS metadata, the Spotify
bridge, monitor detection, and a live void-core on a private D-Bus with a fake Spotify.

    cd tests && python3 -m unittest test_backend -v
"""

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path

import _env
from void import bridge, lrc, lyrics, paths
from void.integration import monitors
from void.mpris import Track


class LrcTests(unittest.TestCase):
    def test_lines_tags_offset(self):
        p = lrc.parse("[ar:X]\n[offset:+250]\n[00:01.50]one\n[00:03.2]two\n[01:02.123]three\n")
        self.assertEqual([l["t"] for l in p["lines"]], [1500, 3200, 62123])
        self.assertEqual(p["offset"], 250)
        self.assertFalse(p["has_words"])

    def test_enhanced_word_stamps(self):
        p = lrc.parse("[00:04.00]<00:04.00>You <00:04.60>could <00:05.20>be <00:07.00>")
        self.assertTrue(p["has_words"])
        self.assertEqual(p["lines"][0]["w"][-1], [5200, "be ", 7000])

    def test_no_invented_word_timing(self):
        self.assertIsNone(lrc.parse("[00:01.00]plain line only")["lines"][0]["w"])

    def test_line_index(self):
        lines = lrc.parse("[00:01.00]a\n[00:02.00]b\n[00:03.00]c")["lines"]
        self.assertEqual([lrc.line_index(lines, t) for t in (500, 1000, 2999, 99999)], [-1, 0, 1, 2])


class MetadataTests(unittest.TestCase):
    def test_from_metadata(self):
        t = Track.from_metadata({
            "mpris:trackid": ("o", "/com/spotify/track/abc"), "xesam:title": ("s", "T"),
            "xesam:artist": ("as", ["A", "B"]), "xesam:album": ("s", "Al"),
            "mpris:length": ("t", 215_000_000), "mpris:artUrl": ("s", "https://open.spotify.com/image/ff00")})
        self.assertEqual((t.title, t.artist, t.album, t.length_ms), ("T", "A, B", "Al", 215000))
        self.assertEqual(t.art_url, "https://i.scdn.co/image/ff00")
        self.assertTrue(Track(id="spotify:ad:123").is_ad)


class LyricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import mock_lrclib
        cls.srv = HTTPServer(("127.0.0.1", 0), mock_lrclib.H)
        cls.srv.hits = []
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = (paths.LYRICS_CACHE, paths.USER_LYRICS_DIR, paths.CRIMSON_LYRICS_CACHE, paths.CRIMSON_USER_LYRICS)
        paths.LYRICS_CACHE, paths.USER_LYRICS_DIR = t / "void-cache", t / "void-user"
        paths.CRIMSON_LYRICS_CACHE, paths.CRIMSON_USER_LYRICS = t / "crimson-cache", t / "crimson-user"
        for d in (paths.USER_LYRICS_DIR, paths.CRIMSON_LYRICS_CACHE):
            d.mkdir(parents=True)

    def tearDown(self):
        paths.LYRICS_CACHE, paths.USER_LYRICS_DIR, paths.CRIMSON_LYRICS_CACHE, paths.CRIMSON_USER_LYRICS = self.saved
        self.tmp.cleanup()

    def svc(self, **kw):
        return lyrics.LyricsService({"lyrics": {"lrclib": True, "lrclib_url": f"http://127.0.0.1:{self.srv.server_port}",
                                                "local_dirs": [], "duration_tolerance": 3, "negative_cache_hours": 24,
                                                "use_crimson_cache": True, **kw}})

    def test_lrclib_synced_then_cached(self):
        s = self.svc()
        self.assertEqual(s.lookup("Void Test", "Everything You Are", "Signal Lost", 30_000)["status"], "synced")
        hits = len(self.srv.hits)
        r2 = s.lookup("Void Test", "Everything You Are", "Signal Lost", 30_000)
        self.assertIn("cached", r2["source"])
        self.assertEqual(len(self.srv.hits), hits)

    def test_crimson_cache_reused_read_only(self):
        s = self.svc()
        key = s._cache_key("Someone", "Crimson Only Song", 100_000)
        f = paths.CRIMSON_LYRICS_CACHE / f"{key}.json"
        f.write_text(json.dumps({"fetched": 1, "result": lyrics.from_lrc_text("[00:01.00]from crimson", "lrclib")}))
        before = f.read_bytes()
        hits = len(self.srv.hits)
        r = s.lookup("Someone", "Crimson Only Song", "", 100_000)
        self.assertEqual(r["status"], "synced")
        self.assertIn("via crimson", r["source"])
        self.assertEqual(len(self.srv.hits), hits)                        # no network request
        self.assertEqual(f.read_bytes(), before)                          # Crimson's file untouched
        self.assertTrue((paths.LYRICS_CACHE / f"{key}.json").exists())    # copied into VOID's own cache

    def test_crimson_negative_entries_ignored(self):
        s = self.svc()
        key = s._cache_key("Void Test", "Everything You Are", 30_000)
        (paths.CRIMSON_LYRICS_CACHE / f"{key}.json").write_text(json.dumps({"fetched": 9e12, "result": {"status": "none"}}))
        self.assertEqual(s.lookup("Void Test", "Everything You Are", "Signal Lost", 30_000)["status"], "synced")

    def test_crimson_cache_can_be_disabled(self):
        s = self.svc(use_crimson_cache=False)
        key = s._cache_key("Someone", "Crimson Only Song", 100_000)
        (paths.CRIMSON_LYRICS_CACHE / f"{key}.json").write_text(
            json.dumps({"fetched": 1, "result": lyrics.from_lrc_text("[00:01.00]x", "lrclib")}))
        self.assertNotEqual(s.lookup("Someone", "Crimson Only Song", "", 100_000)["status"], "synced")

    def test_local_file_wins(self):
        (paths.USER_LYRICS_DIR / "Some Artist - Local Song.lrc").write_text("[00:01.00]from disk")
        r = self.svc().lookup("Some Artist", "Local Song", "", 100_000)
        self.assertTrue(r["source"].startswith("local:"))

    def test_duration_mismatch_rejected(self):
        self.assertNotEqual(self.svc().lookup("Void Test", "Everything You Are", "Other", 200_000)["status"], "synced")

    def test_network_error_not_cached(self):
        s = self.svc(lrclib_url="http://127.0.0.1:9")
        self.assertEqual(s.lookup("Nobody", "Nothing", "", 100_000)["status"], "error")
        self.assertIsNone(s._cache_get(s._cache_key("Nobody", "Nothing", 100_000)))


class BridgeTests(unittest.TestCase):
    def test_rfc6455_accept_key(self):
        self.assertEqual(bridge.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_allowlists(self):
        self.assertEqual(bridge.BRIDGE_COMMANDS, {"sub", "offset", "ping"})
        self.assertNotIn("sys", bridge.BRIDGE_TOPICS)

    def test_origin_check_and_port(self):
        """A real TCP handshake: Spotify's origin is accepted, a web page's origin gets 403."""
        class FakeCore:
            clients = set()
            def snapshot(self, c): c.send(b'{"t":"ui"}\n')
            async def command(self, c, m): return {"ok": True}
            def _update_audio(self): pass

        async def go():
            b = bridge.Bridge(FakeCore(), {"bridge_port": 0})
            self.assertEqual(bridge.Bridge(FakeCore(), {}).port, 47812)   # VOID's port, never Crimson's 47811
            await b.start()
            port = b.server.sockets[0].getsockname()[1]

            async def handshake(origin):
                r, w = await asyncio.open_connection("127.0.0.1", port)
                key = base64.b64encode(os.urandom(16)).decode()
                w.write((f"GET / HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         f"Sec-WebSocket-Key: {key}\r\nOrigin: {origin}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
                await w.drain()
                status = (await r.readline()).decode()
                w.close()
                return status
            ok = await handshake("https://xpui.app.spotify.com")
            bad = await handshake("https://evil.example")
            b.server.close()
            return ok, bad
        ok, bad = asyncio.run(go())
        self.assertIn("101", ok)
        self.assertIn("403", bad)


class MonitorTests(unittest.TestCase):
    def test_json_rotation_and_scale(self):
        outs = monitors.from_json(json.dumps({"outputs": [
            {"name": "DP-2", "enabled": True, "connected": True, "pos": {"x": 1920, "y": 0}, "scale": 2, "rotation": 1,
             "currentModeId": "a", "modes": [{"id": "a", "refreshRate": 144, "size": {"width": 3840, "height": 2160}}]},
            {"name": "DP-1", "enabled": True, "connected": True, "priority": 1, "pos": {"x": 0, "y": 0}, "scale": 1,
             "rotation": 2, "currentModeId": "b", "modes": [{"id": "b", "refreshRate": 60, "size": {"width": 1920, "height": 1080}}]}]}))
        d = {o["name"]: o for o in outs}
        self.assertEqual((d["DP-2"]["logical_width"], d["DP-2"]["logical_height"]), (1920, 1080))
        self.assertEqual((d["DP-1"]["logical_width"], d["DP-1"]["logical_height"]), (1080, 1920))

    def test_right_monitor_by_position_not_name(self):
        env = dict(os.environ, PATH=f"{_env.TESTS / 'stubs'}:{os.environ['PATH']}")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            # connector names deliberately "backwards": HDMI-A-1 is on the LEFT here
            json.dump({"outputs": [
                {"name": "HDMI-A-1", "enabled": True, "connected": True, "pos": {"x": -1920, "y": 0}, "scale": 1,
                 "currentModeId": "a", "modes": [{"id": "a", "refreshRate": 60, "size": {"width": 1920, "height": 1080}}]},
                {"name": "DP-1", "enabled": True, "connected": True, "pos": {"x": 0, "y": 0}, "scale": 1,
                 "currentModeId": "b", "modes": [{"id": "b", "refreshRate": 60, "size": {"width": 1920, "height": 1080}}]}]}, f)
        env["STUB_KSCREEN_JSON"] = f.name
        code = ("import json; from void.integration import monitors; from void import config; "
                "print(json.dumps(monitors.detect(config.DEFAULTS)['target']['name']))")
        r = subprocess.run([sys.executable, "-c", code], env=dict(env, PYTHONPATH=str(_env.ROOT / "src")),
                           capture_output=True, text=True)
        os.unlink(f.name)
        self.assertEqual(r.stdout.strip(), '"DP-1"', r.stderr)

    def test_text_fallback(self):
        raw = ("Output: 1 DP-1 enabled connected priority 1 DisplayPort Modes: 1:2560x1440@165*! "
               "Geometry: 0,0 2560x1440 Scale: 1 Rotation: 1\n"
               "Output: 2 HDMI-A-1 enabled connected priority 2 HDMI Modes: 1:1920x1080@75*! "
               "Geometry: 2560,180 1920x1080 Scale: 1 Rotation: 1\n")
        outs = monitors.from_text(raw)
        self.assertEqual([o["name"] for o in outs], ["DP-1", "HDMI-A-1"])
        self.assertEqual(outs[1]["x"], 2560)


@unittest.skipUnless(shutil.which("dbus-run-session"), "needs dbus-run-session")
class LiveCoreTests(unittest.TestCase):
    def test_core_follows_fake_spotify(self):
        try:
            import dbus_next  # noqa: F401
            import jeepney  # noqa: F401
        except ImportError:
            self.skipTest("needs jeepney + dbus-next")
        with _env.new_home() as t:
            env = _env.sandbox_env(Path(t))
            r = subprocess.run(["dbus-run-session", "--", sys.executable, str(_env.TESTS / "live_core_check.py")],
                               env=env, capture_output=True, text=True, timeout=90)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr[-2000:])
        self.assertIn("synced lyrics: 8 lines, words=True", r.stdout)
        self.assertIn("after Next", r.stdout)
        self.assertIn("paused at", r.stdout)
