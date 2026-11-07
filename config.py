"""كل الإعدادات في مكان واحد. غيّر هنا فقط عند الحاجة."""
import os

# ---- الشخصيات ----
# صورة الشخصيات (يونس وفريدة). تُحمّل وقت التشغيل.
CHARACTER_IMAGE_URL = os.getenv("CHARACTER_IMAGE_URL", "https://raw.githubusercontent.com/kareem1badawy/younis-farida-daily-video/main/character.jpg")   # اختياري؛ الأفضل رفع character.jpg في المستودع
CHARACTER_IMAGE_BACKUP_URL = os.getenv("CHARACTER_IMAGE_BACKUP_URL", "")

CHANNEL_NAME_AR = "عالم يونس وفريدة"

# ---- مواصفات الفيديو ----
WIDTH, HEIGHT = 1080, 1920          # عمودي 9:16
FPS = 24
# مدة الحلقة المستهدفة: 20 ثانية. يمكن تجاوزها صراحةً عبر متغيرات البيئة.
MIN_SECONDS = 20.0
MAX_SECONDS = 20.0
SCENES = int(os.getenv("SCENES") or "5")      # عدد المقاطع المستقلة؛ كل واحد يبدأ من الصورة المرجعية (يثبّت الشكل)
# التمديد بمقاطع متتابعة (آخر إطار -> مقطع جديد) يسبب انحراف الشكل، لذلك مُعطّل افتراضياً
CHAIN_CLIPS = os.getenv("CHAIN_CLIPS", "0") == "1"
# حد أدنى لثبات الشكل (0-1). أقل منه = ارفض المقطع وجرّب المزود التالي
SIM_MIN = float(os.getenv("SIM_MIN") or "0.75")
NEGATIVE_PROMPT = ("different face, changed hairstyle, changed outfit, different clothes, extra people, "
                   "morphing, deformed, distorted, blurry, text, watermark, subtitles")

# ---- مفاتيح (من أسرار GitHub) ----
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")

# ---- نماذج Gemini (قابلة للتغيير من متغيرات البيئة) ----
GEMINI_TEXT_MODELS = os.getenv(
    "GEMINI_TEXT_MODELS", "gemini-flash-latest"
).split(",")
GEMINI_TTS_MODELS = os.getenv(
    "GEMINI_TTS_MODELS", "gemini-2.5-flash-preview-tts,gemini-2.5-pro-preview-tts"
).split(",")
GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Kore")
GEMINI_IMAGE_MODELS = os.getenv(
    "GEMINI_IMAGE_MODELS", "gemini-2.5-flash-image,gemini-3-pro-image-preview,gemini-2.0-flash-preview-image-generation"
).split(",")
# ترتيب مزودي الصورة الافتتاحية لكل مشهد
# pollinations مُعطّل افتراضياً: لا يقبل صورة مرجعية فيغيّر شكل الشخصيات
IMAGE_ORDER = os.getenv("IMAGE_ORDER") or "reference_crop"
IMAGE_ORDER = IMAGE_ORDER.split(",")

# ---- ترتيب مزودي الصوت (يجرّب بالترتيب) ----
# Edge TTS أولاً لتجنب استهلاك حصة Gemini TTS التي ظهرت ممتلئة في الاختبار.
# Edge ثم gTTS كبديل مجاني، وGemini أخيراً لتجنب الحصة الممتلئة.
VOICE_ORDER = os.getenv("VOICE_ORDER", "edge_tts,gtts,gemini_tts").split(",")
EDGE_VOICES = os.getenv("EDGE_VOICES", "ar-EG-SalmaNeural,ar-SA-ZariyahNeural,ar-SA-HamedNeural").split(",")

# ---- ترتيب مزودي الفيديو (لكل مشهد على حدة) ----
# كل عنصر هو مساحة (Space) مجانية على Hugging Face. لو فشلت ننتقل للتي بعدها.
VIDEO_SPACES = [
    s.strip() for s in os.getenv(
        "VIDEO_SPACES",
        "zerogpu-aoti/wan2-2-fp8da-aoti-faster,"
        "multimodalart/wan2-1-fast,"
        "Lightricks/ltx-video-distilled",
    ).split(",") if s.strip()
]

# ---- فيديو مدفوع بالكلام (صورة + صوت -> شخصية تتكلم بحركة شفايف متزامنة) ----
# Wan-AI/Wan2.2-S2V: مساحة رسمية على Hugging Face (المدخلات: صورة، صوت، دقة). يمكن إضافة مساحات أخرى مفصولة بفاصلة.
SPEECH_SPACES = [s.strip() for s in (os.getenv("SPEECH_SPACES") or "Wan-AI/Wan2.2-S2V").split(",") if s.strip()]
# نبدأ بتحريك الجسم من صورة + وصف. مزامنة الشفاه عبر S2V قد تستهلك حصة GPU
# كبيرة وتقلل فرص إكمال حلقة مجانية يومياً؛ يمكن تفعيلها لاحقاً باختبار مستقل.
SPEECH_ENABLED = (os.getenv("SPEECH_VIDEO") or "0") == "1"
SIM_MIN_SPEECH = float(os.getenv("SIM_MIN_SPEECH") or "0.60")   # أقل صرامة: الإطار قد يتغير مع الكلام

# ---- Veo (جودة جوجل). مدفوع: لا يعمل إلا لو VEO_ENABLED=1 ----
VEO_ENABLED = os.getenv("VEO_ENABLED", "0") == "1"
VEO_MODELS = (os.getenv("VEO_MODELS") or "veo-3.1-lite-generate-preview,veo-3.1-fast-generate-preview").split(",")
VEO_RESOLUTION = os.getenv("VEO_RESOLUTION") or "720p"
# سقف أمان لعدد ثواني Veo المولّدة في التشغيلة الواحدة (يحمي من أي حلقة تكرار تصرف فلوساً)
VEO_MAX_SECONDS_PER_RUN = int(os.getenv("VEO_MAX_SECONDS_PER_RUN", "24"))

VIDEO_ORDER = os.getenv("VIDEO_ORDER", "hf_spaces").split(",")
# تحريك الكاميرا على صورة ثابتة ليس تحريكاً للشخصيات؛ لا تسمح به إلا بطلب صريح.
ALLOW_CAMERA_ONLY_FALLBACK = os.getenv("ALLOW_CAMERA_ONLY_FALLBACK", "0") == "1"
SPACE_TIMEOUT_SECONDS = int(os.getenv("SPACE_TIMEOUT_SECONDS", "420"))
# إعادة المحاولة على نفس مزود الفيديو عند فشل فحص الثبات فقط.
VIDEO_RETRIES_PER_SPACE = max(1, int(os.getenv("VIDEO_RETRIES_PER_SPACE", "2")))

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
HISTORY_FILE = "history.json"

# ---- أصوات الأطفال (حوار يونس وفريدة) ----
# Gemini TTS: Puck (مرح) ليونس وLeda (شابة) لفريدة + وصف أسلوبي للطفولة
KID_VOICES = {
    "younis": {"gemini": "Puck", "edge": "ar-EG-ShakirNeural", "pitch": "+22Hz", "shift": 1.20,
               "style": "a cheerful, curious 5-year-old boy"},
    "farida": {"gemini": "Leda", "edge": "ar-EG-SalmaNeural", "pitch": "+32Hz", "shift": 1.30,
               "style": "a sweet, cheerful 4-year-old girl"},
}
LINE_GAP_SECONDS = 0.25
# صورة المشاهد في يوم الغابة (الغابة تحتاج توليد صورة، وليست موجودة في الصورة المرجعية)
FOREST_IMAGE_ORDER = (os.getenv("FOREST_IMAGE_ORDER") or "gemini_image,reference_crop").split(",")
LOCATION_OVERRIDE = os.getenv("LOCATION", "").strip()   # home | forest | فارغ = تناوب تلقائي
