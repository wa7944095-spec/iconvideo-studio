"""IconVideo pipeline — voice upload -> TikTok-style map/icon explainer video.

Usage:
  python run_pipeline.py --voice narration.mp3 --out final.mp4 [--workdir work/]

Steps: transcribe (word timestamps) -> Gemini/heuristic scene plan ->
       asset fetch (Noun Project / Unsplash / Openverse / local maps /
                    stock video) ->
       render (1080x1920) -> audio mix (voice + music + whoosh, ducking).
"""

import argparse
import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from pipeline import config, transcribe, planner, assemble  # noqa: E402

CACHE = os.path.join(_ROOT, "assets", "cache")


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def resolve_icon_assets(scenes):
    """Har icon item ke liye Noun Project se PNG lao; fail ho to plain scene."""
    try:
        from pipeline import assets_noun
    except Exception as e:
        print(f"[assets] assets_noun import failed ({e}) — icons skip")
        assets_noun = None

    for sc in scenes:
        bg = sc.get("bg") or {}
        if bg.get("type") != "icons":
            continue
        ok_items = []
        for item in bg.get("items", []):
            q = item.get("query") or "idea"
            dest = os.path.join(CACHE, "icons", slugify(q) + ".png")
            got = None
            if assets_noun and not os.path.isfile(dest):
                try:
                    res = assets_noun.search_icons(q, limit=4)
                    if res:
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        got = assets_noun.download_icon(
                            res[0]["png_url"], dest)
                except Exception as e:
                    print(f"[assets] noun '{q}' failed: {e}")
            elif os.path.isfile(dest):
                got = dest
            if got:
                item["path"] = got
                ok_items.append(item)
        if ok_items:
            bg["items"] = ok_items
        else:
            print(f"[assets] no icons for scene @{sc['start']:.1f}s — plain")
            sc["bg"] = {"type": "plain"}


def _valid_image(path):
    """PIL se verify karo ke ye asli image hai."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False


def resolve_photo_assets(scenes):
    """Har photo scene ke liye Unsplash -> Openverse se JPG lao."""
    try:
        from pipeline import assets_unsplash, assets_openverse
    except Exception as e:
        print(f"[assets] photo modules import failed ({e}) — photos skip")
        assets_unsplash = assets_openverse = None

    for sc in scenes:
        bg = sc.get("bg") or {}
        if bg.get("type") != "photo":
            continue
        q = bg.get("query") or "city"
        dest = os.path.join(CACHE, "photos", slugify(q) + ".jpg")
        got = None
        if os.path.isfile(dest) and _valid_image(dest):
            got = dest
        if not got and assets_unsplash:
            try:
                res = assets_unsplash.search_photos(q, per_page=3)
                if res:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    if assets_unsplash.download_photo(res[0]["url"], dest) \
                            and _valid_image(dest):
                        got = dest
                    else:
                        try:
                            os.remove(dest)
                        except OSError:
                            pass
            except Exception as e:
                print(f"[assets] unsplash '{q}' failed: {e}")
        if not got and assets_openverse:
            try:
                res = assets_openverse.search_images(q, page_size=3)
                if res:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    if assets_openverse.download_image(res[0]["url"], dest) \
                            and _valid_image(dest):
                        got = dest
                    else:
                        try:
                            os.remove(dest)
                        except OSError:
                            pass
            except Exception as e:
                print(f"[assets] openverse '{q}' failed: {e}")
        if got:
            bg["path"] = got
        else:
            print(f"[assets] no photo for '{q}' @{sc['start']:.1f}s — plain")
            sc["bg"] = {"type": "plain"}


def resolve_video_assets(scenes):
    """Har video scene ke liye stock clip lao (Pexels->Pixabay->Coverr)."""
    try:
        from pipeline import assets_stock
    except Exception as e:
        print(f"[assets] assets_stock import failed ({e}) — videos skip")
        assets_stock = None

    for sc in scenes:
        bg = sc.get("bg") or {}
        if bg.get("type") != "video":
            continue
        q = bg.get("query") or "city"
        dest = os.path.join(CACHE, "videos", slugify(q) + ".mp4")
        got = None
        if os.path.isfile(dest):
            got = dest
        if not got and assets_stock:
            try:
                got = assets_stock.fetch_video(q, dest)
            except Exception as e:
                print(f"[assets] stock video '{q}' failed: {e}")
        if got:
            bg["path"] = got
        else:
            print(f"[assets] no video for '{q}' @{sc['start']:.1f}s — plain")
            sc["bg"] = {"type": "plain"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", default=os.path.join(_ROOT, "work"))
    ap.add_argument("--no-gemini", action="store_true",
                    help="Gemini skip, heuristic planner")
    ap.add_argument("--music-vol", type=float, default=0.22)
    ap.add_argument("--sfx-vol", type=float, default=0.4)
    a = ap.parse_args()

    os.makedirs(a.workdir, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    keys = config.load_keys()

    print("[1/5] transcribing…")
    tr = transcribe.transcribe_words(a.voice)
    duration = tr["duration"]
    print(f"      {len(tr['words'])} words, {duration:.1f}s, lang={tr['language']}")

    print("[2/5] planning scenes…")
    gkey = None if a.no_gemini else keys.get("GEMINI_API_KEY")
    plan = planner.plan(tr["words"], duration, api_key=gkey)
    scenes = plan["scenes"]
    print(f"      {len(scenes)} scenes " +
          ("(Gemini)" if gkey else "(heuristic)"))
    with open(os.path.join(a.workdir, "scenes.json"), "w") as f:
        json.dump(plan, f, indent=1)

    print("[3/5] fetching icon/photo/video assets…")
    resolve_icon_assets(scenes)
    resolve_photo_assets(scenes)
    resolve_video_assets(scenes)

    print("[4/5] rendering video…")
    from pipeline import render
    silent = os.path.join(a.workdir, "silent.mp4")
    render.render_scenes(scenes, silent, fps=24)

    print("[5/5] mixing audio…")
    events = []
    for sc in scenes:
        if sc["start"] > 0.15:
            events.append((sc["start"], "whoosh"))
        bg = sc.get("bg") or {}
        if bg.get("type") == "icons":
            for k in range(len(bg.get("items", []))):
                events.append((sc["start"] + 0.3 + 0.25 * k, "pop"))
    voice_wav = os.path.join(a.workdir, "voice.m4a")
    music = os.path.join(a.workdir, "music.m4a")
    sfx = os.path.join(a.workdir, "sfx.m4a")
    assemble.convert_audio(a.voice, voice_wav, duration)
    assemble.make_ambient_music(duration, music)
    assemble.build_sfx_bed(events, sfx, duration)
    assemble.mix_final(silent, voice_wav, music, sfx, a.out, duration,
                       music_vol=a.music_vol, sfx_vol=a.sfx_vol)

    with open(os.path.join(a.workdir, "meta.json"), "w") as f:
        json.dump({"video_silent": silent, "voice_src": voice_wav,
                   "music_src": music, "sfx_bed": sfx,
                   "duration": duration, "final": a.out}, f, indent=1)
    print(f"DONE -> {a.out}")


if __name__ == "__main__":
    main()
