"""Frame renderer for the IconVideo tool.

Recreates the TikTok map/icon explainer style: flat vector art on a 1080x1920
(9:16) canvas at 30 fps, off-white background, kinetic word-by-word text.

Scene format (list of dicts):
    {"start": float, "end": float,
     "bg": {...},                       # one of the bg types below
     "text": [{"w": "word", "t": sec}, ...]}  # t = absolute seconds

bg types:
    {"type": "map", "focus": ["PAK"], "highlight": {"PAK": "#35a05a"},
     "labels": {"PAK": "Pakistan"}, "flags": True, "zoom": "in"|"out"|"pan"}
    {"type": "icons", "items": [{"path": "/abs/icon.png",
                                 "label": "Worker", "callout": "Thousands"}, ...]}
    {"type": "photo", "path": "/abs/photo.jpg", "kenburns": "in"|"out"}
    {"type": "video", "path": "/abs/clip.mp4"}
    {"type": "plain"}

No side effects on import. No secrets involved.
"""

import glob
import json
import math
import os
import shutil
import subprocess
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

# ---------------------------------------------------------------- constants
W, H = 1080, 1920
BG = (250, 250, 247, 255)          # #FAFAF7
GRAY_FILL = "#E5E5E5"
GRAY_LINE = "#D4D4D4"
TEXT_GRAY = (85, 85, 85, 255)      # #555555
PILL_BG = (34, 34, 34, 255)       # #222
PILL_FG = (255, 255, 255, 255)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

_HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(_HERE, "..", "assets")
COUNTRIES_JSON = os.path.join(ASSETS, "maps", "countries.json")
FLAGS_DIR = os.path.join(ASSETS, "maps", "flags")

# Rough lon/lat polygons used when assets/maps/countries.json is missing.
_FALLBACK_COUNTRIES = {
    "PAK": {"name": "Pakistan", "alpha2": "PK",
            "polys": [[[61.0, 23.5], [75.5, 23.5], [75.5, 37.1],
                       [61.0, 37.1], [61.0, 23.5]]]},
    "SAU": {"name": "Saudi Arabia", "alpha2": "SA",
            "polys": [[[34.6, 16.3], [55.7, 16.3], [55.7, 32.2],
                       [34.6, 32.2], [34.6, 16.3]]]},
    "TUR": {"name": "Turkey", "alpha2": "TR",
            "polys": [[[25.7, 35.8], [45.0, 35.8], [45.0, 42.1],
                       [25.7, 42.1], [25.7, 35.8]]]},
}


# ---------------------------------------------------------------- helpers
def _font(path, size):
    return ImageFont.truetype(path, size)


def _ease(p):
    """Smoothstep 0..1."""
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def _ease_out_back(p):
    c1 = 1.70158
    c3 = c1 + 1
    p = min(1.0, max(0.0, p))
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


def _shade(hex_color, factor):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (int(r * factor), int(g * factor), int(b * factor), 255)


# ALPHA3 -> ALPHA2 for flag PNG lookup when the dataset has no alpha2 field.
_ALPHA3_TO_ALPHA2 = {
    "PAK": "PK", "SAU": "SA", "TUR": "TR", "IND": "IN", "USA": "US",
    "GBR": "GB", "CHN": "CN", "ARE": "AE", "QAT": "QA", "KWT": "KW",
    "BHR": "BH", "OMN": "OM", "IRN": "IR", "AFG": "AF", "BGD": "BD",
    "LKA": "LK", "NPL": "NP", "MYS": "MY", "IDN": "ID", "DEU": "DE",
    "FRA": "FR", "ITA": "IT", "ESP": "ES", "RUS": "RU", "JPN": "JP",
    "KOR": "KR", "AUS": "AU", "CAN": "CA", "BRA": "BR", "EGY": "EG",
    "NGA": "NG", "ZAF": "ZA",
}


def _flatten_polys(value):
    """GeoJSON MultiPolygon value -> flat list of rings.

    value = [polygon, ...], polygon = [ring, ...], ring = [[lon, lat], ...].
    Tolerates a polygon element that is already a single ring.
    """
    rings = []
    for poly in value:
        if not isinstance(poly, list) or not poly:
            continue
        first = poly[0]
        if (isinstance(first, list) and first
                and all(isinstance(n, (int, float)) for n in first)):
            rings.append(poly)  # already a ring
        else:
            for ring in poly:
                if isinstance(ring, list) and ring:
                    rings.append(ring)
    return rings


def _normalize_countries(raw):
    """Accept {ALPHA3: {name, alpha2, polys}} or {ALPHA3: multipolygon}."""
    out = {}
    for code, v in raw.items():
        if isinstance(v, dict) and "polys" in v:
            out[code] = v
        elif isinstance(v, list):
            rings = _flatten_polys(v)
            if rings:
                out[code] = {"name": code,
                             "alpha2": _ALPHA3_TO_ALPHA2.get(code, ""),
                             "polys": rings}
    return out


def load_countries():
    """Load {ALPHA3: {name, alpha2, polys}} from countries.json or fallback."""
    try:
        with open(COUNTRIES_JSON, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return dict(_FALLBACK_COUNTRIES)
    if isinstance(raw, dict) and raw:
        norm = _normalize_countries(raw)
        if norm:
            return norm
    return dict(_FALLBACK_COUNTRIES)


def country_bbox(country):
    xs, ys = [], []
    for ring in country["polys"]:
        for lon, lat in ring:
            xs.append(lon)
            ys.append(lat)
    return (min(xs), min(ys), max(xs), max(ys))


def _pad_bbox(bbox, frac):
    minlon, minlat, maxlon, maxlat = bbox
    dx = (maxlon - minlon) * frac
    dy = (maxlat - minlat) * frac
    return (minlon - dx, minlat - dy, maxlon + dx, maxlat + dy)


def project(lon, lat, bbox, W=W, H=H):
    """Equirectangular projection: fit bbox width to W, keep aspect, crop Y."""
    minlon, minlat, maxlon, maxlat = bbox
    s = W / max(maxlon - minlon, 1e-6)
    x = (lon - minlon) * s
    y = H * 0.5 - (lat - (minlat + maxlat) / 2.0) * s
    return x, y


def draw_pill(draw, cx, cy, text, font_size=44,
              bg=PILL_BG, fg=PILL_FG):
    """Dark rounded pill with white bold text, centered at (cx, cy)."""
    font = _font(FONT_BOLD, font_size)
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    px, py = 30, 16
    half = tw / 2 + px
    cx = min(max(cx, half + 16), W - half - 16)  # keep pill on screen
    x0, y0 = cx - tw / 2 - px, cy - th / 2 - py
    x1, y1 = cx + tw / 2 + px, cy + th / 2 + py
    draw.rounded_rectangle([x0, y0, x1, y1], radius=font_size, fill=bg)
    draw.text((cx - tw / 2 - bb[0], cy - th / 2 - bb[1]),
              text, font=font, fill=fg)


# ---------------------------------------------------------------- map bg
def _tight_bbox(countries, code):
    c = countries.get(code)
    if not c:
        return None
    return _pad_bbox(country_bbox(c), 0.35)


def camera_bbox(bg, countries, p):
    """Animated (minlon, minlat, maxlon, maxlat) for the map camera."""
    focus = bg.get("focus", []) or []
    zoom = bg.get("zoom", "in")

    if zoom == "pan" and len(focus) >= 2:
        b0 = _tight_bbox(countries, focus[0])
        b1 = _tight_bbox(countries, focus[-1])
    else:
        all_boxes = [country_bbox(c) for c in countries.values()]
        wide = _pad_bbox((
            min(b[0] for b in all_boxes), min(b[1] for b in all_boxes),
            max(b[2] for b in all_boxes), max(b[3] for b in all_boxes),
        ), 0.12)
        tight = _tight_bbox(countries, focus[0]) if focus else None
        if tight is None:
            return wide
        if zoom == "in":
            b0, b1 = wide, tight
        elif zoom == "pan":
            b0 = b1 = tight  # single focus: hold the close-up, no drift
        else:
            b0, b1 = tight, wide

    if b0 is None or b1 is None:
        b0 = b1 = b0 or b1
    e = _ease(p)
    return tuple(a + (b - a) * e for a, b in zip(b0, b1))


def paste_flag(img, alpha2, cx, cy, width=120):
    """Paste assets/maps/flags/<alpha2>.png at (cx, cy); skip if missing."""
    if not alpha2:
        return
    path = os.path.join(FLAGS_DIR, "%s.png" % alpha2.lower())
    if not os.path.exists(path):
        return
    try:
        flag = Image.open(path).convert("RGBA")
    except OSError:
        return
    h = int(flag.height * width / max(flag.width, 1))
    flag = flag.resize((width, h), Image.LANCZOS)
    img.paste(flag, (int(cx - width / 2), int(cy - h / 2)), flag)


def draw_map(img, bg, countries, p):
    draw = ImageDraw.Draw(img)
    bbox = camera_bbox(bg, countries, p)
    highlight = bg.get("highlight", {}) or {}
    labels = bg.get("labels", {}) or {}
    show_flags = bg.get("flags", False)

    for code, c in countries.items():
        polys = []
        for ring in c["polys"]:
            pts = [project(lon, lat, bbox, W, H) for lon, lat in ring]
            if len(pts) >= 3:
                polys.append(pts)
        if code in highlight:
            fill = highlight[code]
            outline = _shade(fill, 0.72)
        else:
            fill, outline = GRAY_FILL, GRAY_LINE
        for poly in polys:
            draw.polygon(poly, fill=fill, outline=outline, width=3)

    for code in highlight:
        c = countries.get(code)
        if not c:
            continue
        xs, ys = [], []
        for ring in c["polys"]:
            for lon, lat in ring:
                x, y = project(lon, lat, bbox, W, H)
                xs.append(x)
                ys.append(y)
        # skip flag/label when the country is fully off-screen
        if max(xs) < 0 or min(xs) > W or max(ys) < 0 or min(ys) > H:
            continue
        cx = (min(xs) + max(xs)) / 2
        if show_flags:
            paste_flag(img, code,
                       cx, (min(ys) + max(ys)) / 2 - 30)
        label = labels.get(code)
        if label:
            ly = min(max(ys) + 100, H - 150)
            draw_pill(draw, cx, ly, label, font_size=44)


# ---------------------------------------------------------------- icons bg
_PLACEHOLDER_COLORS = [
    (52, 152, 219, 255), (46, 204, 113, 255),
    (230, 126, 34, 255), (155, 89, 182, 255),
]

_icon_cache = {}


def _placeholder_icon(label, size=300):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = _PLACEHOLDER_COLORS[abs(hash(label)) % len(_PLACEHOLDER_COLORS)]
    d.ellipse([10, 10, size - 10, size - 10], fill=color)
    letter = (label or "?").strip()[:1].upper()
    font = _font(FONT_BOLD, int(size * 0.42))
    bb = d.textbbox((0, 0), letter, font=font)
    d.text((size / 2 - (bb[2] - bb[0]) / 2 - bb[0],
            size / 2 - (bb[3] - bb[1]) / 2 - bb[1]),
           letter, font=font, fill=(255, 255, 255, 255))
    return img


def _get_icon(path, label, size=300):
    key = (path, label, size)
    if key in _icon_cache:
        return _icon_cache[key]
    icon = None
    if path and os.path.exists(path):
        try:
            icon = ImageOps.fit(Image.open(path).convert("RGBA"),
                                (size, size), Image.LANCZOS)
        except OSError:
            icon = None
    if icon is None:
        icon = _placeholder_icon(label or "?", size)
    _icon_cache[key] = icon
    return icon


def draw_icons(img, bg, t_scene):
    """Up to 3 icons in a row with staggered draw-on (radial reveal + pop)."""
    items = (bg.get("items") or [])[:3]
    n = len(items)
    if n == 0:
        return
    draw = ImageDraw.Draw(img)
    cy = H * 0.52
    slot = 360
    for i, item in enumerate(items):
        cx = W / 2 + (i - (n - 1) / 2.0) * slot
        local = t_scene - i * 0.25
        if local < 0:
            continue
        pr = min(1.0, local / 0.55)
        scale = 0.5 + 0.5 * _ease_out_back(pr)
        size = max(8, int(300 * scale))
        icon = _get_icon(item.get("path"), item.get("label"), 300)
        icon = icon.resize((size, size), Image.LANCZOS)

        rad = int(size / 2 * min(1.0, pr * 1.25))
        radial = Image.new("L", (size, size), 0)
        md = ImageDraw.Draw(radial)
        md.ellipse([size / 2 - rad, size / 2 - rad,
                    size / 2 + rad, size / 2 + rad], fill=255)
        # combine reveal mask with the icon's own alpha (avoids dark fringe)
        mask = ImageChops.multiply(icon.getchannel("A"), radial)
        img.paste(icon, (int(cx - size / 2), int(cy - size / 2)), mask)

        callout = item.get("callout")
        if callout and pr > 0.35:
            draw_pill(draw, cx, cy - size / 2 - 70, callout, font_size=36)

        label = item.get("label")
        if label:
            font = _font(FONT_REG, 48)
            bb = draw.textbbox((0, 0), label, font=font)
            draw.text((cx - (bb[2] - bb[0]) / 2,
                       cy + size / 2 + 40),
                      label, font=font, fill=TEXT_GRAY)


# ---------------------------------------------------------------- photo bg
_photo_cache = {}


def _load_photo(path):
    """Cover-fit photo with ~12% headroom for the Ken Burns zoom."""
    if path in _photo_cache:
        return _photo_cache[path]
    img = Image.open(path).convert("RGB")
    s = max(W / img.width, H / img.height) * 1.12
    img = img.resize((max(1, int(img.width * s)),
                      max(1, int(img.height * s))), Image.LANCZOS)
    _photo_cache[path] = img
    return img


def draw_photo(img, bg, p):
    """Full-bleed photo, cover-fit, slow Ken Burns zoom. Missing file -> skip."""
    path = bg.get("path")
    if not path or not os.path.isfile(path):
        return
    try:
        base = _load_photo(path)
    except OSError:
        return
    kb = bg.get("kenburns", "in")
    z = 1.0 + 0.08 * (p if kb == "in" else 1.0 - p)
    bw, bh = base.width, base.height
    zw, zh = max(1, int(bw / 1.12 / z)), max(1, int(bh / 1.12 / z))
    x0, y0 = (bw - zw) // 2, (bh - zh) // 2
    crop = base.crop((x0, y0, x0 + zw, y0 + zh)).resize((W, H), Image.LANCZOS)
    img.paste(crop.convert("RGBA"), (0, 0))


# ---------------------------------------------------------------- text overlay
def draw_text(img, words, T):
    """Kinetic text: words appear at their timestamp, stay till scene end."""
    vis = [(w["w"], w["t"]) for w in words if w["t"] <= T]
    if not vis:
        return img
    font = _font(FONT_REG, 64)
    meas = ImageDraw.Draw(img)

    # wrap to ~12 chars per line
    lines, cur, cur_len = [], [], 0
    for w, t in vis:
        add = len(w) + (1 if cur else 0)
        if cur and cur_len + add > 12:
            lines.append(cur)
            cur, cur_len = [(w, t)], len(w)
        else:
            cur.append((w, t))
            cur_len += add
    if cur:
        lines.append(cur)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    line_h = 86
    y = H * 0.24 - (line_h * len(lines)) / 2
    for line in lines:
        total = sum(meas.textbbox((0, 0), w + " ", font=font)[2]
                    for w, _ in line)
        x = (W - total) / 2
        for w, t in line:
            alpha = int(255 * min(1.0, max(0.0, (T - t) / 0.12)))
            if alpha > 0:
                # halka sa shadow taake photo/video background par bhi parha jaye
                d.text((x + 3, y + 3), w, font=font,
                       fill=(0, 0, 0, int(alpha * 0.35)))
                d.text((x, y), w, font=font,
                       fill=(85, 85, 85, alpha))
            x += meas.textbbox((0, 0), w + " ", font=font)[2]
        y += line_h
    return Image.alpha_composite(img, overlay)


# ---------------------------------------------------------------- frame + render
def render_frame(scene, t, countries=None):
    """Render a single RGBA frame for absolute time t."""
    if countries is None:
        countries = load_countries()
    img = Image.new("RGBA", (W, H), BG)
    dur = max(scene["end"] - scene["start"], 1e-6)
    t_scene = t - scene["start"]
    p = min(1.0, max(0.0, t_scene / dur))
    bg = scene.get("bg", {"type": "plain"})
    btype = bg.get("type", "plain")
    if btype == "map":
        draw_map(img, bg, countries, p)
    elif btype == "icons":
        draw_icons(img, bg, t_scene)
    elif btype == "photo":
        draw_photo(img, bg, p)
    # "plain": empty background; "video" is handled per-segment in render_scenes
    img = draw_text(img, scene.get("text", []) or [], t)
    return img


def _encode_frames(pattern, out_mp4, fps):
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", pattern,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + r.stderr[-2000:])


def _render_pil_segment(scene, seg_mp4, countries, tmp, si, fps):
    """map/icons/plain/photo scene -> PIL frames -> silent mp4 segment."""
    n = max(1, int(round((scene["end"] - scene["start"]) * fps)))
    for i in range(n):
        t = scene["start"] + i / fps
        frame = render_frame(scene, t, countries)
        frame.convert("RGB").save(
            os.path.join(tmp, "p%02d_%04d.png" % (si, i)))
    try:
        _encode_frames(os.path.join(tmp, "p%02d_%%04d.png" % si), seg_mp4, fps)
    finally:
        for fp in glob.glob(os.path.join(tmp, "p%02d_*.png" % si)):
            try:
                os.remove(fp)
            except OSError:
                pass


def _render_video_segment(scene, seg_mp4, tmp, si, fps):
    """video scene: ffmpeg trims/scales the stock clip, PIL overlays text."""
    bg = scene["bg"]
    path = bg.get("path")
    dur = max(scene["end"] - scene["start"], 0.5)
    words = scene.get("text", []) or []
    pat = os.path.join(tmp, "v%02d_%%04d.png" % si)
    vf = ("scale=1080:1920:force_original_aspect_ratio=increase,"
          "crop=1080:1920,fps=%d" % fps)
    cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", path,
           "-t", "%.3f" % dur, "-vf", vf, pat]
    r = subprocess.run(cmd, capture_output=True, text=True)
    frames = sorted(glob.glob(os.path.join(tmp, "v%02d_*.png" % si)))
    if r.returncode != 0 or not frames:
        # corrupt/short clip -> downgrade to plain PIL segment
        scene["bg"] = {"type": "plain"}
        _render_pil_segment(scene, seg_mp4, None, tmp, si, fps)
        return
    for idx, fp in enumerate(frames):
        T = scene["start"] + idx / fps
        im = Image.open(fp).convert("RGBA")
        im = draw_text(im, words, T)
        im.convert("RGB").save(fp)
    try:
        _encode_frames(pat, seg_mp4, fps)
    finally:
        for fp in glob.glob(os.path.join(tmp, "v%02d_*.png" % si)):
            try:
                os.remove(fp)
            except OSError:
                pass


def render_scenes(scenes, out_mp4, fps=30):
    """Render each scene to a silent mp4 segment, then concat to out_mp4.

    Scene bg types map/icons/plain/photo render via PIL; video scenes trim
    the stock clip with ffmpeg and overlay kinetic text per frame.
    """
    countries = load_countries()
    tmp = tempfile.mkdtemp(prefix="iconvideo_")
    try:
        segments = []
        for si, s in enumerate(scenes):
            seg = os.path.join(tmp, "seg_%02d.mp4" % si)
            bg = s.get("bg") or {}
            if (bg.get("type") == "video" and bg.get("path")
                    and os.path.isfile(bg["path"])):
                _render_video_segment(s, seg, tmp, si, fps)
            else:
                if bg.get("type") == "video":
                    s["bg"] = {"type": "plain"}  # missing clip -> plain
                _render_pil_segment(s, seg, countries, tmp, si, fps)
            segments.append(seg)
        lst = os.path.join(tmp, "concat.txt")
        with open(lst, "w") as f:
            for seg in segments:
                f.write("file '%s'\n" % seg)
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
               "-c", "copy", out_mp4]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg concat failed:\n" + r.stderr[-2000:])
        return out_mp4
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
