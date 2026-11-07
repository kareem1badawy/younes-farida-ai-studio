"""صورة افتتاحية عمودية لكل لقطة، مع ثبات شكل الشخصيات:
- يوم البيت: اقتطاعات من الصورة المرجعية نفسها (الوجوه والملابس مطابقة 100%).
- يوم الغابة: صورة تُولَّد بـ Gemini (نانو بنانا) بالصورة المرجعية، وتُرفض لو اختفت ألوان الملابس."""
import base64, os
import config
from PIL import Image
from util import log, try_chain, request_retry
import consistency

def _valid(path):
    Image.open(path).verify()
    return path

# أحجام اقتطاع بنسبة 9:16 نفسها (كسر من الصورة الأصلية، إزاحة رأسية)
CROPS = [(1.00, 0.00), (0.82, 0.03), (0.66, 0.06), (0.90, 0.00)]

def crop_index(camera):
    c = (camera or "").lower()
    if "close" in c:
        return 2
    if "low angle" in c:
        return 3
    if "medium" in c:
        return 1
    return 0

def reference_crop(idx, ref_path, out):
    img = Image.open(ref_path).convert("RGB")
    f, y0 = CROPS[idx % len(CROPS)]
    w, h = img.width * f, img.height * f
    x0 = (img.width - w) / 2
    top = img.height * y0
    box = (int(x0), int(top), int(x0 + w), int(min(top + h, img.height)))
    img.crop(box).resize((768, 1344), Image.LANCZOS).save(out, quality=95)
    return out

# لقطة متحدث واحد (قريبة): اقتطاع نظيف لا يظهر فيه الطفل الآخر (جُرّبت على الصورة المرجعية)
SOLO_CROPS = [(0.50, 0.09), (0.46, 0.10)]

def speaker_crop(who, variant, ref_path, out):
    img = Image.open(ref_path).convert("RGB")
    W, H = img.size
    f, y0 = SOLO_CROPS[variant % len(SOLO_CROPS)]
    w = W * f
    h = w * H / W
    x0 = 0.02 * W if who == "younis" else W - w - 0.02 * W
    top = H * y0
    img.crop((int(x0), int(top), int(x0 + w), int(min(top + h, H)))).resize((768, 1344), Image.LANCZOS).save(out, quality=95)
    return out

def gemini_image(prompt, ref_path, out, who=None):
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing")
    ref_b64 = base64.b64encode(open(ref_path, "rb").read()).decode()
    last = None
    for model in config.GEMINI_IMAGE_MODELS:
        for attempt in (1, 2):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model.strip()}:generateContent"
            body = {
                "contents": [{"parts": [
                    {"text": "Using the reference image, keep the exact same two characters (same faces, hair, "
                             "outfits with name tags, 3D animated style). Create a NEW vertical 9:16 scene with both "
                             "characters fully visible, a single image, no collage, no text overlays. Scene: " + prompt},
                    {"inlineData": {"mimeType": "image/jpeg", "data": ref_b64}},
                ]}],
                "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}},
            }
            try:
                r = request_retry("POST", url, json=body, timeout=180, headers={"x-goog-api-key": config.GEMINI_API_KEY})
                if r.status_code != 200:
                    raise RuntimeError(f"{model} HTTP {r.status_code}: {r.text[:200]}")
                parts = r.json()["candidates"][0]["content"]["parts"]
                data = next(p["inlineData"]["data"] for p in parts if "inlineData" in p)
                with open(out, "wb") as f:
                    f.write(base64.b64decode(data))
                _valid(out)
                ok, fr, missing = consistency.outfit_ok(out, who=who)
                if not ok:
                    raise RuntimeError(f"outfit colors missing {missing}")
                return out
            except Exception as e:
                last = e
                log(f"gemini_image {model} try {attempt} failed: {str(e)[:200]}")
    raise RuntimeError(f"all Gemini image attempts failed: {last}")

def make_keyframe(index, scene_prompt, ref_path, work, location="home", camera="", kind="wide", who=None):
    out = os.path.join(work, f"key_{index}.jpg")
    order = config.FOREST_IMAGE_ORDER if location == "forest" else config.IMAGE_ORDER
    solo = (kind == "speech" and who in ("younis", "farida"))
    cands = []
    for name in order:
        name = name.strip()
        if name == "reference_crop":
            if solo:
                cands.append((name, lambda: speaker_crop(who, index // 2, ref_path, out)))
            else:
                cands.append((name, lambda: reference_crop(crop_index(camera) if index == 0 else 3, ref_path, out)))
        elif name == "gemini_image":
            cands.append((name, lambda: gemini_image(scene_prompt, ref_path, out, who if solo else None)))
    res, label, errs = try_chain(f"keyframe {index + 1}", cands)
    if not res:
        raise RuntimeError("all keyframe providers failed: " + " | ".join(errs))
    if location == "forest" and label == "reference_crop":
        label = "reference_crop(FALLBACK: playroom, forest image failed)"
    return res, label, errs
