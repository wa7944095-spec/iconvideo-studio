"""Stock video fallback: Pexels -> Pixabay -> Coverr.

Adapted from the proven ~/workspace/voicecut/pipeline/footage.py chain
(minus YouTube, which is clip-oriented for that tool).
Keys: PEXELS_API_KEY / PIXABAY_API_KEY / COVERR_API_KEY from
~/workspace/voicecut/.env (parsed manually, never printed).
"""

import os
import subprocess

import requests

ENV_PATH = os.path.expanduser("~/workspace/voicecut/.env")
CACHE_DIR = os.path.expanduser("~/workspace/iconvideo/assets/cache")
TIMEOUT = 25


def _load_env(path=ENV_PATH):
    out = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                out[k.strip()] = v
    except OSError:
        pass
    return out


def _valid_video(dest, min_secs=2.0):
    try:
        if not os.path.isfile(dest) or os.path.getsize(dest) < 50000:
            return False
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type:format=duration",
             "-of", "default=noprint_wrappers=1", dest],
            capture_output=True, text=True, timeout=30)
        return "codec_type=video" in (p.stdout or "")
    except Exception:
        return False


def _download(url, dest):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        r = requests.get(url, timeout=120)
        if r.status_code == 200 and len(r.content) > 50000:
            with open(dest, "wb") as f:
                f.write(r.content)
            if _valid_video(dest):
                return True
            try:
                os.remove(dest)
            except OSError:
                pass
    except Exception:
        pass
    return False


def _pexels(query, api_key, dest):
    if not api_key:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": api_key},
            params={"query": query, "per_page": 5, "size": "medium"},
            timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        for v in r.json().get("videos", []):
            files = sorted(v.get("video_files", []),
                           key=lambda f: f.get("width", 0), reverse=True)
            mp4s = [f for f in files
                    if f.get("file_type") == "video/mp4"
                    and f.get("width", 0) >= 640]
            if mp4s and _download(mp4s[0]["link"], dest):
                return dest
    except Exception:
        pass
    return None


def _pixabay(query, api_key, dest):
    if not api_key:
        return None
    try:
        r = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": api_key, "q": query, "per_page": 3,
                    "safesearch": "true"},
            timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        for h in r.json().get("hits", []):
            vids = h.get("videos", {}) or {}
            for size in ("medium", "large", "small"):
                url = vids.get(size, {}).get("url")
                if url and _download(url, dest):
                    return dest
    except Exception:
        pass
    return None


def _coverr(query, api_key, dest):
    if not api_key:
        return None
    try:
        r = requests.get(
            "https://api.coverr.co/videos",
            headers={"Authorization": "Bearer " + api_key},
            params={"query": query, "urls": "true", "page_size": 5},
            timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        for h in r.json().get("hits", []):
            urls = h.get("urls") or {}
            url = urls.get("mp4_download") or urls.get("mp4")
            if url and _download(url, dest):
                return dest
    except Exception:
        pass
    return None


def fetch_video(query, dest, max_dur=10):
    """Try Pexels -> Pixabay -> Coverr. Returns local path or None."""
    env = _load_env()
    got = (_pexels(query, env.get("PEXELS_API_KEY", ""), dest)
           or _pixabay(query, env.get("PIXABAY_API_KEY", ""), dest)
           or _coverr(query, env.get("COVERR_API_KEY", ""), dest))
    return got
