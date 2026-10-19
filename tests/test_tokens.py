"""Design-token tests: generated files are in sync, and VOID's interface is strictly monochrome."""

import re
import tomllib
import unittest

from _env import ROOT
from void import tokens

# every file that paints VOID's interface
VISUAL = [p for p in [*ROOT.joinpath("config").rglob("*"), *ROOT.joinpath("spicetify").rglob("*"),
                      *ROOT.joinpath("src").rglob("*.py"), *ROOT.joinpath("config/shell").rglob("*")] if p.is_file()]
HEX = re.compile(r"(?<![0-9A-Za-z&])#([0-9A-Fa-f]{6})\b")
SGR_RGB = re.compile(r"38;2;(\d+);(\d+);(\d+)")


class TokenTests(unittest.TestCase):
    def test_generated_files_in_sync(self):
        self.assertEqual(tokens.stale(), [], "run: bin/void tokens build")

    def test_palette_matches_the_brief(self):
        self.assertEqual(tokens.pal(), {
            "background": "#080808", "secondary": "#111111", "elevated": "#1B1B1B", "border": "#333333",
            "muted": "#777777", "secondary_text": "#AAAAAA", "text": "#E5E5E5", "highlight": "#F2F2F2"})

    def test_every_colour_is_grey(self):
        offenders = []
        for f in VISUAL:
            text = f.read_text(errors="ignore")
            for m in HEX.finditer(text):
                h = m.group(1).upper()
                if not (h[0:2] == h[2:4] == h[4:6]):
                    offenders.append(f"{f.relative_to(ROOT)}: #{h}")
            for m in SGR_RGB.finditer(text):
                if len(set(m.groups())) > 1:
                    offenders.append(f"{f.relative_to(ROOT)}: rgb{m.groups()}")
        ini = (ROOT / "spicetify/Themes/VOID/color.ini").read_text()
        for k, v in re.findall(r"^([\w-]+)\s*=\s*([0-9A-F]{6})$", ini, re.M):
            if not (v[0:2] == v[2:4] == v[4:6]):
                offenders.append(f"color.ini {k}={v}")
        kde = (ROOT / "config/kde/VOIDMonochrome.colors").read_text()
        for r, g, b in re.findall(r"=(\d+),(\d+),(\d+)$", kde, re.M):
            if not (r == g == b):
                offenders.append(f"VOIDMonochrome.colors {r},{g},{b}")
        self.assertEqual(offenders, [])

    def test_text_contrast(self):
        p = tokens.pal()
        self.assertGreaterEqual(tokens.contrast(p["text"], p["background"]), 15)
        self.assertGreaterEqual(tokens.contrast(p["secondary_text"], p["background"]), 7)   # AAA
        # the brief's muted grey is just under AA for small text: used for labels only, never body text
        self.assertGreaterEqual(tokens.contrast(p["muted"], p["background"]), 4.4)
        for i in range(1, 16):
            self.assertGreaterEqual(tokens.contrast(tokens.ansi(i), p["background"]), 3.0, f"ANSI {i}")

    def test_ansi_steps_distinguishable(self):
        lum = sorted(tokens.luminance(tokens.ansi(i)) for i in range(16))
        self.assertEqual(len(set(round(x, 3) for x in lum)), 16)

    def test_spicetify_keys_complete(self):
        """Every --spice-* variable the theme and custom app use is defined by color.ini."""
        keys = set(re.findall(r"^([\w-]+)\s*=", (ROOT / "spicetify/Themes/VOID/color.ini").read_text(), re.M))
        used = set()
        for f in (ROOT / "spicetify/Themes/VOID/user.css", ROOT / "spicetify/CustomApps/void/index.js"):
            used |= set(re.findall(r"--spice-(?:rgb-)?([a-z][a-z-]*[a-z])(?![-\w$])", f.read_text()))
        used |= set(re.findall(r'V\("([a-z-]+)"\)', (ROOT / "spicetify/CustomApps/void/index.js").read_text()))
        self.assertEqual(used - keys, set())

    def test_default_config_documents_every_key(self):
        from void import config
        self.assertEqual(tomllib.loads((ROOT / "config/void.toml").read_text()), config.DEFAULTS)

    def test_css_balanced(self):
        css = (ROOT / "spicetify/Themes/VOID/user.css").read_text()
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        self.assertEqual(css.count("{"), css.count("}"))
