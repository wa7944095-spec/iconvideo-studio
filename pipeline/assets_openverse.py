"""Openverse image search/download (no API key needed).

Openverse is CC-licensed media search by WordPress. Anonymous use is
rate-limited, so keep queries small and cache results.
"""

import os

import requests

CACHE_DIR = os.path.expanduser("~/workspace/iconvideo/assets/cache")
TIMEOUT = 25
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def search_images(query, page_size=3):
    """Return [{url, title}] from Openverse image search."""
    try:
        r = requests.get(
            "https://api.openverse.org/v1/images/",
            headers={"User-Agent": UA},
            params={"q": query, "page_size": page_size},
            timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        out = []
        for h in r.json().get("results", [])[:page_size]:
            url = h.get("url") or ""
            if url:
                out.append({"url": url, "title": h.get("title") or ""})
        return out
    except Exception:
        return []


def download_image(url, dest):
    """Download an image to dest. Returns True on success."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
        if r.status_code == 200 and len(r.content) > 5000:
            with open(dest, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass
    return False
