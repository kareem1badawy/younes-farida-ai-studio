"""Upload the generated episode to YouTube as Private and report the real outcome.

The uploader runs in its own GitHub Actions job. A failure here must never cancel
or roll back the already completed episode build.
"""
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

import deliver

STATUS_FILE = "output/youtube_upload_status.json"
VIDEO_URL_RE = re.compile(r"https://youtu\.be/([A-Za-z0-9_-]{6,20})")


def write_status(state, message, video_id=None, url=None):
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    payload = {
        "status": state,
        "message": message,
        "privacy": "private" if state == "success" else None,
        "video_id": video_id,
        "url": url,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    temp = STATUS_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(temp, STATUS_FILE)
    print(f"[youtube] STATUS={state.upper()}: {message}", flush=True)


def notify(meta, message):
    try:
        deliver.send_youtube_status_email(meta or {"title": "حلقة يونس وفريدة"}, message)
    except Exception as exc:
        # Notification failure must not hide the actual upload outcome.
        print(f"[youtube] notification failed: {type(exc).__name__}", flush=True)


def safe_error(exc):
    message = str(exc)
    for key in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        secret = os.getenv(key, "")
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return f"{type(exc).__name__}: {message[:220]}"


def main():
    meta = None
    try:
        videos = sorted(glob.glob("output/episode_*.mp4"))
        metas = sorted(glob.glob("output/episode_*.json"))
        if len(videos) != 1 or len(metas) != 1:
            message = (
                "تعذّر الرفع: يجب وجود فيديو واحد وملف بيانات واحد بالضبط؛ "
                f"الموجود {len(videos)} فيديو و{len(metas)} ملف بيانات."
            )
            write_status("failed", message)
            notify(meta, message)
            return 1

        with open(metas[0], encoding="utf-8") as f:
            meta = json.load(f)
        with open("output/report.json", encoding="utf-8") as f:
            report = json.load(f)

        required = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
        missing = [name for name in required if not os.getenv(name, "").strip()]
        if missing:
            message = "تخطي الرفع: أسرار YouTube التالية غير مضبوطة في GitHub: " + ", ".join(missing)
            write_status("skipped", message)
            notify(meta, message)
            return 1

        # Owner-review uploads only. This explicitly permits Private uploads even
        # when the episode is marked review_required/degraded; public is never used.
        report["quality"] = "review_required"
        result = deliver.upload_youtube(videos[0], meta, report)
        match = VIDEO_URL_RE.search(result or "")
        if not (result and "uploaded (private)" in result.lower() and match):
            state = "skipped" if (result or "").lower().startswith("skipped") else "failed"
            message = "لم يؤكد YouTube اكتمال الرفع: " + str(result or "لا توجد نتيجة")[:240]
            write_status(state, message)
            notify(meta, message)
            return 1

        video_id = match.group(1)
        url = f"https://youtu.be/{video_id}"
        message = f"تم رفع الفيديو بنجاح إلى YouTube بوضع Private (خاص): {url}"
        write_status("success", message, video_id=video_id, url=url)
        notify(meta, message)
        return 0

    except Exception as exc:
        message = "فشل رفع YouTube: " + safe_error(exc)
        write_status("failed", message)
        notify(meta, message)
        return 1


if __name__ == "__main__":
    sys.exit(main())
