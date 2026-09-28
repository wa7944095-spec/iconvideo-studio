"""API keys load karo — precedence: env vars > iconvideo/.env > video-assets/.env > voicecut/.env.

Saari keys local files me rehti hain, kabhi chat/memory me nahi jati.
"""

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_env(path):
    d = {}
    if os.path.isfile(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k and v:
                    d[k] = v
    return d


def load_keys():
    merged = {}
    for p in (os.path.expanduser("~/workspace/voicecut/.env"),
              os.path.expanduser("~/workspace/video-assets/.env"),
              os.path.join(_ROOT, ".env")):
        merged.update(_parse_env(p))
    for k, v in os.environ.items():
        if v:
            merged[k] = v
    # Streamlit Cloud: keys Settings -> Secrets (TOML) me
    try:
        import streamlit as st
        for k, v in st.secrets.items():
            if v:
                merged[str(k)] = str(v)
    except Exception:
        pass
    return merged


def get(key, default=None):
    return load_keys().get(key, default)
