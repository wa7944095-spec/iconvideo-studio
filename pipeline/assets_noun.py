"""Noun Project icon search/download (OAuth 1.0a, 2-legged).

Keys: NOUN_PROJECT_API_KEY / NOUN_PROJECT_API_SECRET from
~/workspace/video-assets/.env (parsed manually, never printed).
"""

import base64
import hashlib
import hmac
import os
import time
import uuid
from urllib.parse import quote

import requests

ENV_PATH = os.path.expanduser("~/workspace/video-assets/.env")
CACHE_DIR = os.path.expanduser("~/workspace/iconvideo/assets/cache")
BASE_URL = "https://api.thenounproject.com"
TIMEOUT = 25


def _load_env(path=ENV_PATH):
    """Parse a KEY=VALUE file manually. Values are never printed/logged."""
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


def _oauth1_header(method, url, params, consumer_key, consumer_secret):
    """Build an OAuth 1.0a Authorization header (HMAC-SHA1, 2-legged)."""
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_version": "1.0",
    }
    all_params = dict(params)
    all_params.update(oauth)
    normalized = "&".join(
        "%s=%s" % (quote(str(k), safe="~"), quote(str(v), safe="~"))
        for k, v in sorted(all_params.items(),
                           key=lambda kv: (quote(str(kv[0]), safe="~"),
                                           quote(str(kv[1]), safe="~")))
    )
    base_string = "&".join(
        [method.upper(), quote(url, safe="~"), quote(normalized, safe="~")])
    signing_key = quote(consumer_secret, safe="~") + "&"
    sig = base64.b64encode(
        hmac.new(signing_key.encode("utf-8"),
                 base_string.encode("utf-8"),
                 hashlib.sha1).digest()).decode("utf-8")
    oauth["oauth_signature"] = sig
    return "OAuth " + ", ".join(
        '%s="%s"' % (quote(str(k), safe="~"), quote(str(v), safe="~"))
        for k, v in sorted(oauth.items()))


def search_icons(query, limit=5):
    """Return [{id, term, png_url}] for a Noun Project icon search."""
    env = _load_env()
    key = env.get("NOUN_PROJECT_API_KEY", "")
    secret = env.get("NOUN_PROJECT_API_SECRET", "")
    if not key or not secret:
        return []
    url = BASE_URL + "/v2/icon"
    params = {"query": query, "limit": str(limit)}
    headers = {"Authorization": _oauth1_header("GET", url, params, key, secret)}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        out = []
        for icon in r.json().get("icons", [])[:limit]:
            # v2 API serves PNGs as thumbnail_url
            # (e.g. https://static.thenounproject.com/png/<id>-200.png)
            png = (icon.get("thumbnail_url")
                   or icon.get("preview_url")
                   or icon.get("preview_url_200")
                   or icon.get("preview_url_84") or "")
            if png:
                out.append({"id": str(icon.get("id", "")),
                            "term": icon.get("term", ""),
                            "png_url": png})
        return out
    except Exception:
        return []


def download_icon(png_url, dest):
    """Download an icon PNG to dest. Returns True on success."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        r = requests.get(png_url, timeout=60)
        if r.status_code == 200 and len(r.content) > 1000:
            with open(dest, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass
    return False
