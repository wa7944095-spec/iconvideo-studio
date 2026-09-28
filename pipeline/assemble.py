"""Step 4 — Audio: voice-over + ambient music + transition whoosh + smart ducking.

Voice full volume; music voice ke neeche auto-duck hoti hai (sidechain).
(VoiceCut Studio ke proven audio chain se adapted.)
"""

import os
import subprocess


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-1500:]}")
    return r


def make_ambient_music(duration, out_path):
    """Soft ambient pad — A-major drone, halka taake narration saaf rahe."""
    expr = ("0.20*sin(2*PI*110*t)+0.16*sin(2*PI*164.81*t)"
            "+0.12*sin(2*PI*220*t)+0.09*sin(2*PI*277.18*t)")
    _run(["ffmpeg", "-y", "-f", "lavfi",
          "-i", f"aevalsrc='{expr}':s=44100:d={duration:.2f}",
          "-af", "aformat=channel_layouts=stereo,tremolo=f=0.12:d=0.7,"
                 "lowpass=f=900,volume=0.55",
          "-c:a", "aac", "-b:a", "128k", out_path])
    return out_path


def make_silence(duration, out_path):
    _run(["ffmpeg", "-y", "-f", "lavfi",
          "-i", f"anullsrc=r=44100:cl=stereo:d={duration:.2f}",
          "-c:a", "aac", out_path])
    return out_path


def make_whoosh(out_path):
    """0.7s upward sweep — har scene transition par."""
    expr = "sin(2*PI*(250+1400*t/0.7)*t)*sin(PI*t/0.7)"
    _run(["ffmpeg", "-y", "-f", "lavfi",
          "-i", f"aevalsrc='{expr}':s=44100:d=0.7",
          "-af", "aformat=channel_layouts=stereo,volume=0.7",
          "-c:a", "aac", out_path])
    return out_path


def make_pop(out_path):
    """0.25s soft pop — icon appear par."""
    expr = "sin(2*PI*(600+400*t/0.25)*t)*sin(PI*t/0.25)"
    _run(["ffmpeg", "-y", "-f", "lavfi",
          "-i", f"aevalsrc='{expr}':s=44100:d=0.25",
          "-af", "aformat=channel_layouts=stereo,volume=0.35",
          "-c:a", "aac", out_path])
    return out_path


def build_sfx_bed(events, out_path, duration):
    """events: [(time, kind)] kind='whoosh'|'pop'. Har event 0.2s pehle."""
    whoosh = os.path.join(os.path.dirname(out_path), "whoosh.m4a")
    pop = os.path.join(os.path.dirname(out_path), "pop.m4a")
    make_whoosh(whoosh)
    make_pop(pop)
    if not events:
        return make_silence(duration, out_path)
    cmd = ["ffmpeg", "-y"]
    for _, kind in events:
        cmd += ["-i", whoosh if kind == "whoosh" else pop]
    parts = []
    for i, (tt, _) in enumerate(events):
        ms = int(max(0.0, tt - 0.2) * 1000)
        parts.append(f"[{i}:a]adelay={ms}|{ms}[s{i}]")
    labels = "".join(f"[s{i}]" for i in range(len(events)))
    parts.append(f"{labels}amix=inputs={len(events)}:duration=longest:"
                 f"normalize=0[sfx]")
    cmd += ["-filter_complex", ";".join(parts),
            "-map", "[sfx]", "-t", f"{duration:.2f}",
            "-c:a", "aac", out_path]
    _run(cmd)
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
