"""Local map library: country polygons + flag PNGs, no API key needed.

Source: world-atlas@2 countries-110m.json (TopoJSON, Natural Earth).
Run build_library() once to download/decode; query functions then read
the local ~/workspace/iconvideo/assets/maps/countries.json.

countries.json format: {ALPHA3: [polygon, ...]},
each polygon = [ring, ...], each ring = [[lon, lat], ...].
"""

import json
import os

import requests

MAPS_DIR = os.path.expanduser("~/workspace/iconvideo/assets/maps")
FLAGS_DIR = os.path.join(MAPS_DIR, "flags")
COUNTRIES_JSON = os.path.join(MAPS_DIR, "countries.json")
TOPO_URL = "https://unpkg.com/world-atlas@2/countries-110m.json"
FLAG_URL = "https://flagcdn.com/w160/{}.png"
TIMEOUT = 60
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# ISO 3166-1 numeric -> alpha-3 (superset; at least every flagged country)
NUMERIC_TO_ALPHA3 = {
    4: "AFG", 8: "ALB", 12: "DZA", 24: "AGO", 32: "ARG", 51: "ARM",
    36: "AUS", 40: "AUT", 31: "AZE", 50: "BGD", 112: "BLR", 56: "BEL",
    68: "BOL", 70: "BIH", 72: "BWA", 76: "BRA", 100: "BGR", 854: "BFA",
    116: "KHM", 120: "CMR", 124: "CAN", 140: "CAF", 148: "TCD", 152: "CHL",
    156: "CHN", 170: "COL", 178: "COG", 180: "COD", 188: "CRI", 384: "CIV",
    191: "HRV", 192: "CUB", 196: "CYP", 203: "CZE", 208: "DNK", 262: "DJI",
    214: "DOM", 218: "ECU", 818: "EGY", 222: "SLV", 226: "GNQ", 232: "ERI",
    233: "EST", 231: "ETH", 238: "FLK", 2380: "FJI", 246: "FIN", 250: "FRA",
    266: "GAB", 270: "GMB", 268: "GEO", 276: "DEU", 288: "GHA", 300: "GRC",
    304: "GRL", 320: "GTM", 324: "GIN", 624: "GNB", 328: "GUY", 332: "HTI",
    340: "HND", 348: "HUN", 352: "ISL", 356: "IND", 360: "IDN", 364: "IRN",
    368: "IRQ", 372: "IRL", 376: "ISR", 380: "ITA", 388: "JAM", 392: "JPN",
    400: "JOR", 398: "KAZ", 404: "KEN", 408: "PRK", 410: "KOR", 414: "KWT",
    417: "KGZ", 418: "LAO", 428: "LVA", 422: "LBN", 426: "LSO", 430: "LBR",
    434: "LBY", 440: "LTU", 442: "LUX", 807: "MKD", 450: "MDG", 454: "MWI",
    458: "MYS", 466: "MLI", 478: "MRT", 484: "MEX", 498: "MDA", 496: "MNG",
    499: "MNE", 504: "MAR", 508: "MOZ", 104: "MMR", 516: "NAM", 524: "NPL",
    528: "NLD", 554: "NZL", 558: "NIC", 562: "NER", 566: "NGA", 578: "NOR",
    512: "OMN", 586: "PAK", 591: "PAN", 598: "PNG", 600: "PRY", 604: "PER",
    608: "PHL", 616: "POL", 620: "PRT", 634: "QAT", 642: "ROU", 643: "RUS",
    646: "RWA", 682: "SAU", 686: "SEN", 688: "SRB", 694: "SLE", 703: "SVK",
    705: "SVN", 90: "SLB", 706: "SOM", 710: "ZAF", 728: "SSD", 724: "ESP",
    144: "LKA", 729: "SDN", 740: "SUR", 748: "SWZ", 752: "SWE", 756: "CHE",
    760: "SYR", 158: "TWN", 762: "TJK", 834: "TZA", 764: "THA", 626: "TLS",
    768: "TGO", 780: "TTO", 788: "TUN", 792: "TUR", 795: "TKM", 800: "UGA",
    804: "UKR", 784: "ARE", 826: "GBR", 840: "USA", 858: "URY", 860: "UZB",
    548: "VUT", 862: "VEN", 704: "VNM", 887: "YEM", 894: "ZMB", 716: "ZWE",
}

# alpha-3 -> flagcdn alpha-2 (only countries we ship flags for)
ALPHA3_TO_ALPHA2 = {
    "PAK": "pk", "SAU": "sa", "TUR": "tr", "USA": "us", "IND": "in",
    "CHN": "cn", "GBR": "gb", "ARE": "ae", "QAT": "qa", "KWT": "kw",
    "MYS": "my", "IDN": "id", "BGD": "bd", "PHL": "ph", "EGY": "eg",
    "DEU": "de", "FRA": "fr",
}


def _decode_arc(arc, sx, sy, tx, ty):
    """Delta-decode one quantized arc -> [(lon, lat), ...]."""
    pts = []
    x = y = 0
    for dx, dy in arc:
        x += dx
        y += dy
        pts.append([x * sx + tx, y * sy + ty])
    return pts


def _decode_topo(topo):
    """TopoJSON -> {numeric_id: [polygon, ...]} (polygon = [rings])."""
    transform = topo.get("transform") or {}
    sx, sy = transform.get("scale", [1, 1])
    tx, ty = transform.get("translate", [0, 0])
    raw_arcs = topo.get("arcs", [])
    arcs = [_decode_arc(a, sx, sy, tx, ty) for a in raw_arcs]

    def get_arc(i):
        if i >= 0:
            return arcs[i]
        return list(reversed(arcs[~i]))

    def stitch(idxs):
        ring = []
        for k, i in enumerate(idxs):
            pts = get_arc(i)
            ring.extend(pts if k == 0 else pts[1:])  # shared endpoints
        return ring

    out = {}
    geoms = (topo.get("objects", {}).get("countries", {})
             .get("geometries", []))
    for g in geoms:
        try:
            nid = int(str(g.get("id", "")).strip())
        except (ValueError, TypeError):
            continue
        if nid < 0 or nid not in NUMERIC_TO_ALPHA3:
            continue
        t = g.get("type")
        a = g.get("arcs", [])
        if t == "Polygon":
            polys = [[stitch(ring) for ring in a]]
        elif t == "MultiPolygon":
            polys = [[stitch(ring) for ring in poly] for poly in a]
        else:
            continue
        out[nid] = [p for p in polys if p and p[0]]
    return out


def build_library():
    """Download TopoJSON, decode, save countries.json, fetch flag PNGs."""
    os.makedirs(FLAGS_DIR, exist_ok=True)
    r = requests.get(TOPO_URL, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    decoded = _decode_topo(r.json())
    data = {}
    for nid, polys in decoded.items():
        alpha3 = NUMERIC_TO_ALPHA3[nid]
        data[alpha3] = polys
    with open(COUNTRIES_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f)
    # flags
    got, missing = [], []
    for alpha3, a2 in sorted(ALPHA3_TO_ALPHA2.items()):
        dest = os.path.join(FLAGS_DIR, alpha3.lower() + ".png")
        try:
            fr = requests.get(FLAG_URL.format(a2),
                              headers={"User-Agent": UA}, timeout=30)
            body = fr.content
            # simple stripe flags compress to a few hundred bytes —
            # validate by PNG magic, not size
            if (fr.status_code == 200 and len(body) > 100
                    and body[:8] == b"\x89PNG\r\n\x1a\n"):
                with open(dest, "wb") as f:
                    f.write(body)
                got.append(alpha3)
            else:
                missing.append(alpha3)
        except Exception:
            missing.append(alpha3)
    return {"countries": sorted(data.keys()), "flags": got,
            "missing_flags": missing}


def load_countries():
    """Return the full {ALPHA3: [polygons]} dict from local JSON."""
    with open(COUNTRIES_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def polygons(iso3):
    """List of polygons for an alpha-3 code, or [] if unknown.

    Also tolerates the older bbox-placeholder schema
    {ALPHA3: {"polys": [...]}} by returning its "polys" list.
    """
    try:
        v = load_countries().get(iso3.upper(), [])
        if isinstance(v, dict):
            return v.get("polys", [])
        return v
    except (OSError, ValueError):
        return []


def flag_path(iso3):
    """Local PNG path for a country's flag, or None if missing."""
    p = os.path.join(FLAGS_DIR, iso3.lower() + ".png")
    return p if os.path.isfile(p) else None


def _outer_rings(iso3):
    polys = polygons(iso3)
    return [p[0] for p in polys if p and p[0]] or [[]]


def bbox(iso3):
    """(min_lon, min_lat, max_lon, max_lat) or None."""
    xs, ys = [], []
    for ring in _outer_rings(iso3):
        for lon, lat in ring:
            xs.append(lon)
            ys.append(lat)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def centroid(iso3):
    """(lon, lat) centroid of the largest outer ring, or None."""
    rings = [r for r in _outer_rings(iso3) if r]
    if not rings:
        return None
    ring = max(rings, key=len)
    n = len(ring)
    return (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)
