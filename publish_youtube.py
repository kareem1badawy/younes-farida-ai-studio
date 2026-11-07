"""Best-effort YouTube upload: failures never affect episode production or email delivery."""
import glob
import json
import os

import deliver

videos = sorted(glob.glob("output/episode_*.mp4"))
metas = sorted(glob.glob("output/episode_*.json"))
if len(videos) != 1 or len(metas) != 1:
    print(f"[youtube] SKIPPED: expected exactly one video and metadata file; found {len(videos)} video(s), {len(metas)} metadata file(s).")
    raise SystemExit(0)

with open(metas[0], encoding="utf-8") as f:
    meta = json.load(f)
with open("output/report.json", encoding="utf-8") as f:
    report = json.load(f)

# Automated uploads are always Private. Missing credentials or upload errors are non-fatal.
required = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
missing = [name for name in required if not os.getenv(name, "").strip()]
if missing:
    status = "تعذّر الرفع لأن مفاتيح YouTube غير مكتملة. لم يتأثر إنتاج الحلقة أو رسالة الفيديو الأساسية."
    print(f"[youtube] SKIPPED: {status}")
    deliver.send_youtube_status_email(meta, status)
    raise SystemExit(0)

report["quality"] = "review_required"
try:
    result = deliver.upload_youtube(videos[0], meta, report)
    print(result)
    deliver.send_youtube_status_email(meta, result)
except Exception as exc:
    status = f"فشل الرفع: {type(exc).__name__}: {str(exc)[:250]}"
    print(f"[youtube] WARNING: {status}. The episode and email delivery remain successful.")
    deliver.send_youtube_status_email(meta, status)
    raise SystemExit(0)
