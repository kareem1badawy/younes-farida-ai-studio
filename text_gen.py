"""فكرة الحلقة بحوار بين يونس وفريدة + خطة لقطات الكاميرا. Gemini أولاً، وإن فشل نستخدم بنك أفكار جاهز.
الحلقات تتناوب: يوم في البيت، ويوم في الغابة."""
import json, re
import config
from util import log, request_retry

CHARACTERS = ("Younis (little boy, curly dark hair, blue denim overalls with the name Younis, yellow t-shirt, "
              "blue sneakers) and Farida (little girl, two dark braids, coral overalls with the name Farida, "
              "purple t-shirt, pink sneakers), 3D Pixar-style animation, same faces and outfits as the reference")

LOCATIONS = {
    "home": "a cozy pastel children's playroom (teal wall, stars, soft toys, colorful balls, rainbow rug)",
    "forest": "a magical sunny forest (tall trees, wildflowers, soft sunbeams, a winding dirt path)",
}
LOCATION_AR = {"home": "في البيت", "forest": "في الغابة"}

# خطة كاميرا افتراضية بنفس أسلوب فيديو السحابة: واسعة، تتبع، قريبة، متوسطة من زاوية، واسعة ختامية
DEFAULT_CAMERAS = [
    "wide establishing shot, camera slowly pushes in",
    "medium tracking shot, camera pans sideways following the characters as they walk",
    "close-up on the characters' faces, slow push-in",
    "medium two-shot from a slightly low angle, gentle camera move",
    "wide closing shot, both characters wave to the camera, slow push-in",
]

WIDE_MOTION_LOCK = (
    "ANIMATE BOTH CHARACTERS, NOT JUST THE CAMERA. Keep both children visible together in a clear "
    "two-shot with readable full-body action when the framing allows it. Choreograph one simple "
    "cause-and-effect interaction in three continuous phases: one child initiates a clear action; "
    "the other child notices and visibly responds with a matching gesture, step or facial reaction; "
    "then both complete the shared action and settle naturally. Keep their positions and any shared "
    "prop consistent from start to finish. Show visible weight shifts, steps, arm movement, head turns, "
    "eye-lines and expressive reactions; neither child may remain frozen while the other acts. "
    "Prefer a simple safe interaction over several unrelated gestures. Keep the background relatively "
    "stable and camera movement subtle so the characters' movement is easy to see. "
    "Preserve the exact reference identities, faces, hairstyles, outfits and name tags. "
    "No extra people, no morphing, no text."
)

SOLO_MOTION_LOCK = (
    "ANIMATE ONLY THE NAMED SPEAKER in this single-character shot. Keep the second child out of frame; "
    "do not request a full-body composition. Adapt any shared story action to the named speaker's own "
    "visible contribution only. If the other child is part of the action, keep that child off-screen "
    "and let the speaker acknowledge their off-screen position through a natural glance, head turn or "
    "responsive expression; never imply that the second child is visible. Use a readable medium "
    "close-up or upper-body composition with natural torso and shoulder shifts, expressive hand "
    "gestures within frame, small head turns, blinking and mouth movement while speaking. The speaker "
    "must not freeze in a static talking-head pose. Keep the background relatively stable and camera "
    "movement subtle. Preserve the exact reference identity, face, hairstyle, outfit and name tag. "
    "No extra people, no morphing, no text."
)

def D(l):  # اختصار لسطر حوار
    return {"who": l[0], "text": l[1]}

# بنك احتياطي متنوع. لكل فكرة موضوع ثابت لمنع إعادة إنتاج نفس الدرس بصياغة مختلفة.
def _idea(location, topic, title, dialogue, actions):
    return {"location": location, "topic": topic, "title": title,
            "lines": [D(x) for x in dialogue], "actions": actions}

FALLBACK_BANK = [
    _idea("home", "handwashing", "يونس وفريدة يغسلان أيديهما",
          [("younis", "مرحباً يا أصدقاء! أنا يونس."), ("farida", "وأنا فريدة! هيا نغسل أيدينا."),
           ("younis", "نفتح الماء ونضع الصابون."), ("farida", "نفرك الكفين ونعد إلى عشرين."),
           ("younis", "الآن أيدينا نظيفة!"), ("farida", "إلى اللقاء يا أصدقاء!")],
          ["the kids enter the playroom and greet the camera", "they walk to a small sink and turn on the water", "Farida rubs her hands with soap bubbles", "Younis shows his clean hands proudly", "both wave goodbye"]),
    _idea("forest", "butterfly", "يونس وفريدة يجدان فراشة",
          [("farida", "انظر يا يونس! فراشة ملونة!"), ("younis", "ما أجملها! هيا نتبعها بهدوء."),
           ("farida", "نمشي على أطراف أصابعنا."), ("younis", "ها هي تقف على الزهرة!"),
           ("farida", "نحب الطبيعة ونحافظ عليها."), ("younis", "إلى اللقاء!")],
          ["the kids walk along a forest path and Farida points at a butterfly", "they tiptoe after it between flowers", "Farida watches it land on a flower", "Younis points gently without touching it", "both wave goodbye"]),
    _idea("home", "tidying", "يونس وفريدة يرتبان الألعاب",
          [("farida", "غرفتنا مليئة بالألعاب!"), ("younis", "هيا نرتبها معاً."),
           ("farida", "الكرات في هذا الصندوق."), ("younis", "والدمية على الرف."),
           ("farida", "ما أجمل الغرفة المرتبة!"), ("younis", "إلى اللقاء!")],
          ["the kids look around a toy-filled playroom", "they pick up toys and carry them", "Farida puts balls into a box", "Younis places a teddy bear on a shelf", "both admire the tidy room and wave"]),
    _idea("forest", "colors", "يونس وفريدة يكتشفان ألوان الغابة",
          [("younis", "ما لون هذه الورقة يا فريدة؟"), ("farida", "خضراء! وهذه الزهرة حمراء."),
           ("younis", "والسماء زرقاء فوقنا!"), ("farida", "والشمس صفراء ودافئة."),
           ("younis", "ما أجمل ألوان الغابة!"), ("farida", "إلى اللقاء يا أصدقاء!")],
          ["Younis holds up a green leaf", "Farida points to a red flower", "both look up at the blue sky", "Farida points toward warm sunlight", "both wave in a sunny clearing"]),
    _idea("home", "sharing", "يونس وفريدة يتعلمان المشاركة",
          [("younis", "أريد هذه الكرة الجميلة."), ("farida", "يمكننا اللعب بها معاً."),
           ("younis", "سأدحرجها إليك."), ("farida", "والآن أعيدها إليك!"),
           ("younis", "اللعب معاً ممتع."), ("farida", "المشاركة تجعلنا سعداء!")],
          ["Younis picks up a colorful ball", "Farida asks to join and smiles", "Younis rolls the ball to Farida", "Farida rolls it back", "both celebrate their game"]),
    _idea("forest", "nature_cleanup", "يونس وفريدة ينظفان مكان النزهة",
          [("farida", "انظر يا يونس، هناك ورقة على الأرض."), ("younis", "لنحافظ على غابتنا جميلة."),
           ("farida", "أضعها في كيس النفايات."), ("younis", "وأنا أجمع الورق nearby."),
           ("farida", "أصبحت الحديقة نظيفة."), ("younis", "الطبيعة بيتنا!")],
          ["the kids notice litter near their picnic spot", "Younis picks up a safe paper wrapper", "Farida places it in a small bag", "they look around for more litter", "they admire the clean spot"]),
    _idea("home", "shapes", "يونس وفريدة يبحثان عن الأشكال",
          [("farida", "هذه نافذة مربعة!"), ("younis", "والساعة دائرية."),
           ("farida", "انظر إلى المكعب، له أوجه مربعة."), ("younis", "وجدت لعبة مثلثية!"),
           ("farida", "الأشكال حولنا في كل مكان."), ("younis", "إلى اللقاء!")],
          ["Farida points to a square window", "Younis shows a round toy clock", "they turn a wooden cube together", "Younis finds a triangle block", "both compare the shapes and wave"]),
    _idea("forest", "birdsong", "يونس وفريدة يستمعان إلى أصوات الطيور",
          [("younis", "هل سمعتِ هذا الصوت يا فريدة؟"), ("farida", "إنه عصفور يغرد فوقنا."),
           ("younis", "لنستمع بهدوء."), ("farida", "صوته جميل مثل الموسيقى."),
           ("younis", "لا نزعج الطيور في أعشاشها."), ("farida", "وداعاً يا أصدقاء!")],
          ["the kids pause on a forest path and listen", "Farida points toward a bird in a distant tree", "both cup a hand near an ear and listen", "Younis smiles at the birdsong", "they quietly wave goodbye"]),
    _idea("home", "planting", "يونس وفريدة يزرعان بذرة",
          [("younis", "ماذا سنزرع اليوم؟"), ("farida", "هذه بذرة صغيرة."),
           ("younis", "نضعها في التراب برفق."), ("farida", "ثم نسقيها قليلاً."),
           ("younis", "سنعتني بها كل يوم."), ("farida", "حتى تكبر وتصبح نبتة!")],
          ["the kids examine a large seed packet", "Farida makes a small hole in a pot of soil", "Younis places a seed gently", "they water the soil together", "both imagine the plant growing"]),
    _idea("forest", "animal_tracks", "يونس وفريدة يتتبعان آثار الأقدام",
          [("farida", "ما هذه العلامات على التراب؟"), ("younis", "تبدو آثار أقدام صغيرة."),
           ("farida", "لمن يمكن أن تكون؟"), ("younis", "ربما لأرنب مر من هنا."),
           ("farida", "لنراقب من بعيد دون إزعاجه."), ("younis", "المغامرة ممتعة!")],
          ["Farida notices small footprints in soft earth", "Younis crouches to look closely", "they follow the tracks slowly", "a rabbit is glimpsed far away between trees", "the kids watch quietly and wave"]),
    _idea("home", "music", "يونس وفريدة يصنعان فرقة موسيقية",
          [("farida", "هيا نصنع موسيقى يا يونس!"), ("younis", "سأستخدم الطبلة الصغيرة."),
           ("farida", "وأنا سأهز الجرس."), ("younis", "واحد، اثنان، ثلاثة!"),
           ("farida", "كم إيقاعنا جميل!"), ("younis", "صفقوا معنا!")],
          ["the kids choose safe toy instruments", "Younis taps a small toy drum", "Farida shakes a hand bell", "they play a simple rhythm together", "both clap and dance in place"]),
    _idea("forest", "rainbow", "يونس وفريدة يشاهدان قوس قزح",
          [("younis", "انظري يا فريدة إلى السماء!"), ("farida", "قوس قزح جميل بعد المطر."),
           ("younis", "أرى الأحمر والأصفر."), ("farida", "وأرى الأخضر والأزرق."),
           ("younis", "ألوانه تملأ قلبي فرحاً."), ("farida", "ما أجمل الطبيعة!")],
          ["the kids step into a sunny clearing after a light shower", "Farida points at a rainbow", "Younis traces its colors in the air", "they name colors together", "both smile and wave"]),
    _idea("home", "baking", "يونس وفريدة يحضّران سلطة الفواكه",
          [("younis", "ما رأيكِ أن نحضر وجبة ملونة؟"), ("farida", "نغسل الفواكه أولاً."),
           ("younis", "أضع قطع التفاح هنا."), ("farida", "وأضيف الموز والعنب."),
           ("younis", "ألوانها جميلة ومفيدة."), ("farida", "نتناولها مع العائلة!")],
          ["the kids stand at a safe low kitchen counter with an adult nearby", "they rinse fruit in a bowl", "Younis places prepared apple pieces in a bowl", "Farida adds banana and grapes", "they admire the colorful fruit salad"]),
    _idea("forest", "clouds", "يونس وفريدة يتخيلان أشكال الغيوم",
          [("farida", "هذه الغيمة تشبه الأرنب!"), ("younis", "وتلك تشبه سفينة كبيرة."),
           ("farida", "خيالنا واسع يا يونس."), ("younis", "كل غيمة لها شكل مختلف."),
           ("farida", "لنخترع قصة عنها."), ("younis", "هيا نبدأ!")],
          ["the kids lie on a picnic blanket in a safe clearing", "Farida points at a fluffy cloud", "Younis imagines a ship shape", "they take turns describing cloud shapes", "both laugh and wave"]),
    _idea("home", "puzzles", "يونس وفريدة يحلان لغز الصور",
          [("farida", "أين تذهب هذه القطعة؟"), ("younis", "جرّبي وضعها بجانب الزرقة."),
           ("farida", "وجدت مكانها الصحيح!"), ("younis", "بقيت قطعة واحدة."),
           ("farida", "معاً نستطيع حل اللغز."), ("younis", "نجحنا!")],
          ["the kids sit together with a large child-safe picture puzzle", "Younis points to a matching blue edge", "Farida fits a puzzle piece", "they search for the final piece", "they place it together and celebrate"]),
    _idea("forest", "bridge", "يونس وفريدة يعبران الجسر الصغير",
          [("younis", "هذا جسر خشبي صغير."), ("farida", "سنعبره بهدوء."),
           ("younis", "أمسكي يدي يا فريدة."), ("farida", "خطوة خطوة، نحن معاً."),
           ("younis", "وصلنا إلى الجهة الأخرى!"), ("farida", "كانت مغامرة جميلة!")],
          ["the kids approach a low sturdy footbridge with a safe path", "Younis offers Farida his hand", "they cross slowly side by side", "Farida steps carefully while Younis encourages her", "they reach the other side and celebrate"]),
]

# تصنيف موضوعي محافظ: لا نستخدم كلمات عامة مثل "نظافة" أو "زهرة" وحدها
# لأنها قد تخلط بين موضوعات مختلفة (غسل اليدين مقابل تنظيف الطبيعة).
TOPIC_KEYWORDS = {
    "handwashing": ("غسل اليدين", "يغسلان ايديهما", "نغسل ايدينا", "اغسل ايدينا",
                    "غسل ايدينا", "صابون", "نفرك الكفين", "تعقيم اليدين", "handwashing", "wash hands"),
    "tidying": ("ترتيب الالعاب", "يرتبان الالعاب", "نرتب الالعاب", "غرفة مرتبة", "صندوق الالعاب"),
    "butterfly": ("فراشة", "فراشات", "butterfly"),
    "colors": ("اكتشاف الالوان", "الوان الغابة", "لون هذه الورقة", "نسمي الالوان"),
    "sharing": ("المشاركة", "نتشارك", "نتقاسم", "ندحرج الكرة"),
    "nature_cleanup": ("النفايات", "القمامة", "المخلفات", "كيس النفايات", "نجمع القمامة", "litter", "pick up trash"),
    "shapes": ("الاشكال", "مربع", "دائري", "مثلث"),
    "birdsong": ("طيور", "عصفور", "تغريد", "اصوات الطيور", "birdsong"),
    "planting": ("نزرع", "بذرة", "نبتة", "التراب", "planting", "plant a seed"),
    "animal_tracks": ("اثار الاقدام", "اثار ارنب", "نتتبع الاثار"),
    "music": ("موسيقى", "طبلة", "جرس", "ايقاع"),
    "rainbow": ("قوس قزح", "الوان قوس قزح", "rainbow"),
    "baking": ("فواكه", "سلطة الفواكه", "تفاح", "موز", "fruit salad"),
    "clouds": ("غيوم", "غيمة", "سحاب", "اشكال الغيوم"),
    "puzzles": ("لغز", "احجية", "قطع اللغز", "تركيب الصور"),
    "bridge": ("جسر", "يعبران الجسر", "عبور الجسر"),
}

# عبارات من الحوار والأفعال. الكلمات العامة لا تُعد دليلاً كافياً على الموضوع.
CONTENT_TOPIC_KEYWORDS = {
    "handwashing": ("صابون", "نفرك الكفين", "نغسل ايدينا", "اغسل ايدينا", "غسل اليدين",
                    "نغسل ايدينا بالماء", "الماء والصابون", "رغوة الصابون", "wash hands",
                    "washing their hands", "soap bubbles", "rub their hands"),
    "tidying": ("نرتب الالعاب", "ترتيب الالعاب", "نضعها في الصندوق", "نجمع الالعاب", "toy box"),
    "butterfly": ("فراشة", "فراشات", "butterfly"),
    "sharing": ("المشاركة", "نتشارك", "نتقاسم", "ندحرج الكرة", "share the ball"),
    "nature_cleanup": ("النفايات", "القمامة", "المخلفات", "كيس النفايات", "نجمع المخلفات", "litter", "trash", "garbage"),
    "planting": ("بذرة", "نزرع", "نسقي النبتة", "plant a seed", "planting"),
    "music": ("طبلة", "جرس", "نعزف", "ايقاع", "drum", "bell"),
    "baking": ("سلطة الفواكه", "قطع التفاح", "الموز والعنب", "fruit salad"),
    "puzzles": ("احجية", "قطعة اللغز", "تركيب الصور", "puzzle piece"),
    "bridge": ("الجسر", "نعبر الجسر", "cross the bridge"),
    "birdsong": ("تغريد", "زقزقة", "عصفور يغرد", "birds singing"),
    "animal_tracks": ("اثار الاقدام", "اثار ارنب", "نتتبع الاثار", "animal tracks"),
    "rainbow": ("قوس قزح", "rainbow"),
    "clouds": ("الغيوم", "اشكال الغيوم", "cloud shapes"),
    "shapes": ("المثلث", "المربع", "المكعب", "shapes"),
    "colors": ("الورقة الخضراء", "الزهرة الحمراء", "نسمي الالوان", "name the colors"),
}


def _norm_ar(text):
    text = re.sub(r"[\u064b-\u065f\u0670]", "", str(text or ""))
    text = re.sub(r"[إأآا]", "ا", text).replace("ى", "ي").replace("ة", "ه").lower()
    return re.sub(r"\s+", " ", text).strip()


def _infer_topic(title):
    normalized = _norm_ar(title)
    # العنوان وحده لا يكفي إلا عند وجود عبارة موضوعية واضحة.
    for key, phrases in TOPIC_KEYWORDS.items():
        if any(_norm_ar(phrase) in normalized for phrase in phrases):
            return key
    return ""


def _candidate_text(candidate):
    parts = [candidate.get("title", ""), candidate.get("description", "")]
    parts.extend(line.get("text", "") for line in candidate.get("lines", []) if isinstance(line, dict))
    actions = candidate.get("actions", [])
    if isinstance(actions, list):
        parts.extend(str(action) for action in actions)
    return _norm_ar(" ".join(map(str, parts)))


def _candidate_topics(candidate):
    """استنتج الموضوع من العنوان والحوار والأفعال؛ لا تثق في تصنيف النموذج وحده."""
    content = _candidate_text(candidate)
    topics = set()
    title_topic = _infer_topic(candidate.get("title", ""))
    if title_topic:
        topics.add(title_topic)
    for topic, phrases in CONTENT_TOPIC_KEYWORDS.items():
        if any(_norm_ar(phrase) in content for phrase in phrases):
            topics.add(topic)
    return topics


def _history_topics(history):
    topics = set()
    for item in history:
        if not isinstance(item, dict):
            continue
        topic = item.get("topic")
        if topic:
            topics.add(topic)
        inferred = _infer_topic(item.get("title", ""))
        if inferred:
            topics.add(inferred)
        # السجلات الجديدة تحفظ الحوار والأفعال؛ والسجلات القديمة تظل مدعومة.
        topics.update(_candidate_topics(item))
    return topics

def _title_tokens(value):
    ignored = {"يونس", "وفريده", "وفريدة", "يوني", "في", "من", "على", "مع", "عن", "الى", "يا", "ال"}
    words = re.findall(r"[\u0600-\u06FF]+", _norm_ar(value))
    return {w for w in words if len(w) > 2 and w not in ignored}

def _content_tokens(candidate):
    text = _candidate_text(candidate)
    words = re.findall(r"[\u0600-\u06FFa-z]+", text)
    stop = {"يونس", "فريده", "فريدة", "هما", "هذا", "هذه", "ذلك", "هناك", "هيا", "مع", "في", "من", "على", "الى", "يا", "انا", "ونحن", "ثم", "بعد", "كان", "كانت", "the", "and", "they", "their", "both", "with", "from"}
    return {w for w in words if len(w) > 2 and w not in stop}


def _is_content_duplicate(candidate, history):
    """مقارنة المحتوى المحفوظ، لا العنوان فقط، مع عتبة محافظة لتقليل الرفض الخاطئ."""
    tokens = _content_tokens(candidate)
    if len(tokens) < 5:
        return False
    for old in history[-60:]:
        old_tokens = _content_tokens(old)
        if len(old_tokens) < 5:
            continue
        overlap = len(tokens & old_tokens) / max(1, len(tokens | old_tokens))
        if overlap >= 0.55:
            return True
    return False


def _is_recent_duplicate(title, topic, history):
    normalized = _norm_ar(title)
    candidate_tokens = _title_tokens(title)
    recent = history[-60:]
    for item in recent:
        old = _norm_ar(item.get("title", ""))
        if normalized and old and (normalized == old or normalized in old or old in normalized):
            return True
        old_tokens = _title_tokens(old)
        if candidate_tokens and old_tokens:
            overlap = len(candidate_tokens & old_tokens) / max(1, len(candidate_tokens | old_tokens))
            if overlap >= 0.60:
                return True
    return bool(topic and topic in _history_topics(recent))


def _prompt(history_titles, location):
    return (
        "أنت كاتب محتوى أطفال (3-7 سنوات) لقناة يوتيوب عربية اسمها عالم يونس وفريدة، بطلاها الطفلان يونس وفريدة. "
        f"اكتب حلقة قصيرة جداً تدور {LOCATION_AR[location]}، تعليمية ولطيفة وآمنة تماماً للأطفال، بعربية بسيطة.\n"
        f"عناوين حلقات سابقة (لا تكررها ولا تقدم موضوعاً قريباً منها): {json.dumps(history_titles[-60:], ensure_ascii=False)}\n"
        "الحلقة حوار قصير بين يونس وفريدة (6 إلى 8 جمل قصيرة، المجموع بين 42 و50 كلمة ليكون الصوت قريباً من 30 ثانية) وتنتهي بتوديع الجمهور. "
        "أعد JSON فقط بهذا الشكل بدون أي نص آخر:\n"
        '{"title": "عنوان قصير جذاب", "lines": [{"who": "younis", "text": "..."}, {"who": "farida", "text": "..."}], '
        f'"actions": [{config.SCENES} أوصاف بالإنجليزية، كل وصف جملة قصيرة عن حركة الطفلين وتنقلهما في المكان في كل لقطة], '
        '"description": "وصف يوتيوب قصير بالعربية", "tags": ["كلمة1", "كلمة2", "كلمة3"]}\n'
        'قيم who هي younis أو farida فقط.'
    )

def _ask_gemini(history_titles, location):
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing")
    last = None
    for model in config.GEMINI_TEXT_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model.strip()}:generateContent"
        body = {"contents": [{"parts": [{"text": _prompt(history_titles, location)}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9}}
        try:
            r = request_retry("POST", url, json=body, timeout=90, headers={"x-goog-api-key": config.GEMINI_API_KEY})
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
            data = json.loads(text)
            lines = [{"who": l["who"] if l["who"] in ("younis", "farida") else "younis", "text": l["text"].strip()}
                     for l in data["lines"] if l.get("text", "").strip()]
            words = sum(len(l["text"].split()) for l in lines)
            assert data["title"] and 4 <= len(lines) <= 10 and 15 <= words <= 70, f"bad shape ({len(lines)} lines, {words} words)"
            data["lines"] = lines
            return data
        except Exception as e:
            last = e
            log(f"text model {model} failed: {str(e)[:200]}")
    raise RuntimeError(f"all text models failed: {last}")

def make_episode(history, location):
    titles = [h.get("title", "") for h in history]
    gemini_error = ""
    ep = None
    try:
        candidate = _ask_gemini(titles, location)
        # لا نقبل عنواناً مكرراً أو موضوعاً سبق استخدامه؛ نلجأ إلى فكرة آمنة مختلفة.
        candidate_topics = _candidate_topics(candidate)
        used_topics = _history_topics(history[-60:])
        inferred_topic = _infer_topic(candidate.get("title", ""))
        if (_is_recent_duplicate(candidate.get("title", ""), inferred_topic or None, history)
                or bool(candidate_topics & used_topics)
                or _is_content_duplicate(candidate, history)):
            repeated = sorted(candidate_topics & used_topics)
            raise RuntimeError(
                "Gemini generated a recently used or closely related topic"
                + (f": {', '.join(repeated)}" if repeated else "")
            )
        if candidate_topics:
            candidate["topic"] = inferred_topic if inferred_topic in candidate_topics else sorted(candidate_topics)[0]
        candidate["source"] = "gemini"
        ep = candidate
    except Exception as e:
        log(f"Gemini idea rejected/failed; using a unique fallback idea: {e}")
        gemini_error = str(e)[:300]

    if ep is None:
        used_topics = _history_topics(history[-60:])
        pool = [b for b in FALLBACK_BANK
                if b["location"] == location and b["topic"] not in used_topics
                and not _is_recent_duplicate(b["title"], b["topic"], history)]
        # لا نكرر الموضوعات عند نفاد بنك الموقع؛ نوقف الحلقة بدلاً من نشر محتوى مكرر.
        if not pool:
            raise RuntimeError(
                f"No unused fallback ideas remain for location={location}; refusing to generate a duplicate episode. "
                "Add new ideas or restore Gemini availability."
            )
        ep = dict(pool[0])
        ep["lines"] = [dict(x) for x in pool[0]["lines"]]
        ep["actions"] = list(pool[0]["actions"])
        ep["description"] = ep["title"] + " - حلقة جديدة من " + config.CHANNEL_NAME_AR
        ep["tags"] = ["أطفال", "يونس وفريدة", "كرتون", "عالم يونس وفريدة"]
        ep["source"] = "fallback_bank"
    ep["gemini_error"] = gemini_error
    ep["location"] = location
    ep["narration"] = " ".join(l["text"] for l in ep["lines"])
    actions = list(ep.get("actions") or [])
    while len(actions) < config.SCENES:
        actions.append(actions[-1] if actions else "the kids move naturally and talk to each other")
    cams = [DEFAULT_CAMERAS[i % len(DEFAULT_CAMERAS)] for i in range(config.SCENES)]
    if config.SCENES >= 2:
        cams[-1] = DEFAULT_CAMERAS[-1]
    ep["cameras"] = cams
    ep["motion"] = [f"{CHARACTERS}. Location: {LOCATIONS[location]}. Shot: {cams[i]}. Action: {actions[i]}. {WIDE_MOTION_LOCK}"
                    for i in range(config.SCENES)]
    return ep


SOLO = {
    "younis": "Younis (little boy, curly dark hair, blue denim overalls with the name Younis, yellow t-shirt)",
    "farida": "Farida (little girl, two dark braids, coral overalls with the name Farida, purple t-shirt)",
}
SPEECH_CAMERAS = [
    "medium close-up, slow push-in",
    "close-up on the face, very slight handheld sway",
    "medium shot from a slightly low angle",
    "medium close-up, the camera drifts gently sideways",
]

def shot_prompt(ep, shot):
    """وصف لقطة واحدة: واسعة بالاثنين، أو متحدث واحد بكاميرا قريبة تتغير بين اللقطات."""
    loc = LOCATIONS[ep["location"]]
    acts = ep.get("actions") or ["the kids move naturally and talk to each other"]
    # اربط كل جملة حوار بالفعل المناسب بدلاً من تكرار لقطة وجه ثابتة.
    action_index = min(len(acts) - 1, round(shot["i"] * (len(acts) - 1) / max(1, config.SCENES - 1)))
    act = acts[action_index]
    if shot["kind"] == "wide":
        return (f"{CHARACTERS}. Location: {loc}. Shot: {shot['camera']}. "
                f"Physical action: {act}. Interaction focus: make the two children visibly notice, "
                f"respond to and complete one shared action together. {WIDE_MOTION_LOCK}")
    cam = SPEECH_CAMERAS[shot["i"] % len(SPEECH_CAMERAS)]
    shot["camera"] = cam
    character = SOLO[shot["who"]]
    return (f"{character}, 3D animated film, exact same identity and outfit as the reference. "
            f"Location: {loc}. The named speaker performs only their own visible part of this story action "
            f"while speaking: {act}. Shot: {cam}. {SOLO_MOTION_LOCK} "
            f"Synchronize natural mouth movement to the supplied dialogue audio.")
