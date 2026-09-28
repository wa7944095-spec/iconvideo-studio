"""Step 2 — Scene planner: transcript (word timestamps) -> scene list.
Scene schema (renderer isi par chalta hai):
{
  "start": 0.0, "end": 2.5,
  "bg": {"type": "map", "focus": ["PAK"],
          "highlight": {"PAK": "#35a05a"}, "labels": {"PAK": "Pakistan"},
          "flags": true, "zoom": "in"}
      | {"type": "icons", "items": [{"query": "construction worker",
          "label": "Worker", "callout": null}, ...]}
      | {"type": "photo", "query": "city skyline", "kenburns": "in"}
      | {"type": "video", "query": "construction site"}
      | {"type": "plain"},
  "text": [{"w": "Pakistan", "t": 0.2}, ...]   # t = absolute seconds
}

Gemini API key ho to smart planning, warna local heuristic fallback.
"""

import json
import os
import re

# phrase (lowercase) -> (ISO3, display label, highlight color)
COUNTRIES = {
    "pakistan": ("PAK", "Pakistan", "#35a05a"),
    "saudi arabia": ("SAU", "Saudi Arabia", "#35a05a"),
    "saudi": ("SAU", "Saudi Arabia", "#35a05a"),
    "turkey": ("TUR", "Turkey", "#d64545"),
    "turkiye": ("TUR", "Turkey", "#d64545"),
    "india": ("IND", "India", "#e8912d"),
    "china": ("CHN", "China", "#d64545"),
    "america": ("USA", "America", "#3b7dd8"),
    "united states": ("USA", "United States", "#3b7dd8"),
    "britain": ("GBR", "Britain", "#3b7dd8"),
    "uk": ("GBR", "UK", "#3b7dd8"),
    "england": ("GBR", "England", "#3b7dd8"),
    "uae": ("ARE", "UAE", "#35a05a"),
    "dubai": ("ARE", "Dubai", "#35a05a"),
    "qatar": ("QAT", "Qatar", "#7a4fd0"),
    "kuwait": ("KWT", "Kuwait", "#35a05a"),
    "germany": ("DEU", "Germany", "#e8c832"),
    "france": ("FRA", "France", "#3b7dd8"),
    "egypt": ("EGY", "Egypt", "#e8c832"),
    "bangladesh": ("BGD", "Bangladesh", "#35a05a"),
    "malaysia": ("MYS", "Malaysia", "#e8912d"),
    "indonesia": ("IDN", "Indonesia", "#d64545"),
    "philippines": ("PHL", "Philippines", "#3b7dd8"),
}

STOPWORDS = set("""
a an the and or but of to in on at for with from by as is are was were be been
being it its this that these those i you he she we they them his her our your
their me him us there here so such no not only just very can will would could
should do does did have has had having what when where who whom which how why
all any some more most other into over after before between out up down off
again once than too also s t re ll ve d m
""".split())

NUMBER_WORDS = {"thousand": "Thousands", "thousands": "Thousands",
                "million": "Millions", "millions": "Millions",
                "billion": "Billions", "billions": "Billions",
                "hundred": "Hundreds", "hundreds": "Hundreds"}

MAX_SCENE = 4.0
MIN_SCENE = 1.2


def _clean(w):
    return re.sub(r"[^a-z']", "", w.lower())


def plan(words, duration, api_key=None):
    """words: [{w,start,end}]. Returns {duration, scenes:[...]}."""
    if api_key:
        try:
            return plan_gemini(words, duration, api_key)
        except Exception as e:
            print(f"[planner] Gemini failed ({e}), heuristic fallback")
    return plan_heuristic(words, duration)


# ---------------- Gemini ----------------

_GEMINI_PROMPT = """You plan scenes for a vertical (9:16) explainer video in the style of viral map/icon TikToks: flat vector icons, animated country maps with flags, and kinetic word-by-word text synced to narration.

INPUT: narration words with timestamps, one per line as: [seconds] word
AUDIO DURATION: {duration:.1f}s

OUTPUT: strict JSON only, no markdown, no commentary:
{{"scenes": [{{"start": 0.0, "end": 2.5,
  "bg": {{"type": "map", "focus": ["PAK"], "zoom": "in"}}
       | {{"type": "icons", "items": [{{"query": "construction worker", "label": "Worker", "callout": null}}]}}
       | {{"type": "photo", "query": "city skyline", "kenburns": "in"}}
       | {{"type": "video", "query": "construction site"}}
       | {{"type": "plain"}},
  "text": [{{"w": "Pakistan", "t": 0.2}}]}}]}}

RULES:
- Scenes must tile [0, DURATION] contiguously, no gaps/overlaps. Scene length 1.2-4.0s.
- "text" = EXACT words spoken in [start,end], with their timestamps (absolute seconds).
- Use "map" bg whenever a country is named. focus = ISO3 codes. Known ISO3: PAK Pakistan, SAU Saudi Arabia, TUR Turkey, IND India, CHN China, USA United States, GBR United Kingdom, ARE UAE, QAT Qatar, KWT Kuwait, DEU Germany, FRA France, EGY Egypt, BGD Bangladesh, MYS Malaysia, IDN Indonesia, PHL Philippines.
- zoom: "in" on first country scene, "pan" when the country changes, "out" rarely.
- Use "icons" bg for concepts/people/objects. query = short icon search term ("construction worker", "calendar", "factory", "money", "airplane"). label = 1-2 word caption. callout = short pill text above an icon when narration mentions a quantity (e.g. "Thousands").
- Use "photo" bg for generic visual/B-roll moments needing a real-world image (city skyline, factory floor, crowd, desert). query = short English photo search phrase. kenburns = "in" or "out".
- Use "video" bg SPARINGLY (max 1-2 per video) for action moments that need real motion (construction site, traffic, waves). query = short English video search phrase.
- Keep every scene visually simple: max 3 icons, max 2 countries in focus.
- Prefer map scenes for geography/economy topics, icons for people/actions/objects, photo for atmosphere, video for action.
- "plain" is the last resort when nothing else fits.

WORDS:
{words}
"""


def plan_gemini(words, duration, api_key):
    # httpx bracketed IPv6 no_proxy entries par crash karta hai — sanitize karo
    for v in ("no_proxy", "NO_PROXY"):
        val = os.environ.get(v, "")
        if "[" in val:
            os.environ[v] = ",".join(p for p in val.split(",") if "[" not in p)
    from google import genai
    lines = "\n".join(f"[{w['start']:.2f}] {w['w']}" for w in words)
    prompt = _GEMINI_PROMPT.format(duration=duration, words=lines)
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    data = json.loads(resp.text)
    scenes = _normalize(data["scenes"], words, duration)
    return {"duration": duration, "scenes": scenes}


def _normalize(scenes, words, duration):
    """Clamp/retile scenes so they cover [0, duration] cleanly."""
    out = []
    cursor = 0.0
    for sc in scenes:
        start = max(cursor, float(sc.get("start", cursor)))
        end = float(sc.get("end", start + 2.0))
        end = min(max(end, start + MIN_SCENE), duration)
        if end <= start:
            continue
        txt = [w for w in words if start - 1e-6 <= w["start"] < end]
        bg = sc.get("bg") or {"type": "plain"}
        out.append({"start": start, "end": end, "bg": bg,
                    "text": [{"w": w["w"], "t": w["start"]} for w in txt]})
        cursor = end
        if cursor >= duration - 1e-6:
            break
    if out:
        out[-1]["end"] = duration
    elif duration > 0:
        out = [{"start": 0.0, "end": duration, "bg": {"type": "plain"},
                "text": [{"w": w["w"], "t": w["start"]} for w in words]}]
    return out


# ---------------- Heuristic fallback ----------------

def _find_country(text_low):
    for phrase, info in COUNTRIES.items():
        if re.search(r"\b" + re.escape(phrase) + r"\b", text_low):
            return info
    return None


def _content_words(words):
    seen, out = set(), []
    for w in words:
        c = _clean(w["w"])
        if len(c) > 3 and c not in STOPWORDS and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def plan_heuristic(words, duration):
    scenes = []
    i, n = 0, len(words)
    prev_map = None
    while i < n:
        w0 = words[i]
        # look ahead for a country mention within ~3.5s
        j = i
        found = None
        window_text = []
        while j < n and words[j]["start"] - w0["start"] < 3.5:
            window_text.append(words[j]["w"])
            j += 1
        found = _find_country(" ".join(window_text).lower())

        if found:
            iso3, label, color = found
            # extend scene a bit past the mention
            k = j
            end = words[j - 1]["end"] + 0.6 if j > i else w0["end"] + 1.0
            while k < n and words[k]["start"] < end and k - i < 14:
                k += 1
            end = min(words[k - 1]["end"] + 0.4, duration)
            zoom = "pan" if (prev_map and prev_map != iso3) else "in"
            bg = {"type": "map", "focus": [iso3],
                  "highlight": {iso3: color}, "labels": {iso3: label},
                  "flags": True, "zoom": zoom}
            prev_map = iso3
        else:
            # icon scene ~2.5s
            k = i
            while k < n and words[k]["start"] - w0["start"] < 2.5:
                k += 1
            k = max(k, i + 1)
            chunk = words[i:k]
            end = min(chunk[-1]["end"] + 0.4, duration)
            cws = _content_words(chunk)[:3]
            items = []
            callout = None
            for cw in [w["w"] for w in chunk]:
                cl = _clean(cw)
                if cl in NUMBER_WORDS:
                    callout = NUMBER_WORDS[cl]
                    break
            for cw in cws or ["idea"]:
                items.append({"query": cw.replace("_", " "),
                              "label": cw.replace("_", " ").title(),
                              "callout": callout})
                callout = None  # sirf pehle icon par
            bg = {"type": "icons", "items": items[:3]}
            prev_map = None

        if end - w0["start"] < MIN_SCENE:
            end = min(w0["start"] + MIN_SCENE, duration)
        txt = [{"w": w["w"], "t": w["start"]} for w in words[i:k]]
        scenes.append({"start": w0["start"], "end": end, "bg": bg, "text": txt})
        i = k
        if end >= duration - 1e-6:
            break

    # retile: no gaps
    for idx in range(1, len(scenes)):
        scenes[idx]["start"] = scenes[idx - 1]["end"]
    if scenes:
        scenes[-1]["end"] = duration
    return {"duration": duration, "scenes": scenes}
