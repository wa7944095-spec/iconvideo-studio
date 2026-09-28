"""Unsplash photo search/download.

Key: UNSPLASH_ACCESS_KEY from ~/workspace/video-assets/.env
(parsed manually, never printed).
"""

import os

import requests

ENV_PATH = os.path.expanduser("~/workspace/video-assets/.env")
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


def search_photos(query, per_page=3):
    """Return [{id, url, alt}] from Unsplash photo search."""
    key = _load_env().get("UNSPLASH_ACCESS_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            headers={"Authorization": "Client-ID " + key},
            params={"query": query, "per_page": per_page},
            timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        out = []
        for p in r.json().get("results", [])[:per_page]:
            urls = p.get("urls", {}) or {}
            url = urls.get("regular") or urls.get("small") or urls.get("raw")
            if url:
                out.append({"id": p.get("id", ""),
                            "url": url,
                            "alt": p.get("alt_description") or ""})
        return out
    except Exception:
        return []


def download_photo(url, dest):
    """Download a photo to dest. Returns True on success."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        r = requests.get(url, timeout=60)
        if r.status_code == 200 and len(r.content) > 5000:
            with open(dest, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass
    return False
