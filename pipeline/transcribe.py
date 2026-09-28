"""Step 1 — Voice-over transcribe karo WORD-level timestamps ke saath.

faster-whisper (local, free) har lafz ka start/end deta hai — isi par
kinetic text aur scene timing khadi hai. Model voicecut wala bundled
model reuse hota hai (dobara download nahi).
"""

import os

from faster_whisper import WhisperModel

_model = None
_VOICECUT_MODEL = os.path.expanduser("~/workspace/voicecut/models/base")


def _get_model():
    global _model
    if _model is None:
        mid = (_VOICECUT_MODEL if os.path.isfile(
            os.path.join(_VOICECUT_MODEL, "model.bin")) else "base")
        try:
            _model = WhisperModel(mid, device="cpu", compute_type="int8")
        except Exception:
            os.environ["HF_HUB_OFFLINE"] = "1"
            _model = WhisperModel(mid, device="cpu", compute_type="int8")
    return _model


def transcribe_words(audio_path):
    """Returns {duration, language, words:[{w,start,end}], segments:[...]}"""
    model = _get_model()
    segments, info = model.transcribe(audio_path, beam_size=5,
                                      word_timestamps=True)
    words, segs = [], []
    for s in segments:
        t = (s.text or "").strip()
        if t:
            segs.append({"start": s.start, "end": s.end, "text": t})
        for w in (s.words or []):
            wt = (w.word or "").strip()
            if wt:
                words.append({"w": wt, "start": w.start, "end": w.end})
    if not words:
        raise ValueError("Audio mein koi speech nahi mili — file check karo.")
    return {
        "duration": float(info.duration),
        "language": info.language,
        "words": words,
        "segments": segs,
    }
