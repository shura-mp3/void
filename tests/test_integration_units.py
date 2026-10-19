"""Unit tests for integration helpers: wallpaper ranking, Konsole profiles + shell layer, Spotify
detection, the journal engine itself, and installed-file ownership."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import _env
from void import paths
from void.integration import files, journal, konsole, spotify, wallpaper


def _pixels(im):
    return list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())


def _img(path: Path, colour, size=(1920, 1080), noise=False):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, colour)
    if noise:
        d = ImageDraw.Draw(im)
        for i in range(0, size[0], 7):
            d.line((i, 0, size[0] - i, size[1]), fill=(255 - colour[0], 128, colour[2]))
    im.save(path)


@unittest.skipUnless(shutil.which("python3") and wallpaper._pil(), "needs Pillow")
class WallpaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ranking_prefers_dark_monochrome_by_content_not_name(self):
        from PIL import Image, ImageDraw
        # names are deliberately misleading
        _img(self.d / "black_and_grey_monochrome.png", (230, 30, 40))                   # bright red
        _img(self.d / "colourful_neon.png", (24, 24, 26))                               # actually dark grey
        dark = Image.new("RGB", (1920, 1080), (20, 20, 20))
        ImageDraw.Draw(dark).ellipse((700, 300, 1200, 800), fill=(150, 150, 150))      # dark mono + a subject
        dark.save(self.d / "x.png")
        _img(self.d / "small.png", (30, 30, 30), size=(640, 360))
        ranked = wallpaper.rank(self.d, 1920, 1080)
        names = [i["name"] for _, i in ranked]
        self.assertEqual(names[-1], "black_and_grey_monochrome.png")
        self.assertIn(names[0], ("x.png", "colourful_neon.png"))
        self.assertLess(names.index("colourful_neon.png"), names.index("small.png"))

    def test_derivative_is_grey_exact_size_and_original_untouched(self):
        src = self.d / "src.png"
        _img(src, (200, 40, 90), size=(2560, 1600), noise=True)
        before = src.read_bytes()
        from PIL import Image
        with Image.open(src) as im:
            out = wallpaper.monochrome(im, 1920, 1080)
        self.assertEqual(out.size, (1920, 1080))
        px = _pixels(out.resize((64, 36)))
        self.assertTrue(all(r == g == b for r, g, b in px))
        self.assertEqual(src.read_bytes(), before)

    def test_fallback_wallpaper_bundled(self):
        from PIL import Image
        with Image.open(wallpaper.FALLBACK) as im:
            self.assertEqual(im.size, (1920, 1080))
            self.assertTrue(all(r == g == b for r, g, b in _pixels(im.convert("RGB").resize((32, 18)))))


class KonsoleTests(unittest.TestCase):
    def test_profiles(self):
        p = konsole.profile_text()
        self.assertIn("ColorScheme=Void", p)
        self.assertIn(f"Command={paths.PROJECT_DIR / 'bin' / 'void-shell'}", p)
        self.assertIn("ScrollBarPosition=2", p)
        d = konsole.profile_text(dashboard=True)
        self.assertIn("dashboard attach", d)
        self.assertIn("LocalTabTitleFormat=VOID//DASHBOARD", d)

    def _shell(self, shell: str, script: str) -> str:
        with tempfile.TemporaryDirectory() as h:
            home = Path(h)
            (home / ".bashrc").write_text("echo USER-RC-LOADED; alias ll='ls -l'\n")
            (home / ".zshrc").write_text("echo USER-RC-LOADED; alias ll='ls -l'\n")
            env = {"HOME": h, "SHELL": shell, "PATH": "/usr/bin:/bin", "TERM": "xterm-256color", "VOID_STARTUP_FETCH": "0"}
            r = subprocess.run(["script", "-qc", str(_env.ROOT / "bin/void-shell"), "/dev/null"], input=script,
                               env=env, capture_output=True, text=True, timeout=30)
            return r.stdout

    @unittest.skipUnless(shutil.which("script"), "needs util-linux script")
    def test_bash_layer_loads_after_user_rc(self):
        out = self._shell("/bin/bash", "type void; alias ll; echo PC=$PROMPT_COMMAND; exit\n")
        self.assertIn("USER-RC-LOADED", out)
        self.assertIn("void is a function", out)
        self.assertIn("ls -l", out)
        self.assertIn("PC=__void_ps1", out)

    @unittest.skipUnless(shutil.which("script") and shutil.which("zsh"), "needs zsh")
    def test_zsh_layer_loads_after_user_rc(self):
        out = self._shell(shutil.which("zsh"), "whence -w void; alias ll; exit\n")
        self.assertIn("USER-RC-LOADED", out)
        self.assertIn("void: function", out)

    @unittest.skipUnless(shutil.which("script"), "needs util-linux script")
    def test_plain_escape_hatch(self):
        with tempfile.TemporaryDirectory() as h:
            env = {"HOME": h, "SHELL": "/bin/bash", "PATH": "/usr/bin:/bin", "VOID_PLAIN": "1"}
            r = subprocess.run(["script", "-qc", str(_env.ROOT / "bin/void-shell"), "/dev/null"],
                               input="type void || echo NO-VOID; exit\n", env=env, capture_output=True, text=True, timeout=30)
            self.assertIn("NO-VOID", r.stdout)


class SpotifyDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_apps_state(self):
        apps = self.d / "Apps"
        apps.mkdir()
        self.assertEqual(spotify.apps_state(self.d), "invalid")
        (apps / "xpui.spa").write_text("x")
        self.assertEqual(spotify.apps_state(self.d), "stock")
        (apps / "xpui").mkdir()
        self.assertEqual(spotify.apps_state(self.d), "mixed")
        (apps / "xpui.spa").unlink()
        self.assertEqual(spotify.apps_state(self.d), "applied")

    def test_prefs_version_reads_only_version(self):
        p = self.d / "prefs"
        p.write_text('autologin.username="someone"\napp.last-launched-version="1.2.93.564.g1"\n')
        self.assertEqual(spotify.prefs_version(p), "1.2.93.564.g1")

    def test_target_never_guessed(self):
        a, b = {"method": "flatpak-system", "path": "/a"}, {"method": "rpm", "path": "/b"}
        cfg = {"spicetify": {}}
        self.assertEqual(spotify._target([a], cfg), a)
        self.assertIsNone(spotify._target([a, b], cfg))
        self.assertEqual(spotify._target([a, b], {"spicetify": {"target": "rpm"}}), b)

    def test_project_theme_files(self):
        for f in ("color.ini", "user.css", "theme.js"):
            self.assertTrue((spotify.SRC_THEME / f).is_file(), f)
        for f in ("manifest.json", "index.js"):
            self.assertTrue((spotify.SRC_APP / f).is_file(), f)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_js_syntax(self):
        for f in (spotify.SRC_THEME / "theme.js", spotify.SRC_APP / "index.js"):
            self.assertEqual(subprocess.run(["node", "--check", str(f)], capture_output=True).returncode, 0, f)


class _Mem(journal.Handler):
    kind = "mem"
    store: dict = {}
    fail_on: set = set()

    def get(self, key):
        return self.store.get(key, journal.ABSENT)

    def set(self, key, value):
        if key in self.fail_on:
            raise RuntimeError("boom")
        if value == journal.ABSENT:
            self.store.pop(key, None)
        else:
            self.store[key] = value


journal.register(_Mem)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.j = journal.Journal(Path(self.tmp.name))
        _Mem.store = {"a": "1"}
        _Mem.fail_on = set()

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_ahead_and_revert(self):
        self.assertTrue(self.j.change("mem", "a", "2"))
        self.assertTrue(self.j.change("mem", "b", "x"))         # b did not exist
        self.assertFalse(self.j.change("mem", "a", "2"))        # idempotent
        self.assertEqual(len(self.j.entries()), 2)
        self.assertEqual(self.j.revert_session(), 0)
        self.assertEqual(_Mem.store, {"a": "1"})

    def test_failed_set_still_journaled_and_revert_is_noop(self):
        _Mem.fail_on = {"a"}
        with self.assertRaises(RuntimeError):
            self.j.change("mem", "a", "2")
        self.assertEqual(self.j.entries()[0]["previous"], "1")
        _Mem.fail_on = set()
        self.assertEqual(self.j.revert_session(), 0)
        self.assertEqual(_Mem.store, {"a": "1"})

    def test_newer_user_value_kept_unless_forced(self):
        self.j.change("mem", "a", "2")
        _Mem.store["a"] = "user"
        seen = []
        self.j.revert_session(report=lambda o, *a: seen.append(o))
        self.assertEqual(seen, ["kept"])
        self.assertEqual(_Mem.store["a"], "user")

    def test_original_is_first_ever_value(self):
        self.j.change("mem", "a", "2")
        self.j.revert_session()
        _Mem.store["a"] = "crimson"            # another theme changed it in between
        self.j.change("mem", "a", "2")
        self.assertEqual(self.j.original()[0]["value"], "1")
        self.assertEqual(self.j.entries()[0]["previous"], "crimson")
        self.j.revert_session()
        self.assertEqual(_Mem.store["a"], "crimson")             # deactivate → state before THIS activation
        self.j.restore_original()
        self.assertEqual(_Mem.store["a"], "1")                   # restore → state before VOID ever

    def test_revert_continues_after_a_failure(self):
        self.j.change("mem", "a", "2")
        self.j.change("mem", "c", "3")
        _Mem.fail_on = {"c"}
        self.assertEqual(self.j.revert_session(), 1)
        self.assertEqual(_Mem.store["a"], "1")                   # still undone
        self.assertTrue(self.j.session_file.exists())            # kept for a retry


class FileOwnershipTests(unittest.TestCase):
    def test_never_overwrites_foreign_files(self):
        with tempfile.TemporaryDirectory() as t:
            saved = files.MANIFEST
            files.MANIFEST = Path(t) / "installed.json"
            try:
                f = Path(t) / "x.profile"
                f.write_text("user's own")
                self.assertFalse(files.install(f, "void", quiet=True))
                self.assertEqual(f.read_text(), "user's own")
                g = Path(t) / "y.profile"
                self.assertTrue(files.install(g, "v1", quiet=True))
                self.assertTrue(files.install(g, "v2", quiet=True))   # ours: updated
                g.write_text("edited by user")
                self.assertFalse(files.install(g, "v3", quiet=True))  # edited: kept
                self.assertEqual(files.uninstall_all(), [])           # edited file not removed
                self.assertTrue(f.exists() and g.exists())
            finally:
                files.MANIFEST = saved
