"""Wallpaper: rank the pack by actual image content, make monochrome copies, set the right monitor.

Ranking looks at pixels, never file names: saturation (how close to monochrome), the share of
strongly coloured pixels, darkness, tonal contrast, resolution and aspect for the target
monitor, and visual busyness. A contact sheet of the top candidates is written so you can check
the pick; override with `void wallpaper --pick FILE` or [wallpaper] pick in config.toml.

Originals are only ever read. Processed copies go to <project>/assets/wallpapers/generated/.
Both monitors get a VOID wallpaper (panorama split by real geometry, a matched pair, or one image
cropped per screen). Plasma's desktop scripting finds each monitor's desktop containment by its screen
geometry — never by containment id. Each desktop's previous plugin/image/fill mode is journaled and
restored by `void deactivate`; `verify()` reads the result back from Plasma.
"""

from __future__ import annotations

import colorsys
import json
import sys
from pathlib import Path

from .. import config, paths, tokens
from . import kde, ui
from .journal import Handler, register

OUT = paths.PROJECT_DIR / "assets" / "wallpapers" / "generated"   # git-ignored, per machine
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


def monochrome(im, w: int, h: int, darken: float = 0.10, vignette: bool = True):
    """Cover-crop to w x h, fully desaturate, map tones onto VOID's black→white ramp, vignette."""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    im = ImageOps.fit(ImageOps.exif_transpose(im).convert("RGB"), (w, h), Image.LANCZOS)
    g = ImageOps.autocontrast(ImageOps.grayscale(im), cutoff=0.5)
    lo, hi = tokens.rgb(tokens.pal()["background"])[0], tokens.rgb(tokens.pal()["highlight"])[0]
    g = g.point(lambda v: int(lo + (hi - lo) * ((v / 255) ** 1.15) * (1 - darken)))
    if not vignette:
        return g.convert("RGB")
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


def fallback_image(w: int = 1920, h: int = 1080, centre: tuple[float, float] = (0.5, 0.5), sigil_px: int | None = None):
    """Procedural VOID wallpaper (used when the pack folder is missing): dark grid + faint sigil.

    For two monitors one canvas spans the whole layout (continuous grid); the sigil sits at `centre`
    (fractions of the canvas) and is sized for a monitor `sigil_px` pixels wide.
    """
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
    sw = sigil_px or w
    cw, ch = max(2, sw // 140), max(4, sw // 70)
    ox = round(w * centre[0] - cw * max(len(l) for l in art) / 2)
    oy = round(h * centre[1] - ch * len(art) / 2)
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


def screen_size(o: dict) -> tuple[int, int]:
    """Physical pixel size of a monitor as it is shown (rotation and scaling applied)."""
    sc = float(o.get("scale") or 1.0)
    w, h = round(o["logical_width"] * sc), round(o["logical_height"] * sc)
    return (w, h) if w and h else (o.get("width") or 1920, o.get("height") or 1080)


def bbox(outs: list[dict]) -> tuple[int, int, int, int]:
    """Logical bounding box (x0, y0, x1, y1) of the monitor layout."""
    return (min(o["x"] for o in outs), min(o["y"] for o in outs),
            max(o["x"] + o["logical_width"] for o in outs), max(o["y"] + o["logical_height"] for o in outs))


def choose(ranked: list[tuple[float, dict]], outs: list[dict], picks: dict[str, str]) -> dict:
    """Decide the arrangement from real images and real geometry.

    panorama: one image wide and large enough to span the whole layout (split by geometry)
    pair:     two different images with matching tone/contrast, best one on the dashboard monitor
    single:   the same image cover-cropped for every monitor
    """
    by_path = {str(Path(i["path"]).resolve()): i for _, i in ranked}
    forced = {n: by_path.get(str(Path(f).expanduser().resolve())) for n, f in picks.items() if f}
    for n, f in picks.items():
        if f and not forced.get(n):
            ui.warn(f"picked file not found in the pack: {f}")
    names = [o["name"] for o in outs]
    if forced.get("all"):
        return {"mode": "single", "images": {n: forced["all"] for n in names}}
    if len(outs) == 1:
        return {"mode": "single", "images": {names[0]: forced.get(names[0]) or ranked[0][1]}}
    right, left = names[0], names[1]
    if forced.get(right) or forced.get(left):
        r = forced.get(right) or ranked[0][1]
        l = forced.get(left) or next((i for _, i in ranked if i is not r), r)
        return {"mode": "pair" if l is not r else "single", "images": {right: r, left: l}}
    best_score, best = ranked[0]
    x0, y0, x1, y1 = bbox(outs)
    span = (x1 - x0) / max(1, y1 - y0)
    need_w = sum(screen_size(o)[0] for o in outs)
    for sc, i in ranked:
        if sc < best_score * 0.85:
            break
        if i["w"] / i["h"] >= span * 0.9 and i["w"] >= need_w * 0.6:
            return {"mode": "panorama", "images": {n: i for n in names}, "panorama": i}
    for sc, i in ranked[1:]:
        if sc < best_score * 0.75:
            break
        if abs(i["lum"] - best["lum"]) <= 0.08 and abs(i["contrast"] - best["contrast"]) <= 0.08:
            return {"mode": "pair", "images": {right: best, left: i}}
    return {"mode": "single", "images": {n: best for n in names}}


def render(plan: dict, outs: list[dict]) -> dict[str, "object"]:
    """Images per monitor name, each exactly the monitor's physical resolution."""
    from PIL import Image
    out = {}
    if plan["mode"] == "panorama" or plan["mode"] == "procedural":
        x0, y0, x1, y1 = bbox(outs)
        s = max(screen_size(o)[0] / o["logical_width"] for o in outs)
        cw, ch = round((x1 - x0) * s), round((y1 - y0) * s)
        if plan["mode"] == "panorama":
            with Image.open(plan["panorama"]["path"]) as im:
                canvas = monochrome(im, cw, ch)
        else:
            left = min(outs, key=lambda o: o["x"])
            cx = ((left["x"] - x0) + left["logical_width"] / 2) / (x1 - x0)
            cy = ((left["y"] - y0) + left["logical_height"] / 2) / (y1 - y0)
            canvas = fallback_image(cw, ch, centre=(cx, cy), sigil_px=round(left["logical_width"] * s))
        for o in outs:
            box = (round((o["x"] - x0) * s), round((o["y"] - y0) * s),
                   round((o["x"] - x0 + o["logical_width"]) * s), round((o["y"] - y0 + o["logical_height"]) * s))
            out[o["name"]] = canvas.crop(box).resize(screen_size(o), Image.LANCZOS)
        return out
    for o in outs:
        with Image.open(plan["images"][o["name"]]["path"]) as im:
            out[o["name"]] = monochrome(im, *screen_size(o))
    return out


def preview(outs: list[dict], files: dict[str, str], dest: Path, width: int = 1600) -> None:
    """The monitors drawn in their real arrangement, for checking the result at a glance."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = bbox(outs)
    k = (width - 40) / (x1 - x0)
    sheet = Image.new("RGB", (width, round((y1 - y0) * k) + 70), tokens.rgb(tokens.pal()["secondary"]))
    d = ImageDraw.Draw(sheet)
    for o in outs:
        bx, by = 20 + round((o["x"] - x0) * k), 20 + round((o["y"] - y0) * k)
        bw, bh = round(o["logical_width"] * k), round(o["logical_height"] * k)
        with Image.open(files[o["name"]]) as im:
            sheet.paste(im.convert("RGB").resize((bw, bh)), (bx, by))
        d.rectangle((bx, by, bx + bw - 1, by + bh - 1), outline=tokens.rgb(tokens.pal()["border"]))
        d.text((bx + 6, by + bh + 8), f"{o['name']}  {screen_size(o)[0]}x{screen_size(o)[1]}  at {o['x']},{o['y']}",
               fill=tokens.rgb(tokens.pal()["text"]))
    sheet.save(dest)


def prepare(cfg: dict, outs: list[dict], right: dict | None = None, picks: dict | None = None,
            interactive: bool = True) -> dict | None:
    """Pick + render wallpapers for every enabled monitor (right/dashboard monitor first).

    Returns {"mode", "screens": {name: {"image", "x", "y", "source"}}, "lock", "preview"} or None.
    """
    outs = [o for o in outs if o.get("enabled", True)]
    if not outs:
        return None
    if not _pil():
        ui.warn("python3-pillow is not installed — can't analyse the pack; every monitor gets the bundled VOID wallpaper")
        if not FALLBACK.exists():
            return None
        return {"mode": "bundled", "lock": str(FALLBACK), "preview": "",
                "screens": {o["name"]: {"image": str(FALLBACK), "x": o["x"], "y": o["y"], "size": None,
                                        "source": "bundled fallback"} for o in outs}}
    from PIL import Image, ImageFilter
    if right:
        outs = [o for o in outs if o["name"] == right["name"]] + [o for o in outs if o["name"] != right["name"]]
    OUT.mkdir(parents=True, exist_ok=True)
    w_cfg = cfg["wallpaper"]
    picks = picks or {}
    picks = {"all": picks.get("all") or w_cfg.get("pick") or "",
             outs[0]["name"]: picks.get("right") or w_cfg.get("pick_right") or "",
             **({outs[1]["name"]: picks.get("left") or w_cfg.get("pick_left") or ""} if len(outs) > 1 else {})}
    src = Path(w_cfg["source_dir"]).expanduser()
    plan = {"mode": "procedural", "images": {}}
    if src.is_dir():
        rw, rh = screen_size(outs[0])
        ranked = [(s, i) for s, i in rank(src, rw, rh) if s > 0] or rank(src, rw, rh)
        if ranked:
            plan = choose(ranked, outs, picks)
            chosen = {i["path"] for i in plan["images"].values()}
            contact_sheet(ranked, OUT / "candidates.jpg", next(iter(chosen)))
            print("\n  rank  score  sat   colour  dark  size          file")
            for k, (s, i) in enumerate(ranked[:10], 1):
                tags = [n for n, im in plan["images"].items() if im is i]
                print(f"  {k:>4}  {s:5.2f}  {i['sat']:.2f}  {i['colourful']:5.0%}  {i['lum']:.2f}  "
                      f"{i['w']}x{i['h']:<6}  {i['name']}{'   ◀ ' + ', '.join(tags) if tags else ''}")
            print(f"\n  arrangement: {plan['mode']}")
            for o in outs:
                print(f"    {o['name']:10} {'(dashboard) ' if o is outs[0] else '            '}{plan['images'][o['name']]['name']}")
            ui.info(f"contact sheet: {OUT / 'candidates.jpg'}   (override: void wallpaper --left FILE --right FILE)")
            if interactive and not any(picks.values()) and not ui.ask("use these wallpapers?", True):
                ui.info("using the procedural VOID wallpapers instead")
                plan = {"mode": "procedural", "images": {}}
    else:
        ui.warn(f"wallpaper folder not found: {src} — using the procedural VOID wallpapers")
    images = render(plan, outs)
    screens = {}
    for o in outs:
        f = OUT / f"{o['name']}.png"
        images[o["name"]].save(f)
        screens[o["name"]] = {"image": str(f), "x": o["x"], "y": o["y"], "size": list(screen_size(o)),
                              "source": plan["images"][o["name"]]["path"] if plan["images"] else "procedural"}
    prim = next((o for o in outs if o.get("primary")), outs[0])
    li = images[prim["name"]]
    Image.blend(li.filter(ImageFilter.GaussianBlur(8)), Image.new("RGB", li.size, tokens.rgb(tokens.pal()["background"])), 0.4) \
        .save(OUT / "lockscreen.png")
    preview(outs, {n: v["image"] for n, v in screens.items()}, OUT / "preview.png")
    res = {"mode": plan["mode"], "screens": screens, "lock": str(OUT / "lockscreen.png"), "preview": str(OUT / "preview.png")}
    st = config.JsonState(paths.WALLPAPER_STATE)
    st.data = res
    st.save()
    for n, v in screens.items():
        ui.ok(f"wallpaper {n}: {Path(v['source']).name if v['source'] != 'procedural' else 'procedural VOID'} "
              f"→ {v['size'][0]}x{v['size'][1]} monochrome")
    ui.info(f"preview of both screens: {res['preview']}")
    return res


def verify(res: dict) -> list[str]:
    """Read every monitor's wallpaper back from Plasma and check the files. Returns problems."""
    problems = []
    for name, v in res["screens"].items():
        live = Wallpaper().get(f"{v['x']},{v['y']}")
        if not live:
            problems.append(f"{name}: Plasma has no desktop at {v['x']},{v['y']}")
        elif live.get("plugin") != "org.kde.image" or live.get("image") != f"file://{v['image']}":
            problems.append(f"{name}: Plasma reports {live.get('plugin')} {live.get('image')!r}, expected {v['image']}")
        if not v.get("size") or not _pil():
            continue
        from PIL import Image
        try:
            with Image.open(v["image"]) as im:
                if list(im.size) != list(v["size"]):
                    problems.append(f"{name}: image is {im.size}, monitor is {tuple(v['size'])}")
        except OSError as e:
            problems.append(f"{name}: {e}")
    return problems


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
