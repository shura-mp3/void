"""Wallpaper: rank the pack by actual image content, make monochrome copies, set the right monitor.

Ranking looks at pixels, never file names: saturation (how close to monochrome), the share of
strongly coloured pixels, darkness, tonal contrast, resolution and aspect for the target
monitor, and visual busyness. A contact sheet of the top candidates is written so you can check
the pick; override with `void wallpaper --pick FILE` or [wallpaper] pick in config.toml.

Originals are only ever read. Processed copies go to ~/.local/state/void-desktop/wallpaper/.
Setting the wallpaper uses Plasma's desktop scripting on the right monitor's desktop only; the
previous plugin/image/fill mode of that desktop is journaled and restored by `void deactivate`.
"""

from __future__ import annotations

import colorsys
import json
import sys
from pathlib import Path

from .. import config, paths, tokens
from . import kde, ui
from .journal import Handler, register

OUT = paths.STATE_DIR / "wallpaper"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
FALLBACK = paths.PROJECT_DIR / "assets" / "wallpapers" / "void-fallback.png"


def _pil() -> bool:
    import importlib.util
    return importlib.util.find_spec("PIL") is not None


def analyse(path: Path) -> dict | None:
    from PIL import Image, ImageFilter, ImageOps, ImageStat
    try:
        with Image.open(path) as im:
            if getattr(im, "is_animated", False):
                return None
            w, h = im.size
            if w * h > 150_000_000:
                return None
            im.draft("RGB", (320, 180))
            small = ImageOps.exif_transpose(im).convert("RGB").resize((160, 90))
    except Exception as e:  # noqa: BLE001 - unreadable / unsupported file
        print(f"  skip {path.name}: {e}", file=sys.stderr)
        return None
    px = list(small.get_flattened_data() if hasattr(small, "get_flattened_data") else small.getdata())
    n = len(px)
    sat = lum = colourful = 0.0
    lums = []
    for r, g, b in px:
        _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        y = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
        sat += s * v  # saturation weighted by brightness: dark noise isn't "colour"
        lum += y
        lums.append(y)
        if s > 0.30 and v > 0.25:
            colourful += 1
    mean = lum / n
    std = (sum((y - mean) ** 2 for y in lums) / n) ** 0.5
    edges = ImageStat.Stat(small.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0] / 255
    return {"path": str(path), "name": path.name, "w": w, "h": h, "sat": sat / n, "colourful": colourful / n,
            "lum": mean, "contrast": std, "busy": edges}


def score(a: dict, tw: int = 1920, th: int = 1080) -> float:
    mono = 1 - min(1.0, a["sat"] / 0.25)
    dark = max(0.0, 1 - abs(a["lum"] - 0.16) / 0.30)
    contrast = max(0.0, 1 - abs(a["contrast"] - 0.20) / 0.20)
    res = min(1.0, a["w"] / tw) * min(1.0, a["h"] / th)
    aspect = 1 - min(1.0, abs(a["w"] / a["h"] - tw / th) / (tw / th))
    calm = 1 - min(1.0, a["busy"] * 4)
    return (0.30 * mono + 0.20 * dark + 0.12 * contrast + 0.16 * res + 0.08 * aspect + 0.14 * calm
            - 0.45 * a["colourful"])


def rank(src: Path, tw: int, th: int) -> list[tuple[float, dict]]:
    files = sorted(p for p in src.rglob("*") if p.suffix.lower() in EXTS and p.is_file())
    ui.info(f"analysing {len(files)} image(s) in {src}")
    infos = [i for i in (analyse(p) for p in files) if i]
    return sorted(((score(i, tw, th), i) for i in infos), key=lambda x: -x[0])


def monochrome(im, w: int, h: int, darken: float = 0.10):
    """Cover-crop to w x h, fully desaturate, map tones onto VOID's black→white ramp, vignette."""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    im = ImageOps.fit(ImageOps.exif_transpose(im).convert("RGB"), (w, h), Image.LANCZOS)
    g = ImageOps.autocontrast(ImageOps.grayscale(im), cutoff=0.5)
    lo, hi = tokens.rgb(tokens.pal()["background"])[0], tokens.rgb(tokens.pal()["highlight"])[0]
    g = g.point(lambda v: int(lo + (hi - lo) * ((v / 255) ** 1.15) * (1 - darken)))
    mask = Image.new("L", (max(1, w // 8), max(1, h // 8)), 0)
    ImageDraw.Draw(mask).ellipse((-w // 40, -h // 40, w // 8 + w // 40, h // 8 + h // 40), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(1, w // 60))).resize((w, h), Image.BICUBIC)
    dark = Image.new("L", (w, h), lo)
    g = Image.composite(g, Image.blend(g, dark, 0.35), mask)
    return g.convert("RGB")


def contact_sheet(ranked: list[tuple[float, dict]], dest: Path, pick: str) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    top = ranked[:12]
    tw, th, pad, cols = 320, 180, 10, 4
    rows = (len(top) + cols - 1) // cols
    bgc = tokens.rgb(tokens.pal()["background"])
    sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + 40 + pad) + pad), bgc)
    d = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for i, (s, a) in enumerate(top):
        x, y = pad + (i % cols) * (tw + pad), pad + (i // cols) * (th + 40 + pad)
        with Image.open(a["path"]) as im:
            im.draft("RGB", (tw * 2, th * 2))
            sheet.paste(ImageOps.fit(ImageOps.exif_transpose(im).convert("RGB"), (tw, th)), (x, y))
        if a["path"] == pick:
            d.rectangle((x - 3, y - 3, x + tw + 2, y + th + 2), outline=tokens.rgb(tokens.pal()["highlight"]), width=3)
        d.text((x, y + th + 4), f"#{i + 1} {a['name'][:40]}", fill=tokens.rgb(tokens.pal()["text"]), font=font)
        d.text((x, y + th + 20), f"score {s:.2f} sat {a['sat']:.2f} colour {a['colourful']:.0%} {a['w']}x{a['h']}",
               fill=tokens.rgb(tokens.pal()["muted"]), font=font)
    sheet.save(dest, quality=88)


def fallback_image(w: int = 1920, h: int = 1080):
    """Procedural VOID wallpaper (used when the pack folder is missing): dark field + faint sigil."""
    from PIL import Image, ImageDraw, ImageFilter
    p = tokens.pal()
    im = Image.new("RGB", (w, h), tokens.rgb(p["background"]))
    d = ImageDraw.Draw(im)
    step = max(24, w // 64)
    grid = tokens.rgb(p["secondary"])
    for x in range(0, w, step):
        d.line((x, 0, x, h), fill=grid)
    for y in range(0, h, step):
        d.line((0, y, w, y), fill=grid)
    art = (paths.PROJECT_DIR / "assets" / "ascii" / "geass.txt").read_text().splitlines()
    cw, ch = max(2, w // 140), max(4, w // 70)
    ox, oy = (w - cw * max(len(l) for l in art)) // 2, (h - ch * len(art)) // 2
    ink = tokens.rgb(p["border"])
    for r, line in enumerate(art):
        for c, g in enumerate(line):
            x, y = ox + c * cw, oy + r * ch
            if g == "█":
                d.rectangle((x, y, x + cw - 1, y + ch - 1), fill=ink)
            elif g == "▀":
                d.rectangle((x, y, x + cw - 1, y + ch // 2 - 1), fill=ink)
            elif g == "▄":
                d.rectangle((x, y + ch // 2, x + cw - 1, y + ch - 1), fill=ink)
    return im.filter(ImageFilter.GaussianBlur(0.6))


def prepare(cfg: dict, target: dict | None, pick: str | None = None, interactive: bool = True) -> dict | None:
    """Pick + process. Returns {"image", "lock", "source"} or None (Pillow missing and no fallback)."""
    tw, th = (target or {}).get("width") or 1920, (target or {}).get("height") or 1080
    OUT.mkdir(parents=True, exist_ok=True)
    if not _pil():
        ui.warn("python3-pillow is not installed — can't analyse the pack; using the bundled fallback wallpaper")
        return {"image": str(FALLBACK), "lock": str(FALLBACK), "source": "bundled fallback"} if FALLBACK.exists() else None
    from PIL import Image, ImageFilter
    src = Path(cfg["wallpaper"]["source_dir"]).expanduser()
    pick = pick or cfg["wallpaper"].get("pick") or ""
    chosen = None
    if src.is_dir():
        ranked = rank(src, tw, th)
        if ranked:
            chosen = next((i for _, i in ranked if pick and Path(i["path"]).resolve() == Path(pick).expanduser().resolve()), None) \
                or ranked[0][1]
            contact_sheet(ranked, OUT / "candidates.jpg", chosen["path"])
            print("\n  rank  score  sat   colour  dark  size          file")
            for k, (s, i) in enumerate(ranked[:10], 1):
                print(f"  {k:>4}  {s:5.2f}  {i['sat']:.2f}  {i['colourful']:5.0%}  {i['lum']:.2f}  "
                      f"{i['w']}x{i['h']:<6}  {i['name']}{'   ◀ chosen' if i is chosen else ''}")
            ui.info(f"contact sheet: {OUT / 'candidates.jpg'}  (choose another: void wallpaper --pick FILE)")
            if interactive and not pick and not ui.ask(f"use {chosen['name']} for the right-hand monitor?", True):
                ui.info("keeping the procedural VOID wallpaper instead")
                chosen = None
    else:
        ui.warn(f"wallpaper folder not found: {src} — using the procedural VOID wallpaper")
    if chosen:
        with Image.open(chosen["path"]) as im:
            img = monochrome(im, tw, th)
        source = chosen["path"]
    else:
        img = fallback_image(tw, th)
        source = "procedural"
    img.save(OUT / "right.png")
    lock = Image.blend(img.filter(ImageFilter.GaussianBlur(8)), Image.new("RGB", img.size, tokens.rgb(tokens.pal()["background"])), 0.4)
    lock.save(OUT / "lockscreen.png")
    res = {"image": str(OUT / "right.png"), "lock": str(OUT / "lockscreen.png"), "source": source, "size": [tw, th]}
    st = config.JsonState(paths.WALLPAPER_STATE)
    st.data = res
    st.save()
    ui.ok(f"wallpaper: {Path(source).name if source != 'procedural' else 'procedural VOID'} → {OUT / 'right.png'} ({tw}x{th}, monochrome)")
    return res


# ════════════════════════════════════════════════════════════════════ Plasma (per desktop)
_JS_FIND = """
var want = "%s";
var ds = desktopsForActivity(currentActivity());
var hit = null;
for (var i = 0; i < ds.length; i++) {
    if (ds[i].screen < 0) continue;
    var g = screenGeometry(ds[i].screen);
    if (g.x + "," + g.y === want) { hit = ds[i]; }
}
"""


@register
class Wallpaper(Handler):
    """key = "x,y" (the monitor's logical position). value = {plugin, image, fill}."""
    kind = "wallpaper"

    def get(self, key):
        js = _JS_FIND % key + """
if (hit === null) { print("{}"); } else {
    var plugin = hit.wallpaperPlugin;
    hit.currentConfigGroup = ["Wallpaper", plugin, "General"];
    print(JSON.stringify({plugin: plugin, image: hit.readConfig("Image", ""), fill: String(hit.readConfig("FillMode", ""))}));
}"""
        out = kde.plasma_eval(js).strip().splitlines()
        return json.loads(out[-1]) if out else {}

    def set(self, key, value):
        if not value:
            return
        js = _JS_FIND % key + """
if (hit === null) { print("no desktop at %s"); } else {
    hit.wallpaperPlugin = %s;
    hit.currentConfigGroup = ["Wallpaper", %s, "General"];
    if (%s !== "") hit.writeConfig("Image", %s);
    if (%s !== "") hit.writeConfig("FillMode", %s);
    print("ok");
}""" % (key, *(json.dumps(x) for x in (value["plugin"], value["plugin"], value.get("image", ""), value.get("image", ""),
                                         value.get("fill", ""), value.get("fill", ""))))
        out = kde.plasma_eval(js)
        if "ok" not in out:
            raise RuntimeError(f"wallpaper: {out.strip()[-200:]}")

    def describe(self, key):
        return f"wallpaper of the monitor at {key}"


def plasma_value(image: str) -> dict:
    return {"plugin": "org.kde.image", "image": f"file://{image}", "fill": "2"}
