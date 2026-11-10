"""تسليم الحلقة بعد اكتمالها: إيميل (الأسهل) ورفع مباشر على يوتيوب (اختياري).
كل وسيلة تعمل فقط لو أسرارها موجودة. فشل التسليم لا يُفشل التشغيل (الفيديو محفوظ في Artifacts دائماً)."""
import os, smtplib, ssl
from email.message import EmailMessage
from util import log, run

MAX_MAIL_BYTES = 20 * 1024 * 1024

_notified_provider_events = set()

def notify_provider_usage(category, provider):
    """Send one lightweight email as soon as a provider successfully completes work."""
    key = (str(category), str(provider))
    if key in _notified_provider_events:
        return "skipped (already notified)"
    _notified_provider_events.add(key)
    user = os.getenv("EMAIL_USER", "").strip()
    pw = os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "")
    to = os.getenv("EMAIL_TO", "").strip() or user
    if not (user and pw):
        log(f"[provider notice] {category}: {provider} (email credentials not configured)")
        return "skipped (email credentials not configured)"
    run_url = (f"{os.getenv('GITHUB_SERVER_URL', 'https://github.com')}/"
               f"{os.getenv('GITHUB_REPOSITORY', '')}/actions/runs/{os.getenv('GITHUB_RUN_ID', '')}")
    msg = EmailMessage()
    msg["Subject"] = f"تنبيه استخدام خدمة: {category}"
    msg["From"] = user
    msg["To"] = to
    msg.set_content(
        f"اكتمل استخدام الخدمة التالية بنجاح:\n"
        f"التصنيف: {category}\n"
        f"المزوّد: {provider}\n"
        f"وقت الإشعار: {__import__('datetime').datetime.now().astimezone().isoformat(timespec='seconds')}\n\n"
        f"رابط تشغيل الحلقة وسجل الاستخدام: {run_url}\n"
        "هذا إشعار بالاستخدام فقط، وليس تأكيداً على أن الخدمة مجانية أو أن لها رصيداً متاحاً."
    )
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as server:
            server.login(user, pw)
            server.send_message(msg)
        log(f"[provider notice] sent: {category} / {provider}")
        return f"sent to {to}"
    except Exception as exc:
        log(f"[provider notice] failed: {type(exc).__name__}: {str(exc)[:180]}")
        return f"failed: {type(exc).__name__}"


def _shrink(video, work_dir):
    out = os.path.join(work_dir, "mail_small.mp4")
    run(["ffmpeg", "-y", "-i", video, "-vf", "scale=720:-2", "-c:v", "libx264", "-crf", "28",
         "-preset", "veryfast", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", out])
    return out

def build_completion_email_body(meta, report, warn=""):
    """Build the review email body with real line breaks; kept pure for offline tests."""
    run_number = os.getenv("GITHUB_RUN_NUMBER", "")
    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"
    return (
        f"العنوان: {meta['title']}\n\nالوصف:\n{meta['description']}\n\n"
        f"الوسوم: {', '.join(meta.get('tags', []))}\n\nالتعليق الصوتي:\n{meta['narration']}\n"
        f"{warn}\nالخدمات المستخدمة بنجاح:\n"
        f"- النص: {report.get('idea_source', 'غير محدد')}\n"
        f"- الصوت: {report.get('voice_provider', 'غير محدد')}\n"
        f"- صور المشاهد: {', '.join(report.get('keyframes', [])) or 'غير محدد'}\n"
        f"- الفيديو: {', '.join(report.get('video_providers', [])) or 'غير محدد'}\n\n"
        f"ستتم محاولة رفع الفيديو تلقائياً إلى YouTube بوضع Private بعد نجاح الإنتاج إذا كانت بيانات YouTube مضبوطة. ستصلك رسالة متابعة بنتيجة الرفع ورابط الفيديو عند نجاحه. الفيديو لن يكون عاماً تلقائياً. ويمكنك أيضاً تنزيل نسخة MP4 من Artifact باسم episode-{run_number} في تشغيل GitHub Actions:\n"
        f"{run_url}\n"
    )


def send_email(video, meta, report):
    user = os.getenv("EMAIL_USER", "").strip()
    pw = os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "")
    to = os.getenv("EMAIL_TO", "").strip() or user
    if not (user and pw):
        return "skipped (EMAIL_USER / EMAIL_APP_PASSWORD not set)"
    path = video
    if os.path.getsize(path) > MAX_MAIL_BYTES:
        path = _shrink(video, os.path.dirname(video) or ".")
    msg = EmailMessage()
    msg["Subject"] = f"حلقة جديدة: {meta['title']}"
    msg["From"] = user
    msg["To"] = to
    warn = ""
    if report.get("quality") == "degraded":
        warn = "\n⚠️ تنبيه: مزودو الفيديو المجانيون فشلوا اليوم وخرجت الحلقة بتحريك محلي بسيط. راجع قبل النشر.\n"
    msg.set_content(build_completion_email_body(meta, report, warn))
    with open(path, "rb") as f:
        msg.add_attachment(f.read(), maintype="video", subtype="mp4", filename=os.path.basename(video))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=120) as s:
        s.login(user, pw)
        s.send_message(msg)
    return f"sent to {to}"


def send_youtube_status_email(meta, status):
    """Send a non-fatal follow-up email with the YouTube upload result."""
    user = os.getenv("EMAIL_USER", "").strip()
    pw = os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "")
    to = os.getenv("EMAIL_TO", "").strip() or user
    if not (user and pw):
        log("[youtube notice] skipped (email credentials not configured)")
        return "skipped (email credentials not configured)"
    msg = EmailMessage()
    msg["Subject"] = "نتيجة رفع الحلقة: " + meta.get("title", "حلقة جديدة")
    msg["From"] = user
    msg["To"] = to
    msg.set_content("عنوان الحلقة: " + meta.get("title", "غير محدد") + "\n\nنتيجة YouTube: " + status + "\n\nإذا نجح الرفع فالفيديو مضبوط على Private (خاص)، ويمكنك فتح الرابط ومراجعته ثم تغيير الخصوصية أو حذفه بنفسك من YouTube Studio.\n")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as server:
            server.login(user, pw)
            server.send_message(msg)
        log("[youtube notice] sent to " + to)
        return "sent to " + to
    except Exception as exc:
        log("[youtube notice] failed: " + type(exc).__name__ + ": " + str(exc)[:180])
        return "failed: " + type(exc).__name__


def upload_youtube(video, meta, report):
    cid, sec, tok = (os.getenv(k, "").strip() for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    if not (cid and sec and tok):
        return "skipped (YT_* secrets not set)"
    if report.get("quality") != "review_required" and report.get("quality") != "verified":
        return "skipped (quality status is not approved)"
    if report.get("quality") in ("review_required", "degraded") and os.getenv("YT_ALLOW_PRIVATE_UPLOAD") != "1":
        return "skipped (private upload not enabled; set YT_ALLOW_PRIVATE_UPLOAD=1 to upload privately for owner review)"
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=tok, client_id=cid, client_secret=sec,
                        token_uri="https://oauth2.googleapis.com/token",
                        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    # Safety policy: automated uploads must never become public or unlisted.
    privacy = "private"
    yt = build("youtube", "v3", credentials=creds)
    body = {"snippet": {"title": meta["title"][:95],
                        "description": (meta.get("description") or "") + "\n\n#Shorts",
                        "tags": meta.get("tags", []), "categoryId": "27", "defaultLanguage": "ar"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": True}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(video, mimetype="video/mp4", resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return f"uploaded ({privacy}): https://youtu.be/{resp['id']}"

def deliver_all(video, meta, report):
    results = {}
    for name, fn in (("email", send_email), ("youtube", upload_youtube)):
        try:
            results[name] = fn(video, meta, report)
        except Exception as e:
            results[name] = f"FAILED: {type(e).__name__}: {str(e)[:250]}"
        log(f"[deliver] {name}: {results[name]}")
    return results
