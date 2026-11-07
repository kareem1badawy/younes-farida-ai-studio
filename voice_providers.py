"""مزودو الصوت العربي المجانيون. كل دالة ترجع مسار ملف wav أو ترفع خطأ."""
import asyncio, base64, os
import config
from util import log, run, duration, request_retry

def _to_wav(src, dst):
    run(["ffmpeg", "-y", "-i", src, "-ar", "44100", "-ac", "1", dst])
    # الجمل القصيرة في حوار الأطفال قد تكون أقل من ثانيتين؛ لا نرفضها لمجرد قصرها.
    # نرفض فقط الملف الفارغ أو الناتج الأقصر من ربع ثانية.
    d = duration(dst)
    if d < 0.25:
        raise RuntimeError(f"audio missing or too short ({d:.2f}s)")
    return dst

# ---------- 1) Gemini TTS ----------
def gemini_tts(text, out_dir, voice=None, style=None, tag=""):
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing")
    last = None
    for model in config.GEMINI_TTS_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": (f"Speak in Arabic with the voice of {style}, playful, clear and slightly high-pitched: " if style else "اقرأ بصوت طفولي مرح وواضح باللغة العربية: ") + text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice or config.GEMINI_VOICE}}},
            },
        }
        try:
            r = request_retry("POST", url, json=body, timeout=120,
                              headers={"x-goog-api-key": config.GEMINI_API_KEY})
            if r.status_code != 200:
                raise RuntimeError(f"{model} HTTP {r.status_code}: {r.text[:200]}")
            parts = r.json()["candidates"][0]["content"]["parts"]
            data = next(p["inlineData"]["data"] for p in parts if "inlineData" in p)
            pcm = os.path.join(out_dir, f"gemini{tag}.pcm")
            with open(pcm, "wb") as f:
                f.write(base64.b64decode(data))
            wav = os.path.join(out_dir, f"voice_gemini{tag}.wav")
            run(["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", pcm,
                 "-ar", "44100", wav])
            if duration(wav) < 2:
                raise RuntimeError("audio too short")
            return wav
        except Exception as e:
            last = e
            log(f"gemini_tts model {model} failed: {e}")
    raise RuntimeError(f"all Gemini TTS models failed: {last}")

# ---------- 2) edge-tts (أصوات مايكروسوفت المجانية، بدون مفتاح) ----------
def edge_tts_voice(text, out_dir, voice=None, pitch=None, tag=""):
    import edge_tts
    last = None
    # أزل التكرار مع إبقاء صوت الشخصية المفضل أولاً.
    voices = []
    for candidate in ([voice] if voice else []) + list(config.EDGE_VOICES):
        candidate = candidate.strip()
        if candidate and candidate not in voices:
            voices.append(candidate)
    for v in voices:
        mp3 = os.path.join(out_dir, f"voice_edge{tag}.mp3")
        try:
            async def go():
                await edge_tts.Communicate(text, v.strip(), rate="+0%", pitch=pitch or "+8Hz").save(mp3)
            asyncio.run(go())
            return _to_wav(mp3, os.path.join(out_dir, f"voice_edge{tag}.wav"))
        except Exception as e:
            last = e
            log(f"edge-tts voice {v} failed: {e}")
    raise RuntimeError(f"all edge-tts voices failed: {last}")

# ---------- 3) gTTS (صوت جوجل المجاني، آخر حل) ----------
def gtts_voice(text, out_dir, tag=""):
    from gtts import gTTS
    mp3 = os.path.join(out_dir, f"voice_gtts{tag}.mp3")
    gTTS(text=text, lang="ar").save(mp3)
    return _to_wav(mp3, os.path.join(out_dir, f"voice_gtts{tag}.wav"))

PROVIDERS = {
    "gemini_tts": gemini_tts,
    "edge_tts": edge_tts_voice,
    "gtts": gtts_voice,
}

def candidates(text, out_dir):
    out = []
    for name in config.VOICE_ORDER:
        name = name.strip()
        if name in PROVIDERS:
            out.append((name, (lambda n=name: PROVIDERS[n](text, out_dir))))
    return out


# ---------------------------------------------------------------
# حوار بأصوات أطفال: صوت مختلف ليونس وفريدة. المزود يُجرَّب لكل الحلقة كاملة (ثبات الصوت)
# ---------------------------------------------------------------
def _child_shift(wav, factor, out_dir, tag):
    """يرفع طبقة الصوت بدون تغيير السرعة (ليبدو أقرب لصوت طفل)."""
    out = os.path.join(out_dir, f"shift{tag}.wav")
    run(["ffmpeg", "-y", "-i", wav, "-af",
         f"asetrate=44100*{factor},aresample=44100,atempo={1 / factor:.4f}", out])
    return out

def _line_with(provider, who, text, out_dir, idx):
    k = config.KID_VOICES.get(who, config.KID_VOICES["younis"])
    tag = f"_{idx}"
    if provider == "gemini_tts":
        return gemini_tts(text, out_dir, voice=k["gemini"], style=k["style"], tag=tag)
    if provider == "edge_tts":
        return _child_shift(edge_tts_voice(text, out_dir, voice=k["edge"], pitch=k["pitch"], tag=tag),
                            k["shift"], out_dir, tag)
    if provider == "gtts":
        return _child_shift(gtts_voice(text, out_dir, tag=tag), k["shift"] if who == "farida" else 1.12, out_dir, tag)
    raise RuntimeError(f"unknown provider {provider}")

def _dialogue_with(provider, lines, out_dir):
    parts, timeline, t = [], [], 0.0
    sil = os.path.join(out_dir, "gap.wav")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t",
         str(config.LINE_GAP_SECONDS), sil])
    for i, ln in enumerate(lines):
        w = _line_with(provider, ln["who"], ln["text"], out_dir, i)
        norm = os.path.join(out_dir, f"line_{i}.wav")
        run(["ffmpeg", "-y", "-i", w, "-ar", "44100", "-ac", "1", norm])
        d = duration(norm)
        timeline.append({"who": ln["who"], "text": ln["text"], "start": t, "end": t + d})
        parts += [norm, sil]
        t += d + config.LINE_GAP_SECONDS
    lst = os.path.join(out_dir, "dialogue_list.txt")
    with open(lst, "w") as f:
        for p in parts[:-1]:
            f.write(f"file '{os.path.abspath(p)}'\n")
    out = os.path.join(out_dir, "dialogue.wav")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "pcm_s16le", out])
    return out, timeline

def dialogue_candidates(lines, out_dir):
    cands = []
    for name in config.VOICE_ORDER:
        name = name.strip()
        if name in PROVIDERS:
            cands.append((name, (lambda n=name: _dialogue_with(n, lines, out_dir))))
    return cands
