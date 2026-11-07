"""تجميع الفيديو النهائي: توحيد المقاسات + دمج المشاهد + ترجمة عربية + الصوت."""
import os, subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter, features
import config
from util import log, run, duration

# ---------- تجهيز صورة الشخصيات (خلفية مموهة + الصورة في الوسط) ----------
def make_canvas(image_path, out_path):
    W, H = config.WIDTH, config.HEIGHT
    img = Image.open(image_path).convert("RGB")
    bg = img.copy()
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1))
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(35))
    if abs(img.width / img.height - W / H) < 0.06:      # عمودية 9:16 تقريباً: نملأ الشاشة بلا حواف
        full = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1))
        l2, t2 = (full.width - W) // 2, (full.height - H) // 2
        full.crop((l2, t2, l2 + W, t2 + H)).save(out_path, quality=95)
        return out_path
    fscale = min(W / img.width, H / img.height)
    fg = img.resize((int(img.width * fscale), int(img.height * fscale)))
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    bg.save(out_path, quality=95)
    return out_path

def normalize_clip(src, dst):
    W, H = config.WIDTH, config.HEIGHT
    fc = (f"[0:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},boxblur=30:5[bg];[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={config.FPS},format=yuv420p[v]")
    run(["ffmpeg", "-y", "-i", src, "-filter_complex", fc, "-map", "[v]", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", dst])
    return dst

def last_frame(clip, out_jpg):
    """آخر إطار في المقطع: نبدأ منه المقطع التالي ليبقى الشكل والحركة متصلين."""
    run(["ffmpeg", "-y", "-sseof", "-0.15", "-i", clip, "-frames:v", "1", "-q:v", "2", out_jpg])
    if not os.path.exists(out_jpg):
        raise RuntimeError("could not extract last frame")
    return out_jpg

# ---------- الخط والترجمة العربية ----------
def find_arabic_font():
    for fam in ("Noto Naskh Arabic", "Noto Sans Arabic", "Noto Kufi Arabic", "DejaVu Sans"):
        r = subprocess.run(["fc-match", "-f", "%{file}|%{family}", fam],
                           capture_output=True, text=True)
        if r.returncode == 0 and "|" in r.stdout:
            path, family = r.stdout.split("|", 1)
            if os.path.exists(path) and (fam.split()[0].lower() in family.lower() or fam == "DejaVu Sans"):
                return path
    r = subprocess.run(["fc-match", "-f", "%{file}", "sans-serif:lang=ar"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None

# لو كان Pillow مبنياً مع raqm فهو يشكّل العربي ويرتبه بنفسه، وإعادة التشكيل تفسده.
RAQM = features.check("raqm")
TEXT_KW = {"direction": "rtl", "language": "ar"} if RAQM else {}

def _shape(text):
    if RAQM:
        return text
    try:
        import arabic_reshaper
        try:
            from bidi import get_display
        except ImportError:                      # نسخ python-bidi القديمة
            from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        log("WARNING: arabic_reshaper/bidi not installed; Arabic text will look broken")
        return text

def split_chunks(text, max_words=5):
    words = text.split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)] or [text]

def caption_png(text, out_path, font_path, color=(255, 255, 255, 255)):
    W = config.WIDTH
    size = 66
    font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
    max_w = W - 160
    d0 = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    lines, cur = [], []
    for w in text.split():
        trial = " ".join(cur + [w])
        if cur and d0.textlength(_shape(trial), font=font, **TEXT_KW) > max_w:
            lines.append(" ".join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    line_h = int(size * 1.5)
    h = line_h * len(lines) + 50
    img = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((60, 0, W - 60, h), radius=40, fill=(0, 0, 0, 150))
    for i, ln in enumerate(lines):
        shaped = _shape(ln)
        tw = d.textlength(shaped, font=font, **TEXT_KW)
        d.text(((W - tw) / 2, 25 + i * line_h), shaped, font=font, fill=color,
               stroke_width=3, stroke_fill=(0, 0, 0, 255), **TEXT_KW)
    img.save(out_path)
    return out_path, h

# ---------- الصوت: ضبط الطول بين 15 و 20 ثانية ----------
def fit_audio(wav, out_path):
    d = duration(wav)
    log(f"narration length: {d:.1f}s")
    if d > config.MAX_SECONDS:
        tempo = min(1.25, d / config.MAX_SECONDS)
        run(["ffmpeg", "-y", "-i", wav, "-filter:a", f"atempo={tempo:.3f}", out_path])
        d = duration(out_path)
        if d > config.MAX_SECONDS + 0.5:
            run(["ffmpeg", "-y", "-i", out_path, "-t", str(config.MAX_SECONDS),
                 out_path + ".cut.wav"])
            os.replace(out_path + ".cut.wav", out_path)
            d = duration(out_path)
    elif d < config.MIN_SECONDS:
        run(["ffmpeg", "-y", "-i", wav, "-af", f"apad=whole_dur={config.MIN_SECONDS}", out_path])
        d = duration(out_path)
    else:
        run(["ffmpeg", "-y", "-i", wav, out_path])
    return out_path, d

# ---------- التجميع النهائي ----------
SPEAKER_COLORS = {"younis": (150, 205, 255, 255), "farida": (255, 175, 205, 255)}

def captions_from_timeline(timeline, max_words=6):
    """يقسّم كل جملة حوار إلى مقاطع قصيرة موزعة على وقت الجملة، بلون خاص لكل متحدث."""
    caps = []
    for ln in timeline:
        chunks = split_chunks(ln["text"], max_words)
        weights = [max(1, len(c.split())) for c in chunks]
        total, t = float(sum(weights)), ln["start"]
        for c, w in zip(chunks, weights):
            end = t + (ln["end"] - ln["start"]) * w / total
            caps.append({"text": c, "start": t, "end": end, "color": SPEAKER_COLORS.get(ln["who"], (255, 255, 255, 255))})
            t = end
    return caps

def conform(src, dur, dst):
    """يضبط طول المقطع: قصّ لو أطول، وتثبيت آخر إطار لو أقصر."""
    d = duration(src)
    vf = f"tpad=stop_mode=clone:stop_duration={dur - d + 0.1:.2f}" if d < dur else "null"
    run(["ffmpeg", "-y", "-i", src, "-vf", vf, "-t", f"{dur:.2f}", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-an", dst])
    return dst

def build_final(clips, audio_path, narration, work_dir, out_mp4, durations=None):
    """narration: نص (تقسيم متساوٍ) أو قائمة حوار [{who,text,start,end}] لترجمة بتوقيت الكلام الحقيقي."""
    audio_len = duration(audio_path)
    norm = []
    for i, c in enumerate(clips):
        n = normalize_clip(c, os.path.join(work_dir, f"norm_{i}.mp4"))
        if durations:
            n = conform(n, durations[i], os.path.join(work_dir, f"conf_{i}.mp4"))
        norm.append(n)
    lst = os.path.join(work_dir, "list.txt")
    with open(lst, "w") as f:
        for n in norm:
            f.write(f"file '{os.path.abspath(n)}'\n")
    joined = os.path.join(work_dir, "joined.mp4")
    # -stream_loop يكرر المشاهد لو كانت أقصر من الصوت
    run(["ffmpeg", "-y", "-stream_loop", "-1", "-f", "concat", "-safe", "0", "-i", lst,
         "-t", f"{audio_len:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-an", joined])

    font = find_arabic_font()
    log(f"caption font: {font} | raqm={RAQM}")
    if isinstance(narration, list):
        caps = captions_from_timeline(narration)
    else:
        chunks = split_chunks(narration)
        weights = [max(1, len(c.split())) for c in chunks]
        total_w, t, caps = sum(weights), 0.0, []
        for c, w in zip(chunks, weights):
            caps.append({"text": c, "start": t, "end": t + audio_len * w / total_w, "color": (255, 255, 255, 255)})
            t += audio_len * w / total_w
    inputs, filters, last = ["-i", joined, "-i", audio_path], [], "0:v"
    for i, cap in enumerate(caps):
        png, h = caption_png(cap["text"], os.path.join(work_dir, f"cap_{i}.png"), font, cap["color"])
        start, end = cap["start"], min(cap["end"], audio_len)
        inputs += ["-i", png]
        y = int(config.HEIGHT * 0.79)
        filters.append(f"[{last}][{i + 2}:v]overlay=0:{y}:enable='between(t,{start:.2f},{end:.2f})'[v{i}]")
        last = f"v{i}"
    cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex", ";".join(filters),
           "-map", f"[{last}]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
           "-t", f"{audio_len:.2f}", "-movflags", "+faststart", out_mp4]
    run(cmd)
    return out_mp4
