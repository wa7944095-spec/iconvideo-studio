"""Step 5 — Audio: voice-over + Gemini-directed mood music + SFX + smart ducking.

Gemini narration parh kar mood/music direction aur SFX placements deta hai
(key/mode/bpm/energy/brightness + kaunsa effect kab). Asal sound numpy se
synthesize hoti hai (Gemini audio file nahi bana sakta — wo direction deta hai,
tool sound banata hai). Gemini na ho to generic fallback.
"""

import json
import os
import subprocess
import wave

import numpy as np

SR = 44100
SFX_KINDS = ("whoosh", "pop", "riser", "impact", "chime", "sparkle")


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-1500:]}")
    return r


def _write_wav(path, samples, sr=SR):
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _norm(x, peak=0.7):
    m = np.max(np.abs(x))
    return x / m * peak if m > 0 else x


# ------------------------------------------------------------------ music

_NOTES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _note_freq(key, octave):
    semis = _NOTES.get(str(key).upper()[:1], 9)
    midi = 12 * (octave + 1) + semis
    return 440.0 * 2 ** ((midi - 69) / 12)


def make_mood_music(duration, spec, out_path):
    """spec: {key, mode, bpm, energy, brightness} — numpy pad, phir aac."""
    key = str(spec.get("key", "A"))
    minor = str(spec.get("mode", "minor")).lower() == "minor"
    bpm = float(spec.get("bpm", 80) or 80)
    energy = min(1.0, max(0.0, float(spec.get("energy", 0.35) or 0)))
    bright = min(1.0, max(0.0, float(spec.get("brightness", 0.35) or 0)))

    n = max(1, int(duration * SR))
    pad = np.zeros(n, dtype=np.float32)
    root = _note_freq(key, 2)
    # chord progression: minor i-VI-III-VII, major I-V-vi-IV
    prog = [(0, True), (8, False), (3, False), (10, False)] if minor else \
           [(0, False), (7, False), (9, True), (5, False)]
    seg = duration / len(prog)
    fade = min(1.5, seg / 2)

    for k, (off, is_min) in enumerate(prog):
        t0, t1 = k * seg, min((k + 1) * seg, duration)
        i0 = int(max(0.0, t0 - fade) * SR)
        i1 = int(min(duration, t1 + fade) * SR)
        if i1 <= i0:
            continue
        tt = np.arange(i0, i1, dtype=np.float32) / SR
        base = root * 2 ** (off / 12)
        third = 3 if is_min else 4
        tones = [(0, 0.30), (third, 0.20), (7, 0.22), (12, 0.12),
                 (19, 0.07 * bright), (24, 0.05 * bright)]
        chord = np.zeros(i1 - i0, dtype=np.float32)
        for st, amp in tones:
            f = base * 2 ** (st / 12)
            chord += np.float32(amp) * np.sin(2 * np.pi * f * tt)
        g = np.clip((tt - (t0 - fade)) / (2 * fade), 0, 1)
        g = g * g * (3 - 2 * g)
        g2 = np.clip(((t1 + fade) - tt) / (2 * fade), 0, 1)
        g2 = g2 * g2 * (3 - 2 * g2)
        pad[i0:i1] += chord * np.minimum(g, g2)

    # bpm pulse (tremolo), energy se depth
    depth = 0.10 + 0.35 * energy
    tt_all = np.arange(n, dtype=np.float32) / SR
    pad *= 1.0 - depth * 0.5 * (1 + np.sin(2 * np.pi * (bpm / 60) * tt_all
                                           - np.pi / 2))
    pad = np.tanh(pad * 1.2).astype(np.float32)
    peak = np.max(np.abs(pad))
    if peak > 0:
        pad = pad / peak * 0.42
    fi = int(min(2.0, duration / 4) * SR)
    if fi > 0:
        pad[:fi] *= np.linspace(0, 1, fi, dtype=np.float32)
        pad[-fi:] *= np.linspace(1, 0, fi, dtype=np.float32)

    wav = out_path + ".tmp.wav"
    _write_wav(wav, pad)
    _run(["ffmpeg", "-y", "-i", wav, "-af", "aformat=channel_layouts=stereo",
          "-c:a", "aac", "-b:a", "128k", out_path])
    os.remove(wav)
    return out_path


# ------------------------------------------------------------------ SFX

def _sfx_whoosh():
    d, n = 0.7, int(0.7 * SR)
    t = np.arange(n) / SR
    rng = np.random.RandomState(7)
    sweep = np.sin(2 * np.pi * (250 + 1400 * t / d) * t)
    env = np.sin(np.pi * t / d) ** 2
    return _norm((0.6 * sweep + 0.4 * rng.randn(n)) * env)


def _sfx_pop():
    d, n = 0.25, int(0.25 * SR)
    t = np.arange(n) / SR
    return _norm(np.sin(2 * np.pi * (600 + 1600 * t) * t) * np.exp(-t * 14),
                 0.5)


def _sfx_riser():
    d, n = 1.2, int(1.2 * SR)
    t = np.arange(n) / SR
    rng = np.random.RandomState(11)
    sweep = np.sin(2 * np.pi * (180 + 2000 * (t / d) ** 1.5) * t)
    env = (t / d) ** 2
    return _norm((0.7 * sweep + 0.3 * rng.randn(n)) * env)


def _sfx_impact():
    d, n = 0.8, int(0.8 * SR)
    t = np.arange(n) / SR
    rng = np.random.RandomState(13)
    thump = np.sin(2 * np.pi * 55 * t) * np.exp(-t * 7)
    click = rng.randn(n) * np.exp(-t * 40) * 0.4
    return _norm(thump + click, 0.8)


def _sfx_chime():
    d, n = 1.2, int(1.2 * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for f, a in ((880, 0.5), (1174.7, 0.3), (1568, 0.2)):
        x += a * np.sin(2 * np.pi * f * t) * np.exp(-t * 4)
    return _norm(x, 0.55)


def _sfx_sparkle():
    d, n = 1.0, int(1.0 * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for k, f in enumerate((1568, 2093, 2637, 3136)):
        t0 = k * 0.12
        m = t >= t0
        x[m] += 0.4 * np.sin(2 * np.pi * f * (t[m] - t0)) * np.exp(-(t[m] - t0) * 9)
    return _norm(x, 0.5)


_SFX_MAKERS = {"whoosh": _sfx_whoosh, "pop": _sfx_pop, "riser": _sfx_riser,
               "impact": _sfx_impact, "chime": _sfx_chime,
               "sparkle": _sfx_sparkle}


def _sfx_file(kind, workdir):
    path = os.path.join(workdir, f"sfx_{kind}.wav")
    if not os.path.isfile(path):
        _write_wav(path, _SFX_MAKERS[kind]())
    return path


def build_sfx_bed(events, out_path, duration):
    """events: [(time, kind)] — kind in SFX_KINDS."""
    workdir = os.path.dirname(out_path)
    ev = [(t, k) for t, k in events if k in _SFX_MAKERS]
    if not ev:
        return make_silence(duration, out_path)
    cmd = ["ffmpeg", "-y"]
    for _, kind in ev:
        cmd += ["-i", _sfx_file(kind, workdir)]
    parts = []
    for i, (tt, _) in enumerate(ev):
        ms = int(max(0.0, tt - 0.2) * 1000)
        parts.append(f"[{i}:a]adelay={ms}|{ms}[s{i}]")
    labels = "".join(f"[s{i}]" for i in range(len(ev)))
    parts.append(f"{labels}amix=inputs={len(ev)}:duration=longest:"
                 f"normalize=0[sfx]")
    cmd += ["-filter_complex", ";".join(parts),
            "-map", "[sfx]", "-t", f"{duration:.2f}",
            "-c:a", "aac", out_path]
    _run(cmd)
    return out_path


# ------------------------------------------------------------------ misc

def make_silence(duration, out_path):
    _run(["ffmpeg", "-y", "-f", "lavfi",
          "-i", f"anullsrc=r=44100:cl=stereo:d={duration:.2f}",
          "-c:a", "aac", out_path])
    return out_path


def convert_audio(src, out_path, duration):
    _run(["ffmpeg", "-y", "-i", src,
          "-ar", "44100", "-ac", "2", "-t", f"{duration:.2f}",
          "-c:a", "aac", "-b:a", "128k", out_path])
    return out_path


def mix_final(video_silent, voice_path, music_path, sfx_bed, out_path,
              duration, music_vol=0.22, sfx_vol=0.4):
    fc = (
        f"[2:a]volume={music_vol}[mus];"
        f"[3:a]volume={sfx_vol}[sfx];"
        f"[mus][1:a]sidechaincompress=threshold=0.03:ratio=8:"
        f"attack=20:release=400[duck];"
        f"[1:a][duck][sfx]amix=inputs=3:duration=first:normalize=0[aout]"
    )
    _run(["ffmpeg", "-y",
          "-i", video_silent,
          "-i", voice_path,
          "-stream_loop", "-1", "-i", music_path,
          "-i", sfx_bed,
          "-filter_complex", fc,
          "-map", "0:v", "-map", "[aout]",
          "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
          "-t", f"{duration:.2f}",
          "-movflags", "+faststart", out_path])
    return out_path


# ------------------------------------------------------- Gemini sound design

_AUDIO_PROMPT = """You are a sound designer for a vertical (9:16) explainer video. Read the narration (words with [seconds] timestamps) and design the background music direction plus sound-effect placements.

NARRATION:
{words}

AUDIO DURATION: {duration:.1f}s

Return STRICT JSON only, no markdown, no commentary:
{{"mood": "<2-3 words>",
  "music": {{"key": "A-G", "mode": "major|minor", "bpm": 60-140, "energy": 0.0-1.0, "brightness": 0.0-1.0}},
  "sfx": [{{"t": <seconds>, "kind": "<whoosh|pop|riser|impact|chime|sparkle>", "why": "<4 words>"}}]}}

RULES:
- 3-8 sfx events, t within [0, DURATION], spread across the narration.
- kind guide: whoosh = energetic transition; pop = small fact/reveal; riser = building tension before a big line; impact = dramatic/shocking moment; chime = positive/hopeful reveal; sparkle = magical/wondrous moment.
- music must match the narration mood: tense/dark story -> minor key, lower bpm; success/happy story -> major key, higher bpm and energy.
- Place each sfx exactly at (or 0.2s before) the word/moment it emphasizes.
"""


def plan_audio(words, duration, api_key=None):
    """Returns (music_spec, sfx_events). Gemini-directed; generic fallback."""
    default_spec = {"mood": "calm", "key": "A", "mode": "minor", "bpm": 80,
                    "energy": 0.35, "brightness": 0.35}
    if not api_key:
        return dict(default_spec), []
    try:
        for v in ("no_proxy", "NO_PROXY"):
            val = os.environ.get(v, "")
            if "[" in val:
                os.environ[v] = ",".join(p for p in val.split(",")
                                         if "[" not in p)
        from google import genai
        lines = "\n".join(f"[{w['start']:.2f}] {w['w']}" for w in words)
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=_AUDIO_PROMPT.format(duration=duration, words=lines),
            config={"response_mime_type": "application/json"},
        )
        data = json.loads(resp.text)
        spec = dict(default_spec)
        spec.update(data.get("music") or {})
        spec["mood"] = str(data.get("mood", "calm"))[:24]
        events = []
        for e in (data.get("sfx") or [])[:10]:
            try:
                t, kind = float(e["t"]), str(e["kind"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= t <= duration and kind in _SFX_MAKERS:
                events.append((t, kind))
        print(f"[audio] Gemini: mood={spec['mood']}, {len(events)} sfx placed")
        return spec, events
    except Exception as e:
        print(f"[audio] Gemini sound design failed ({e}) — generic music")
        return dict(default_spec), []
