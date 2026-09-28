"""IconVideo Studio — voice upload karo, map/icon explainer video banao."""

import os
import subprocess
import sys
import tempfile
import time
import uuid

import streamlit as st

ROOT = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="IconVideo Studio", page_icon="🗺️", layout="centered")
st.title("🗺️ IconVideo Studio")
st.caption("Voice-over upload karo — tool khud map, icons aur kinetic text wali vertical video bana dega.")

with st.expander("⚙️ API keys (optional — bina keys ke bhi chalta hai)"):
    st.markdown(
        "Keys **Settings → Secrets** me TOML format me dalo (deployed app par), "
        "ya yahan session ke liye paste karo:"
    )
    gemini_key = st.text_input("Gemini API key", type="password")
    noun_key = st.text_input("Noun Project key", type="password")
    noun_secret = st.text_input("Noun Project secret", type="password")
    unsplash_key = st.text_input("Unsplash access key", type="password")

voice = st.file_uploader(
    "🎙️ Voice-over file upload karo (koi bhi audio format: MP3, WAV, M4A, OGG, FLAC, WMA…)",
)
use_gemini = st.toggle("✨ Gemini smart scenes", value=True,
                       help="Band ho to simple rule-based planner chalega.")
col1, col2 = st.columns(2)
with col1:
    music_vol = st.slider("🎵 Music volume", 0, 100, 25)
with col2:
    sfx_vol = st.slider("🔊 SFX volume", 0, 100, 70)

STEPS = ["transcribing", "planning scenes", "fetching icon assets",
         "rendering video", "mixing audio"]

if st.button("🎬 Video banao", type="primary", disabled=not voice):
    if voice is None:
        st.warning("Pehle voice file upload karo.")
        st.stop()

    job = uuid.uuid4().hex[:8]
    workdir = os.path.join(tempfile.gettempdir(), f"iconvideo_{job}")
    os.makedirs(workdir, exist_ok=True)
    voice_path = os.path.join(workdir, "voice" + os.path.splitext(voice.name)[1])
    with open(voice_path, "wb") as f:
        f.write(voice.getbuffer())

    # koi bhi format ho — check karo ke is me audio stream hai
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", voice_path],
        capture_output=True, text=True)
    if "audio" not in probe.stdout:
        st.error("Ye file audio nahi lag rahi — koi audio file (MP3/WAV/M4A/…) upload karo.")
        st.stop()
    out_path = os.path.join(workdir, "iconvideo_final.mp4")

    env = dict(os.environ)
    if gemini_key:
        env["GEMINI_API_KEY"] = gemini_key
    if noun_key:
        env["NOUN_PROJECT_API_KEY"] = noun_key
    if noun_secret:
        env["NOUN_PROJECT_API_SECRET"] = noun_secret
    if unsplash_key:
        env["UNSPLASH_ACCESS_KEY"] = unsplash_key
    cmd = [sys.executable, os.path.join(ROOT, "run_pipeline.py"),
           "--voice", voice_path, "--out", out_path,
           "--workdir", os.path.join(workdir, "work"),
           "--music-vol", str(music_vol / 100),
           "--sfx-vol", str(sfx_vol / 100)]
    if not use_gemini:
        cmd.append("--no-gemini")

    progress = st.progress(0, text="Shuru ho raha hai…")
    log_box = st.empty()
    step_idx = {"i": 0}

    def bump(line):
        for i, s in enumerate(STEPS):
            if s in line.lower():
                step_idx["i"] = max(step_idx["i"], i)
        frac = min(0.99, (step_idx["i"] + 0.5) / len(STEPS))
        progress.progress(frac, text=f"Step {step_idx['i'] + 1}/5: {STEPS[step_idx['i']]}…")

    with st.spinner("Video ban rahi hai — thoda wait karo…"):
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        logs = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                logs.append(line)
                bump(line)
                log_box.code("\n".join(logs[-12:]))
        proc.wait()

    if proc.returncode != 0 or not os.path.isfile(out_path):
        progress.progress(0, text="Fail ho gaya")
        st.error("Video nahi ban saki. Neeche log dekho:")
        log_box.code("\n".join(logs[-30:]))
        st.stop()

    progress.progress(1.0, text="Ho gaya! ✅")
    st.success("Tayyar hai Ustad! 🎉")
    st.video(out_path)
    with open(out_path, "rb") as f:
        st.download_button("⬇️ MP4 download karo", f,
                           file_name="iconvideo_final.mp4",
                           mime="video/mp4")
