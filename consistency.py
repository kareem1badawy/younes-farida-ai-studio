"""تشخيص بصري تقريبي يقارن توزيع ألوان الإطارات بالصورة المرجعية.
هذه الدرجة تتأثر بالخلفية والحركة والقصّ، ولا تثبت هوية الوجه أو ثبات الشخصية.
استخدم outfit_ok لفحص ألوان الملابس فقط؛ ولا تعرض أيّاً منهما كتحقق للهوية."""
import os, tempfile
from PIL import Image
from util import run, duration

def _hist(im):
    im = im.convert("RGB").resize((192, 336)).convert("HSV")
    out = []
    for ch in im.split():
        h = ch.histogram()
        b = [sum(h[i * 8:(i + 1) * 8]) for i in range(32)]
        t = float(sum(b)) or 1.0
        out.append([x / t for x in b])
    return out

def similarity(a, b):
    A, B = _hist(a), _hist(b)
    return sum(sum(min(x, y) for x, y in zip(ha, hb)) for ha, hb in zip(A, B)) / 3.0

def clip_score(clip, key_image):
    """أقل تشابه بين إطارات المقطع (عند 35% و65% و95% من طوله) والصورة الافتتاحية."""
    d = duration(clip)
    ref = Image.open(key_image)
    work = tempfile.mkdtemp(prefix="cons_")
    scores = []
    for i, frac in enumerate((0.35, 0.65, 0.95)):
        png = os.path.join(work, f"f{i}.png")
        run(["ffmpeg", "-y", "-ss", f"{max(d * frac, 0.1):.2f}", "-i", clip, "-frames:v", "1", png],
            check=False)
        if os.path.exists(png):
            scores.append(similarity(ref, Image.open(png)))
    if not scores:
        raise RuntimeError("consistency check could not read frames")
    return min(scores)


# ---------- فحص الملابس (للصور المولَّدة، مثل مشاهد الغابة) ----------
def _outfit_fractions(im):
    im = im.convert("RGB").resize((256, 448)).convert("HSV")
    px = list(im.getdata())
    n = float(len(px))
    def frac(f):
        return sum(1 for h, s, v in px if f(h, s, v)) / n
    return {
        "blue_overalls": frac(lambda h, s, v: 128 <= h <= 150 and s > 110 and v > 90),
        "coral_overalls": frac(lambda h, s, v: (h <= 8 or h >= 246) and 80 < s < 200 and v > 140),
        "yellow_shirt": frac(lambda h, s, v: 13 <= h <= 32 and s > 120 and v > 190),
        "purple_shirt": frac(lambda h, s, v: 182 <= h <= 232 and s > 45 and v > 140),
    }

SOLO_REQUIRED = {"younis": ("blue_overalls", "yellow_shirt"), "farida": ("coral_overalls", "purple_shirt")}

def outfit_ok(image_path, min_fraction=0.003, min_groups=3, who=None):
    """فحص خفيف: ألوان ملابس يونس (أزرق/أصفر) وفريدة (مرجاني/بنفسجي) موجودة في الصورة؟
    لا يثبت أن الوجوه نفسها، لكنه يكشف الصور التي تغيّرت ملابسها أو لا تظهر فيها الشخصيتان."""
    fr = _outfit_fractions(Image.open(image_path))
    missing = [k for k, v in fr.items() if v < min_fraction]
    if who in SOLO_REQUIRED:      # لقطة متحدث واحد: يجب أن يظهر لونا ملابسه
        miss = [k for k in SOLO_REQUIRED[who] if fr[k] < min_fraction]
        return (not miss), fr, miss
    return (len(fr) - len(missing) >= min_groups), fr, missing   # 3 من 4 تكفي (قد تُخفي الوضعية لوناً)
