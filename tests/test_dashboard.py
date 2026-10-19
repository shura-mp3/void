"""Dashboard tests: renderers, block font, Geass art, the real tmux session, launch/stop.

The tmux tests start a real tmux server (VOID's private one) in a sandboxed home.
"""

import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import _env
import fixtures as fx
from void import lrc
from void.dashboard import bigfont, clock, music, rain, session
from void.dashboard.term import width

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def plain(lines):
    return [ANSI.sub("", l) for l in lines]


class GeassArtTests(unittest.TestCase):
    def test_symmetric_and_fits(self):
        art = (_env.ROOT / "assets/ascii/geass.txt").read_text().splitlines()
        w = max(width(l) for l in art)
        self.assertLessEqual(w, 44)
        mirror = str.maketrans("◢◣◤◥▌▐", "◣◢◥◤▐▌")
        for line in art:
            line = line.ljust(w)
            self.assertEqual(line, line[::-1].translate(mirror), line)

    def test_block_elements_only(self):
        """Only one-cell block glyphs: identical width in every font and locale."""
        art = (_env.ROOT / "assets/ascii/geass.txt").read_text()
        self.assertTrue(set(art) <= set(" \n▀▄█"), set(art) - set(" \n▀▄█"))

    def test_fastfetch_logo_matches_plain_art(self):
        coloured = (_env.ROOT / "config/fastfetch/geass.txt").read_text()
        self.assertEqual(re.sub(r"\$[123]", "", coloured), (_env.ROOT / "assets/ascii/geass.txt").read_text())


class BigFontTests(unittest.TestCase):
    def test_glyph_shapes(self):
        for k, rows in bigfont.GLYPHS.items():
            self.assertEqual(len(rows), 5, k)
            self.assertEqual(len(set(map(len, rows))), 1, k)

    def test_render_sizes(self):
        self.assertEqual(len(bigfont.render("HELLO")), 3)
        self.assertEqual(len(bigfont.render("12:34", "wide")), 5)
        self.assertEqual(len(bigfont.render("12:34", "wide")[0]), bigfont.cell_width("12:34", "wide"))

    def test_accents_and_unsupported(self):
        self.assertTrue(bigfont.supported("Café déjà vu"))
        self.assertFalse(bigfont.supported("東京"))


def demo_state(pos_ms: int, now: float) -> music.State:
    text = (_env.TESTS / "mock_lrclib.py").read_text().split('SYNCED = """')[1].split('"""')[0]
    p = lrc.parse(text)
    st = music.State(connected=True,
                     player={"playing": True, "pos_ms": pos_ms, "mono": now,
                             "track": {"title": "Everything You Are", "artist": "Void Test", "album": "Signal Lost", "length_ms": 30000}},
                     lyrics={"status": "synced", "lines": p["lines"], "has_words": True, "source": "lrclib", "offset_ms": 0, "track_id": "t"},
                     ui={"effective_performance": "balanced", "perf": {"music_fps": 10, "spectrum": True}},
                     spec=[200] * 64)
    st.line_since = now - 5
    return st


class MusicRenderTests(unittest.TestCase):
    def test_layout_at_dashboard_size(self):
        now = time.monotonic()
        out = music.render(demo_state(8500, now), 210, 19, now)
        txt = plain(out)
        self.assertEqual(len(out), 19)
        self.assertTrue(all(width(l) <= 210 for l in txt), [width(l) for l in txt])
        self.assertIn("Everything You Are", txt[2])
        self.assertIn("0:08 / 0:30", txt[2])
        self.assertTrue(any("▀" in l or "█" in l for l in txt))            # big active lyric
        self.assertTrue(any("Am I sinking or am I swimming" in l for l in txt))  # next line

    def test_lines_follow_position_and_offset(self):
        now = time.monotonic()
        st = demo_state(11500, now)
        st.ui["perf"]["spectrum"] = False
        txt = "\n".join(plain(music.render(st, 120, 12, now)))   # small: normal-size text
        self.assertIn("Am I sinking or am I swimming", txt)
        st.lyrics["offset_ms"] = 6000                            # positive offset = lyrics earlier
        txt = "\n".join(plain(music.render(st, 120, 12, now)))
        self.assertIn("Is it love or is it noise", txt)

    def test_word_karaoke_colours(self):
        now = time.monotonic()
        st = demo_state(4700, now)        # "You could be everything" at 5.2 s: You, could, be sung
        music.render(st, 80, 12, now)     # first frame of a new line fades in from muted
        out = "\n".join(music.render(st, 80, 12, now + 0.5))
        hi, mute = "\x1b[38;2;242;242;242m", "\x1b[38;2;119;119;119m"
        self.assertRegex(out, re.escape(hi) + r"\x1b\[1mYou")
        self.assertRegex(out, re.escape(hi) + r"\x1b\[1mbe")
        self.assertRegex(out, re.escape(mute) + r"\x1b\[1meverything")

    def test_honest_fallbacks(self):
        now = time.monotonic()
        for status, expect in (("none", "NO SYNCED LYRICS"), ("loading", "SEARCHING"), ("instrumental", "INSTRUMENTAL"),
                               ("plain", "NONE INVENTED")):
            st = demo_state(1000, now)
            st.lyrics = {"status": status, "lines": [], "plain": "a\nb"}
            self.assertIn(expect, "\n".join(plain(music.render(st, 120, 18, now))))
        st = music.State()
        self.assertIn("VOID-CORE OFFLINE", "\n".join(plain(music.render(st, 120, 18, now))))

    def test_paused_position_is_frozen(self):
        now = time.monotonic()
        st = demo_state(5000, now - 10)
        st.player["playing"] = False
        self.assertEqual(st.position(now), 5000)


class ClockRainTests(unittest.TestCase):
    def test_clock(self):
        t = time.strptime("2026-10-19 23:41:07", "%Y-%m-%d %H:%M:%S")
        txt = plain(clock.render(t, 115, 12, True))
        joined = "\n".join(txt)
        self.assertIn("M O N D A Y", joined)
        self.assertTrue(all(width(l) <= 115 for l in txt))
        self.assertEqual(sum(1 for l in txt if "██" in l), 5)

    def test_rain_bounded_and_grey(self):
        r = rain.Rain(94, 11, seed=1)
        for _ in range(50):
            r.step()
        lines = r.lines()
        self.assertEqual(len(lines), 11)
        self.assertTrue(all(width(l) == 94 for l in plain(lines)))
        for m in re.finditer(r"38;2;(\d+);(\d+);(\d+)", "".join(lines)):
            self.assertEqual(len(set(m.groups())), 1)

    def test_pane_layout_plan(self):
        p = session.plan(210, 56)
        self.assertGreaterEqual(p["top_h"], 24)   # btop's minimum
        self.assertGreaterEqual(210 - p["left_w"] - 1, 80)
        self.assertGreaterEqual(p["music_h"], 14)
        p = session.plan(160, 40)                  # smaller monitor / bigger font: still usable
        self.assertGreaterEqual(210 - p["left_w"] - 1, 80)


@unittest.skipUnless(shutil.which("tmux"), "tmux not installed")
class TmuxSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="void-tmux-")
        self.home = Path(self.tmp.name)
        self.env = fx.env_for(self.home, TMUX_TMPDIR=str(self.home / "tmux"))
        (self.home / "tmux").mkdir()

    def tearDown(self):
        subprocess.run([str(_env.ROOT / "bin/void"), "stop"], env=self.env, capture_output=True)
        subprocess.run(["tmux", "-L", session.SERVER, "kill-server"], env=self.env, capture_output=True)
        self.tmp.cleanup()

    def void(self, *a):
        return subprocess.run([str(_env.ROOT / "bin/void"), *a], env=self.env, capture_output=True, text=True, timeout=60)

    def test_build_is_idempotent_and_panes_live(self):
        self.assertIn("created", self.void("dashboard", "build").stdout)
        self.assertIn("already running", self.void("dashboard", "build").stdout)
        time.sleep(3)
        st = self.void("dashboard", "status").stdout
        for pane in session.PANES:
            self.assertIn(pane, st)
        self.assertNotIn("DEAD", st)
        # btop keeps its 80x24 minimum
        m = re.search(r"sysmon\s+\S+\s+(\d+)x(\d+)", st)
        self.assertGreaterEqual(int(m.group(1)), 80)
        self.assertGreaterEqual(int(m.group(2)), 24)

    def test_launch_once_and_stop_cleans_up(self):
        r1 = self.void("launch")
        self.assertIn("dashboard opened", r1.stdout, r1.stdout + r1.stderr)
        r2 = self.void("launch")
        self.assertIn("already open", r2.stdout)
        log = (self.home / "stub-calls.log").read_text()
        self.assertEqual(log.count("konsole --separate"), 1)            # no duplicate window
        self.assertIn("--profile VOID Dashboard", log)
        time.sleep(2)
        self.assertEqual(subprocess.run(["pgrep", "-fc", r"python[0-9.]* -m void\.core"], capture_output=True,
                                        text=True).stdout.strip(), "1")  # exactly one void-core
        self.void("stop")
        time.sleep(1)
        self.assertEqual(subprocess.run(["tmux", "-L", session.SERVER, "has-session", "-t", "void"], env=self.env,
                                        capture_output=True).returncode, 1)
        self.assertEqual(subprocess.run(["pgrep", "-f", r"python[0-9.]* -m void\.core"], capture_output=True).returncode, 1)


