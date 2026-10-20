"""VOID ⇄ Crimson switching, end to end, in sandboxed homes (KDE / systemd / Spicetify test doubles).

    python3 -m unittest tests.test_switching -v
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import _env
import fixtures as fx

TMUX = Path(tempfile.gettempdir()) / "void-test-tmux"
os.environ.setdefault("TMUX_TMPDIR", str(TMUX))
TMUX.mkdir(exist_ok=True)
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is needed to run the Plasma scripting test double")
class CrimsonToVoidAndBack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="void-switch-")
        self.home = Path(self.tmp.name)
        fx.crimson_home(self.home)
        self.plasma = fx.plasmashell(self.home)
        self.before = fx.snapshot(self.home)

    def tearDown(self):
        self.plasma.kill()
        self.plasma.wait()
        fx.void(self.home, "stop")
        self.tmp.cleanup()

    def activate(self, *extra, ok=True, **env):
        r = fx.void(self.home, "activate", "--no-launch", *extra, **env)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def journal(self, name):
        return json.loads((self.home / ".local/state/void-desktop/switch" / name).read_text())

    def test_activate_applies_void_everywhere(self):
        self.activate()
        s = fx.snapshot(self.home)
        g = s["ini"]["kdeglobals"]["[General]"]
        self.assertEqual(g["ColorScheme"], "VOIDMonochrome")
        self.assertNotIn("AccentColor", g)            # Crimson's crimson accent removed
        self.assertEqual(g["accentColorFromWallpaper"], "false")
        self.assertEqual(s["ini"]["breezerc"]["[Common]"]["ShadowColor"], "0,0,0")
        self.assertEqual(s["ini"]["konsolerc"]["[Desktop Entry]"]["DefaultProfile"], "VOID.profile")
        rules = s["ini"]["kwinrulesrc"]
        self.assertEqual(rules["[General]"]["rules"].split(","), ["8d244560-c71b-4a1e-9f2b-0b080dc7a110", "void-dashboard-0808f2f2"])
        self.assertEqual(rules["[void-dashboard-0808f2f2]"]["position"], "2560,0")
        self.assertEqual(rules["[void-dashboard-0808f2f2]"]["size"], "1920,1080")
        # wallpapers: BOTH monitors, each desktop found by its screen geometry
        left, right = s["desktops"]
        limg = left["config"]["Wallpaper/org.kde.image/General"]["Image"]
        rimg = right["config"]["Wallpaper/org.kde.image/General"]["Image"]
        self.assertTrue(limg.endswith("/assets/wallpapers/generated/DP-1.png"), limg)
        self.assertTrue(rimg.endswith("/assets/wallpapers/generated/HDMI-A-1.png"), rimg)
        from PIL import Image
        with Image.open(limg[7:]) as a, Image.open(rimg[7:]) as b:   # each at its monitor's real resolution
            self.assertEqual((a.size, b.size), ((2560, 1440), (1920, 1080)))
        # global shortcuts: Crimson's keys set aside, VOID's on the same keys
        sc = s["ini"]["kglobalshortcutsrc"]
        self.assertEqual(sc["[services][crimson-lyrics.desktop]"]["_launch"], "none")
        self.assertEqual(sc["[services][void-lyrics.desktop]"]["_launch"], "Meta+Alt+L")
        self.assertEqual(sc["[services][void-dashboard-toggle.desktop]"]["_launch"], "Meta+Alt+D")
        self.assertEqual(sc["[kwin]"], {"Overview": "Meta+W,Meta+W,Toggle Overview"})   # unrelated keys untouched
        self.assertTrue((self.home / ".local/share/applications/void-lyrics.desktop").exists())
        # autoload at login + blur behind the translucent grid tiles
        self.assertIn("launch --autostart", (self.home / ".config/autostart/void-dashboard.desktop").read_text())
        self.assertEqual(s["ini"]["kwinrc"]["[Plugins]"]["blurEnabled"], "true")
        # Crimson paused: one Spotify watcher, one appearance manager
        self.assertEqual(s["systemd"]["crimson-core.service"], {"active": False, "enabled": False})
        self.assertEqual(s["systemd"]["crimson-dashboard.service"], {"active": False, "enabled": False})
        # Spotify
        sp = s["spicetify"]
        self.assertEqual(sp["Setting"]["current_theme"], "VOID")
        self.assertEqual(sp["AdditionalOptions"]["custom_apps"].split("|"), ["void"])
        self.assertEqual(sp["AdditionalOptions"]["extensions"].split("|"), ["fullAppDisplay.js", "keyboardShortcut.js"])
        self.assertIn("VOID Spotify", s["xpui_css"])
        self.assertEqual(self.journal("state.json")["status"], "active")
        # Kitty: VOID's block last (wins over Crimson's include), Crimson's line untouched
        kc = (self.home / ".config/kitty/kitty.conf").read_text()
        self.assertIn("include crimson.conf", kc)
        self.assertTrue(kc.rstrip().endswith("include void.conf\n# <<< VOID"))
        vc = (self.home / ".config/kitty/void.conf").read_text()
        self.assertIn(f"shell {_env.ROOT / 'bin/void-shell'}", vc)
        self.assertIn(f"--os-window-class void-lyrics {_env.ROOT / 'bin/void'} lyrics", vc)
        self.assertIn("enabled_layouts splits,stack,tall", vc)          # Crimson's layouts kept
        self.assertIn("include void-profile.conf", vc)
        self.assertNotIn("@VOID", vc)
        # files VOID installed
        self.assertTrue((self.home / ".local/share/konsole/VOID.profile").exists())
        self.assertTrue((self.home / ".local/share/color-schemes/VOIDMonochrome.colors").exists())

    def test_repeat_activation_is_idempotent(self):
        self.activate()
        s1, n1, o1 = fx.snapshot(self.home), len(self.journal("session.json")), self.journal("original.json")
        self.activate()
        self.assertEqual(fx.snapshot(self.home), s1)
        self.assertEqual(len(self.journal("session.json")), n1)
        self.assertEqual(self.journal("original.json"), o1)

    def test_deactivate_returns_exactly_to_crimson(self):
        self.activate()
        r = fx.void(self.home, "deactivate")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        after = fx.snapshot(self.home)
        self.assertEqual(after, self.before)
        self.assertEqual(self.journal("state.json")["status"], "inactive")
        self.assertFalse((self.home / ".config/autostart/void-dashboard.desktop").exists())   # autoload removed
        self.assertFalse((self.home / ".local/state/void-desktop/switch/session.json").exists())
        # repeated deactivation is a harmless no-op
        r2 = fx.void(self.home, "deactivate")
        self.assertEqual(r2.returncode, 0)
        self.assertIn("not active", r2.stdout)
        self.assertEqual(fx.snapshot(self.home), self.before)

    def test_switch_back_and_forth_twice(self):
        for _ in range(2):
            self.activate()
            self.assertEqual(fx.void(self.home, "deactivate").returncode, 0)
            self.assertEqual(fx.snapshot(self.home), self.before)
        # the original record is still the Crimson desktop from before the first activation
        orig = {(e["kind"], e["key"]): e["value"] for e in self.journal("original.json")}
        self.assertEqual(orig[("colorscheme", "global")]["scheme"], "CrimsonNight")

    def test_change_made_while_active_is_kept(self):
        self.activate()
        fx.write_ini(fx.kfile(self.home, "konsolerc"), {"Desktop Entry": {"DefaultProfile": "Mine.profile"},
                                                        "MainWindow": {"MenuBar": "Disabled"}})
        r = fx.void(self.home, "deactivate")
        self.assertEqual(r.returncode, 0)
        self.assertIn("kept your newer value", r.stdout)
        self.assertEqual(fx.read_ini(fx.kfile(self.home, "konsolerc"))["[Desktop Entry]"]["DefaultProfile"], "Mine.profile")
        # everything else is still back to Crimson
        self.assertEqual(fx.snapshot(self.home)["ini"]["kdeglobals"], self.before["ini"]["kdeglobals"])

    def _breeze_dark_style(self):
        # Nobara's default Plasma style: VOID switches it to Breeze "default" (which follows the colours)
        fx.write_ini(fx.kfile(self.home, "plasmarc"), {"Theme": {"name": "breeze-dark"}})
        self.before = fx.snapshot(self.home)

    def test_wallpaper_mismatch_fails_and_is_undone(self):
        """KScreen reports a monitor Plasma has no desktop for: activation must fail, not claim success."""
        state = json.loads((self.home / "plasma-desktops.json").read_text())
        state["screens"][1] = {"x": 3000, "y": 0, "width": 1920, "height": 1080}   # Plasma disagrees with KScreen
        (self.home / "plasma-desktops.json").write_text(json.dumps(state))
        self.before = fx.snapshot(self.home)
        r = self.activate(ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no desktop at 2560,0", r.stdout)
        self.assertEqual(fx.void(self.home, "deactivate").returncode, 0)
        self.assertEqual(fx.snapshot(self.home), self.before)

    def test_profile_minimal_makes_kitty_opaque(self):
        self.activate()
        self.assertEqual(fx.void(self.home, "profile", "minimal").returncode, 0)
        prof = (self.home / ".config/kitty/void-profile.conf").read_text()
        self.assertIn("background_opacity 1.0", prof)
        fx.void(self.home, "profile", "balanced")
        self.assertIn("background_opacity 0.96", (self.home / ".config/kitty/void-profile.conf").read_text())

    def test_kitty_edit_while_active_is_kept(self):
        self.activate()
        kc = self.home / ".config/kitty/kitty.conf"
        kc.write_text("font_size 13\n" + kc.read_text())          # you edit kitty.conf while VOID is on
        self.assertEqual(fx.void(self.home, "deactivate").returncode, 0)
        text = kc.read_text()
        self.assertTrue(text.startswith("font_size 13\n"))
        self.assertNotIn("VOID", text)
        self.assertEqual(text, "font_size 13\n" + self.before["kitty"]["kitty.conf"].decode())

    def test_partial_failure_is_recoverable(self):
        self._breeze_dark_style()
        r = self.activate(ok=False, STUB_FAIL="desktoptheme")
        self.assertEqual(r.returncode, 1)
        self.assertIn("void deactivate", r.stdout)
        self.assertEqual(self.journal("state.json")["status"], "failed")
        # the colour scheme was changed before the failure and is journaled
        self.assertEqual(fx.read_ini(fx.kfile(self.home, "kdeglobals"))["[General]"]["ColorScheme"], "VOIDMonochrome")
        r = fx.void(self.home, "deactivate")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(fx.snapshot(self.home), self.before)
        self.assertEqual(self.journal("state.json")["status"], "inactive")

    def test_failed_activation_can_be_retried(self):
        self._breeze_dark_style()
        self.activate(ok=False, STUB_FAIL="desktoptheme")
        self.activate()  # retry completes the activation
        self.assertEqual(self.journal("state.json")["status"], "active")
        self.assertEqual(fx.void(self.home, "deactivate").returncode, 0)
        self.assertEqual(fx.snapshot(self.home), self.before)

    def test_spicetify_apply_failure_rolls_back_spotify_only(self):
        r = self.activate(FAKE_SPICETIFY_FAIL_APPLY="1")
        self.assertIn("settings rolled back", r.stdout)
        s = fx.snapshot(self.home)
        self.assertEqual(s["spicetify"], self.before["spicetify"])     # Spotify config untouched
        self.assertEqual(s["ini"]["kdeglobals"]["[General]"]["ColorScheme"], "VOIDMonochrome")  # rest applied
        self.assertEqual(fx.void(self.home, "deactivate").returncode, 0)
        self.assertEqual(fx.snapshot(self.home)["ini"], self.before["ini"])

    def test_restore_returns_to_pre_void_and_uninstalls(self):
        self.activate()
        r = fx.void(self.home, "restore", "--uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(fx.snapshot(self.home), self.before)
        self.assertFalse((self.home / ".local/share/konsole/VOID.profile").exists())
        self.assertFalse((self.home / ".config/spicetify/Themes/VOID").exists())
        self.assertTrue((self.home / ".config/spicetify/Themes/Crimson/user.css").exists())  # Crimson's files untouched
        self.assertFalse((self.home / ".local/state/void-desktop/switch/original.json").exists())

    def test_backup_archive_holds_the_original_files(self):
        import tarfile
        self.activate()
        arc = Path(self.journal("state.json")["original_archive"])
        with tarfile.open(arc) as tf:
            names = tf.getnames()
            kd = tf.extractfile(".config/kdeglobals").read().decode()
        self.assertIn(".config/konsolerc", names)
        self.assertIn("CrimsonNight", kd)
        meta = json.loads(arc.with_suffix("").with_suffix(".json").read_text())
        self.assertIn(".config/spicetify/config-xpui.ini", meta["existed"])


@unittest.skipUnless(NODE, "node is needed to run the Plasma scripting test double")
class StockDesktop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="void-stock-")
        self.home = Path(self.tmp.name)
        fx.stock_home(self.home)
        self.plasma = fx.plasmashell(self.home)
        self.spa_before = {p.name: p.read_bytes() for p in (self.home / fx.SPOTIFY_REL / "Apps").glob("*.spa")}
        self.before = fx.snapshot(self.home)

    def tearDown(self):
        self.plasma.kill()
        self.plasma.wait()
        fx.void(self.home, "stop")
        self.tmp.cleanup()

    def test_stock_spotify_is_patched_then_returned_to_stock(self):
        r = fx.void(self.home, "activate", "--no-launch")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # VOID_YES never answers privileged questions: patching a stock Spotify needs an explicit yes
        self.assertIn("skipped: patching declined", r.stdout)
        self.assertEqual(fx.snapshot(self.home)["spa"], ["login.spa", "xpui.spa"])
        self.assertEqual(fx.void(self.home, "deactivate").returncode, 0)
        after = fx.snapshot(self.home)
        # the scheme had no explicit key; it comes back as the explicit, identical-looking BreezeDark
        self.assertEqual(after["ini"]["kdeglobals"].pop("[General]"), {"ColorScheme": "BreezeDark"})
        self.assertEqual(after, self.before)

    def test_approved_stock_patch_is_undone_byte_for_byte(self):
        rc, out = fx.void_tty(self.home, ["activate", "--no-launch"],
                              {"activate VOID now": "y", "let Spicetify patch Spotify now": "y"})
        self.assertEqual(rc, 0, out)
        self.assertIn("spicetify backup apply", out)
        s = fx.snapshot(self.home)
        self.assertEqual(s["spa"], [])                       # patched: .spa files replaced by xpui/
        self.assertIn("VOID Spotify", s["xpui_css"])
        r = fx.void(self.home, "deactivate")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("stock Spotify restored", r.stdout)
        spa_after = {p.name: p.read_bytes() for p in (self.home / fx.SPOTIFY_REL / "Apps").glob("*.spa")}
        self.assertEqual(spa_after, self.spa_before)
        self.assertFalse((self.home / fx.SPOTIFY_REL / "Apps/xpui").exists())

    def test_declining_activation_changes_nothing(self):
        rc, out = fx.void_tty(self.home, ["activate", "--no-launch"], {"activate VOID now": "n"})
        self.assertEqual(rc, 0, out)
        self.assertEqual(fx.snapshot(self.home), self.before)
        self.assertFalse((self.home / ".local/state/void-desktop/switch/session.json").exists())

    @unittest.skipIf(shutil.which("kitty"), "kitty is installed here, so VOID rightly themes it")
    def test_no_kitty_means_no_kitty_files(self):
        self.assertEqual(fx.void(self.home, "activate", "--no-launch").returncode, 0)
        self.assertFalse((self.home / ".config/kitty").exists())

    def test_default_scheme_is_deduced_and_restored(self):
        self.assertEqual(fx.void(self.home, "activate", "--no-launch").returncode, 0)
        self.assertEqual(fx.void(self.home, "deactivate").returncode, 0)
        g = fx.read_ini(fx.kfile(self.home, "kdeglobals"))["[General]"]
        self.assertEqual(g["ColorScheme"], "BreezeDark")  # from LookAndFeelPackage breezedark


class NoKde(unittest.TestCase):
    def test_refuses_cleanly_without_kde_tools(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            env_path = "/usr/bin:/bin"  # no stubs
            r = fx.void(home, "activate", "--no-launch", PATH=env_path)
            self.assertEqual(r.returncode, 1)
            self.assertIn("kwriteconfig6 not found", r.stdout)
            self.assertFalse((home / ".local/state/void-desktop/switch/session.json").exists())


if __name__ == "__main__":
    unittest.main()
