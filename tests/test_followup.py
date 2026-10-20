"""Dual-monitor wallpapers, Kitty integration and the Kitty lyrics view (`void lyrics`).

    cd tests && python3 -m unittest test_followup -v
"""

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import _env
from void import config, lrc
from void.integration import wallpaper as wp

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def mon(name, x, y, w, h, scale=1.0, rot_wh=None, primary=False):
    lw, lh = rot_wh or (w, h)
    return {"name": name, "enabled": True, "x": x, "y": y, "width": w, "height": h, "scale": scale,
            "logical_width": round(lw / scale), "logical_height": round(lh / scale), "primary": primary}


def scene(path, w, h, base, seed, colour=None):
    import random
    from PIL import Image, ImageDraw
    r = random.Random(seed)
    im = Image.new("RGB", (w, h), (base, base, base))
    d = ImageDraw.Draw(im)
    for _ in range(25):
        x, y, s, g = r.randrange(w), r.randrange(h), r.randrange(20, max(21, w // 8)), r.randrange(60, 200)
        d.ellipse((x, y, x + s, y + s), fill=colour or (g, g, g))
    im.save(path)


class DualWallpaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pack = Path(self.tmp.name) / "pack"
        self.pack.mkdir()
        self.cfg = copy.deepcopy(config.DEFAULTS)
        self.cfg["wallpaper"]["source_dir"] = str(self.pack)
        self.saved_out, self.saved_state = wp.OUT, wp.paths.WALLPAPER_STATE
        wp.OUT = Path(self.tmp.name) / "out"
        wp.paths.WALLPAPER_STATE = Path(self.tmp.name) / "wallpaper.json"
        self.L = mon("DP-1", 0, 0, 2560, 1440, primary=True)
        self.R = mon("HDMI-A-1", 2560, 0, 1920, 1080)

    def tearDown(self):
        wp.OUT, wp.paths.WALLPAPER_STATE = self.saved_out, self.saved_state
        self.tmp.cleanup()

    def run_plan(self, outs, right, **kw):
        return wp.prepare(self.cfg, outs, right, interactive=False, **kw)

    def sizes(self, res):
        from PIL import Image
        out = {}
        for n, v in res["screens"].items():
            with Image.open(v["image"]) as im:
                out[n] = im.size
        return out

    def test_panorama_split_by_real_geometry(self):
        scene(self.pack / "wide.png", 5120, 1440, 18, 1)
        scene(self.pack / "small.png", 1920, 1080, 20, 2)
        res = self.run_plan([self.L, self.R], self.R)
        self.assertEqual(res["mode"], "panorama")
        self.assertEqual(self.sizes(res), {"DP-1": (2560, 1440), "HDMI-A-1": (1920, 1080)})
        # continuity: the seam columns of the two screens match (same canvas, adjacent pixels)
        from PIL import Image
        with Image.open(res["screens"]["DP-1"]["image"]) as a, Image.open(res["screens"]["HDMI-A-1"]["image"]) as b:
            la = [a.getpixel((2559, y))[0] for y in range(0, 1080, 40)]
            rb = [b.getpixel((0, y))[0] for y in range(0, 1080, 40)]
        self.assertLess(sum(abs(x - y) for x, y in zip(la, rb)) / len(la), 25)

    def test_matched_pair_when_no_panorama(self):
        scene(self.pack / "a.png", 2560, 1440, 20, 2)
        scene(self.pack / "b.png", 2560, 1440, 21, 3)
        scene(self.pack / "neon.png", 1920, 1080, 30, 4, colour=(220, 30, 60))
        res = self.run_plan([self.L, self.R], self.R)
        self.assertEqual(res["mode"], "pair")
        srcs = {n: Path(v["source"]).name for n, v in res["screens"].items()}
        self.assertNotEqual(srcs["DP-1"], srcs["HDMI-A-1"])
        self.assertNotIn("neon.png", srcs.values())

    def test_overrides_and_original_untouched(self):
        scene(self.pack / "a.png", 2560, 1440, 20, 2)
        scene(self.pack / "b.png", 3000, 2000, 60, 5)
        before = {p.name: p.read_bytes() for p in self.pack.iterdir()}
        res = self.run_plan([self.L, self.R], self.R, picks={"left": str(self.pack / "b.png"), "right": str(self.pack / "a.png")})
        self.assertEqual(Path(res["screens"]["DP-1"]["source"]).name, "b.png")
        self.assertEqual(Path(res["screens"]["HDMI-A-1"]["source"]).name, "a.png")
        self.assertEqual({p.name: p.read_bytes() for p in self.pack.iterdir()}, before)

    def test_scaled_rotated_and_offset_monitors(self):
        scene(self.pack / "a.png", 3840, 2160, 20, 2)
        left = mon("DP-2", 0, 200, 1080, 1920, rot_wh=(1080, 1920))          # portrait, lower
        right = mon("DP-3", 1080, 0, 3840, 2160, scale=1.25)                  # 4K at 125 %
        res = self.run_plan([left, right], right)
        self.assertEqual(self.sizes(res), {"DP-2": (1080, 1920), "DP-3": (3840, 2160)})
        self.assertEqual(res["screens"]["DP-2"]["y"], 200)

    def test_all_outputs_grey_and_preview_written(self):
        scene(self.pack / "a.png", 2560, 1440, 30, 2, colour=(200, 120, 40))
        res = self.run_plan([self.L, self.R], self.R)
        from PIL import Image
        for v in res["screens"].values():
            with Image.open(v["image"]) as im:
                small = im.convert("RGB").resize((48, 27))
                px = list(small.get_flattened_data() if hasattr(small, "get_flattened_data") else small.getdata())
            self.assertTrue(all(r == g == b for r, g, b in px))
        self.assertTrue(Path(res["preview"]).exists())

    def test_procedural_when_pack_missing(self):
        self.cfg["wallpaper"]["source_dir"] = str(Path(self.tmp.name) / "missing")
        res = self.run_plan([self.L, self.R], self.R)
        self.assertEqual(res["mode"], "procedural")
        self.assertEqual(self.sizes(res), {"DP-1": (2560, 1440), "HDMI-A-1": (1920, 1080)})


class LyricsViewTests(unittest.TestCase):
    def tui(self, pos, **kw):
        from void.dashboard.lyrics import LyricsTUI
        t = LyricsTUI(argparse.Namespace(big=kw.get("big", False), compact=False, embedded=False))
        t.osc66 = kw.get("osc66", False)
        t.connected, t.cols, t.rows = True, 90, 22
        text = (_env.TESTS / "mock_lrclib.py").read_text().split('SYNCED = """')[1].split('"""')[0]
        now = time.monotonic()
        t.player = {"available": True, "playing": True, "pos_ms": pos, "mono": now,
                    "track": {"id": "x", "title": "Everything You Are", "artist": "Void Test", "length_ms": 30000}}
        t.lyrics = {"status": "synced", "lines": lrc.parse(text)["lines"], "source": "lrclib", "user_offset_ms": 0,
                    "offset_ms": 0, "track_id": "x"}
        idx = lrc.line_index(t.lyrics["lines"], pos)
        t.line_key, t.line_since = ("x", idx), now - 1
        return t

    def test_scrolling_context_and_current_line(self):
        rows = [ANSI.sub("", r) for r in self.tui(11500).frame()]
        i = next(k for k, r in enumerate(rows) if "Am I sinking" in r)
        self.assertIn("Come back to me", rows[i - 1])
        self.assertIn("Is it love", rows[i + 2])

    def test_karaoke_underlines_active_word(self):
        frame = "\n".join(self.tui(4700).frame())
        self.assertIn("\x1b[4m", frame)                                   # active word underlined
        self.assertRegex(frame, r"\x1b\[38;2;119;119;119mbe ")           # unsung word muted

    def test_big_line_kitty_and_block_font(self):
        f = self.tui(8500, big=True, osc66=True).frame()
        self.assertTrue(any("\x1b]66;s=2;Come back to me" in r for r in f))
        self.assertIn("\x00", f)                                          # second row reserved
        g = "\n".join(self.tui(8500, big=True, osc66=False).frame())
        self.assertIn("█", g)                                             # block font elsewhere

    def test_monochrome_and_fallbacks(self):
        t = self.tui(1000)
        frame = "".join(t.frame())
        for m in re.finditer(r"[34]8;2;(\d+);(\d+);(\d+)", frame):
            self.assertEqual(len(set(m.groups())), 1)
        t.lyrics = {"status": "plain", "plain": "a\nb", "lines": []}
        self.assertIn("no timing is invented", "\n".join(ANSI.sub("", r) for r in t.frame()))
        t.connected = False
        self.assertIn("CONNECTING TO VOID-CORE", "\n".join(ANSI.sub("", r) for r in t.frame()))


class KittyTests(unittest.TestCase):
    def test_launch_commands_keep_kitty_conf(self):
        with _env.new_home() as h:
            code = ("import json; from void.integration import kitty; "
                    "print(json.dumps({m: kitty.command(m) for m in ('shell','lyrics','fetch')}))")
            home = Path(h)
            (home / ".config/kitty").mkdir(parents=True)
            (home / ".config/kitty/kitty.conf").write_text("font_size 12\n")
            r = subprocess.run([sys.executable, "-c", code], env=_env.sandbox_env(home), capture_output=True, text=True)
            cmds = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual((home / ".config/kitty/kitty.conf").read_text(), "font_size 12\n")   # untouched
        lyr = cmds["lyrics"]
        self.assertEqual(lyr[1:5], ["--config", f"{h}/.config/kitty/kitty.conf", "--config", f"{h}/.config/kitty/void.conf"])
        self.assertEqual(lyr[-2:], [str(_env.ROOT / "bin/void"), "lyrics"])
        self.assertIn("--hold", cmds["fetch"])
        self.assertEqual(cmds["shell"][-1], f"{h}/.config/kitty/void.conf")

    @unittest.skipUnless(shutil.which("kitty"), "kitty not installed")
    def test_config_accepted_by_kitty(self):
        with _env.new_home() as h:
            env = _env.sandbox_env(Path(h))
            subprocess.run([sys.executable, "-c", "from void.integration import kitty; kitty.install()"], env=env, check=True,
                           capture_output=True)
            conf = Path(h) / ".config/kitty/void.conf"
            probe = (f"from kitty.config import load_config; o = load_config({str(conf)!r}); "
                     "print(o.background, o.foreground, o.selection_background, o.background_opacity, o.shell, "
                     "o.enabled_layouts, o.active_tab_background)")
            r = subprocess.run(["kitty", "+runpy", probe], capture_output=True, text=True, env=env)
        ignored = [l for l in r.stderr.splitlines() if "Ignoring" in l or "rror" in l]
        # cursor_trail needs kitty 0.37+; everything else must be accepted
        self.assertTrue(all("cursor_trail" in l for l in ignored), ignored)
        self.assertIn("Color(8, 8, 8) Color(229, 229, 229)", r.stdout)       # background, foreground
        self.assertIn("void-shell", r.stdout)
        self.assertIn("splits", r.stdout)

    @unittest.skipUnless(shutil.which("kitty") and shutil.which("xvfb-run") and shutil.which("import")
                         and shutil.which("dbus-run-session"), "needs kitty, xvfb-run, ImageMagick import, dbus")
    def test_real_kitty_lyrics_render_is_monochrome(self):
        with _env.new_home() as h:
            out = Path(h) / "kitty.png"
            r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1240x760x24", "dbus-run-session", "--",
                                sys.executable, str(_env.TESTS / "browser/kitty_check.py"), str(out)],
                               env=_env.sandbox_env(Path(h)), capture_output=True, text=True, timeout=150)
            res = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(res["nongrey_pixels"], 0)
        self.assertEqual(res["most_common"][0][0], [8, 8, 8])               # VOID background fills the window
        self.assertEqual(res["lyrics"], "synced")
        self.assertGreaterEqual(res["core_clients"], 2)                     # the lyrics view is a void-core client


@unittest.skipUnless(shutil.which("node"), "node is needed for the Plasma scripting test double")
class NoQdbusTests(unittest.TestCase):
    """Nobara without qdbus6/qdbus-qt6: wallpapers must still be applied through systemd's busctl."""

    def test_both_wallpapers_via_busctl(self):
        import fixtures as fx
        with tempfile.TemporaryDirectory() as t:
            home, stubs = Path(t) / "home", Path(t) / "stubs"
            home.mkdir()
            shutil.copytree(fx.STUBS, stubs, symlinks=True)
            (stubs / "qdbus6").unlink()
            fx.crimson_home(home)
            plasma = fx.plasmashell(home)
            path = f"{stubs}:{Path(shutil.which('node')).parent}:/usr/bin:/bin"
            try:
                before = fx.snapshot(home)
                r = fx.void(home, "activate", "--no-launch", PATH=path)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                desks = json.loads((home / "plasma-desktops.json").read_text())["desktops"]
                imgs = [d["config"]["Wallpaper/org.kde.image/General"]["Image"] for d in desks]
                self.assertTrue(imgs[0].endswith("/DP-1.png") and imgs[1].endswith("/HDMI-A-1.png"), imgs)
                log = (home / "stub-calls.log").read_text()
                self.assertIn("busctl --user --json=short call org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell evaluateScript s", log)
                self.assertNotIn("qdbus6", log)
                self.assertEqual(fx.void(home, "deactivate", PATH=path).returncode, 0)
                self.assertEqual(fx.snapshot(home), before)
            finally:
                plasma.kill()
                plasma.wait()


class GridDashboardTests(unittest.TestCase):
    def test_kitty_grid_command_and_files(self):
        with _env.new_home() as h:
            code = ("import json; from void import config; from void.dashboard import grid; "
                    "c = grid.command(config.load()); print(json.dumps(c))")
            r = subprocess.run([sys.executable, "-c", code], env=_env.sandbox_env(Path(h)), capture_output=True, text=True)
            cmd = json.loads(r.stdout.strip().splitlines()[-1])
            conf = Path(cmd[cmd.index("--config", 2) + 1]).read_text()
            sess = Path(cmd[cmd.index("--session") + 1]).read_text()
        self.assertEqual(cmd[cmd.index("--class") + 1], "void-dashboard")        # matched by the KWin rule
        self.assertEqual(cmd[cmd.index("--title") + 1], "VOID//DASHBOARD")
        for line in ("enabled_layouts grid", "draw_minimal_borders no", "window_margin_width 7",
                     "background_opacity 0.62", "background_blur 28"):
            self.assertIn(line, conf)
        self.assertEqual(re.findall(r"pane (\w+)", sess), ["shell", "rain", "sysmon", "clock"])

    def test_segment_clock(self):
        from void.dashboard import clock
        t = time.strptime("2025-10-02 21:29:50", "%Y-%m-%d %H:%M:%S")
        out = [ANSI.sub("", l) for l in clock.render(t, 114, 31, True, "segment")]
        self.assertIn("2025-10-02", "\n".join(out))
        self.assertEqual(sum(1 for l in out if "██" in l), 5)
        self.assertNotIn("WEEK", "\n".join(out))

    @unittest.skipUnless(shutil.which("kitty") and shutil.which("xvfb-run") and shutil.which("import"),
                         "needs kitty, xvfb-run and ImageMagick import")
    def test_real_kitty_grid(self):
        with _env.new_home() as h:
            (Path(h) / ".bashrc").write_text('PS1="$ "\n')
            r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24", sys.executable,
                                str(_env.TESTS / "browser/grid_check.py"), str(Path(h) / "grid.png")],
                               env=_env.sandbox_env(Path(h)), capture_output=True, text=True, timeout=150)
            res = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(set(res["tiles"]), {"GEASS", "DATA.STREAM", "SYSTEM.MON", "CHRONO"})
        mon = res["tiles"]["SYSTEM.MON"]
        self.assertGreaterEqual((mon["columns"], mon["lines"]), (80, 24))      # btop's minimum, at 1920x1080
        self.assertEqual(res["nongrey"], 0)


class ClockLyricsTests(unittest.TestCase):
    def state(self, pos, playing=True):
        from void.dashboard import music
        text = (_env.TESTS / "mock_lrclib.py").read_text().split('SYNCED = """')[1].split('"""')[0]
        now = time.monotonic()
        st = music.State(connected=True, ui={"perf": {"music_fps": 10}},
                         player={"playing": playing, "pos_ms": pos, "mono": now,
                                 "track": {"title": "Everything You Are", "artist": "Void Test", "length_ms": 30000}},
                         lyrics={"status": "synced", "lines": lrc.parse(text)["lines"], "track_id": "t", "offset_ms": 0})
        st.line_key, st.line_since = ("t", lrc.line_index(st.lyrics["lines"], pos)), now - 1
        return st, now

    def test_lyrics_under_the_clock(self):
        from void.dashboard import clock
        st, now = self.state(11500)
        ly = clock.lyric_lines(st, 114, now)
        rows = [ANSI.sub("", l) for l in clock.render_segment(time.localtime(), 114, 31, True, ly)]
        joined = "\n".join(rows)
        order = [joined.index(x) for x in (time.strftime("%Y-%m-%d"), "♪ Everything You Are · Void Test",
                                            "Come back to me", "Am I sinking or am I swimming")]
        self.assertEqual(order, sorted(order))                        # date, then now playing, then the lines
        self.assertLessEqual(len(rows), 31)                            # never taller than the tile
        cur = next(l for l in ly if "sinking" in l)
        self.assertIn("\x1b[38;2;242;242;242m\x1b[1m", cur)           # current line bright + bold

    def test_clean_clock_when_nothing_plays(self):
        from void.dashboard import clock, music
        self.assertEqual(clock.lyric_lines(music.State(connected=True), 114, time.monotonic()), [])
        self.assertEqual(clock.lyric_lines(music.State(connected=False), 114, time.monotonic()), [])

    def test_small_tile_keeps_clock(self):
        from void.dashboard import clock
        st, now = self.state(11500)
        rows = clock.render_segment(time.localtime(), 60, 12, True, clock.lyric_lines(st, 60, now))
        self.assertLessEqual(len(rows), 12)
        self.assertTrue(any("█" in r or "▀" in r for r in rows))
