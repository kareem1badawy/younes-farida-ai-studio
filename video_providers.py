"""مزودو الفيديو المجانيون. كل مزود يحوّل صورة الشخصيات + وصف حركة إلى مقطع قصير."""
import base64, os, re, time
import requests
import config
from util import log, run, duration, has_video, request_retry

# ---------------------------------------------------------------
# 1) مساحات Hugging Face المجانية (Wan / LTX / ...) عبر gradio_client
# ---------------------------------------------------------------
_SKIP_ENDPOINTS = ("reset", "clear", "lambda", "flag", "example", "load", "unload", "random")

def _client(space):
    from gradio_client import Client
    token = config.HF_TOKEN or None
    try:
        return Client(space, token=token, verbose=False)
    except TypeError:               # نسخ قديمة
        return Client(space, hf_token=token, verbose=False)

def _find_video(obj):
    """يبحث داخل أي نتيجة عن مسار ملف فيديو."""
    if isinstance(obj, str):
        if obj.lower().endswith((".mp4", ".webm", ".mov")) and os.path.exists(obj):
            return obj
        return None
    if isinstance(obj, dict):
        for key in ("video", "path", "value", "name"):
            if key in obj:
                found = _find_video(obj[key])
                if found:
                    return found
        for v in obj.values():
            found = _find_video(v)
            if found:
                return found
        return None
    if isinstance(obj, (list, tuple)):
        for v in obj:
            found = _find_video(v)
            if found:
                return found
    return None

def _find_video_url(obj):
    """بعض المساحات (مثل Wan2.2-S2V) ترجع رابط فيديو نصياً: نحمّله."""
    m = re.search(r"https?://[^\s\"'\\]+?\.mp4[^\s\"'\\]*", str(obj))
    return m.group(0) if m else None

def _plan_calls(client, image_path, prompt, seconds, audio_path=None):
    """يبني قائمة محاولات (api_name, kwargs) بقراءة توقيع الواجهة تلقائياً،
    فلا نعتمد على أسماء بارامترات ثابتة قد تتغير."""
    from gradio_client import handle_file
    info = client.view_api(return_format="dict", print_info=False)
    plans = []
    for api_name, ep in (info.get("named_endpoints") or {}).items():
        if any(s in api_name.lower() for s in _SKIP_ENDPOINTS):
            continue
        params = ep.get("parameters", [])
        comps = [str(p.get("component", "")).lower() for p in params]
        if not any(c in ("image", "file", "uploadbutton") for c in comps):
            continue
        if any(c in ("video",) for c in comps):       # يطلب فيديو مدخل: ليس مناسباً
            continue
        if audio_path and "audio" not in comps:      # نحتاج نقطة تقبل الصوت
            continue
        kwargs, image_used, prompt_used, audio_used, ok = {}, False, False, False, True
        for p in params:
            name = p.get("parameter_name")
            comp = str(p.get("component", "")).lower()
            label = (str(p.get("label", "")) + " " + str(name)).lower()
            has_default = p.get("parameter_has_default", False)
            default = p.get("parameter_default")
            if comp in ("image", "file", "uploadbutton") and not image_used:
                kwargs[name] = handle_file(image_path); image_used = True
            elif comp == "audio":
                if audio_path and not audio_used:
                    kwargs[name] = handle_file(audio_path); audio_used = True
                else:
                    kwargs[name] = default if has_default else None
            elif comp in ("textbox", "textarea", "text") or "prompt" in label:
                if "negative" in label:
                    kwargs[name] = config.NEGATIVE_PROMPT
                elif not prompt_used:
                    kwargs[name] = prompt; prompt_used = True
                else:
                    kwargs[name] = default if has_default else ""
            elif "duration" in label and comp in ("slider", "number"):
                kwargs[name] = default if has_default and default else seconds
            elif has_default:
                kwargs[name] = default
            elif p.get("example_input") is not None and comp not in ("image", "file"):
                kwargs[name] = p["example_input"]
            else:
                ok = False
        if ok and image_used and (audio_used or not audio_path):
            score = (("generate" in api_name.lower()) + ("video" in api_name.lower()))
            plans.append((score, api_name, kwargs))
    plans.sort(key=lambda t: -t[0])
    return [(a, k) for _, a, k in plans]

def hf_space_clip(space, image_path, prompt, seconds, out_path, audio_path=None):
    client = _client(space)
    plans = _plan_calls(client, image_path, prompt, seconds, audio_path)
    if not plans:
        raise RuntimeError(f"{space}: no usable image-to-video endpoint found")
    last = None
    for api_name, kwargs in plans[:3]:
        try:
            log(f"{space}: calling {api_name}")
            job = client.submit(api_name=api_name, **kwargs)
            result = job.result(timeout=config.SPACE_TIMEOUT_SECONDS)
            src = _find_video(result)
            if not src:
                url = _find_video_url(result)
                if url:
                    src = out_path + ".dl.mp4"
                    dl = request_retry("GET", url, timeout=300)
                    dl.raise_for_status()
                    open(src, "wb").write(dl.content)
            if not src:
                raise RuntimeError("no video file in result")
            run(["ffmpeg", "-y", "-i", src, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-an", out_path])
            if not has_video(out_path) or duration(out_path) < 1.0:
                raise RuntimeError("video too short or invalid")
            return out_path
        except Exception as e:
            last = e
            log(f"{space} {api_name} failed: {str(e)[:200]}")
    raise RuntimeError(f"{space}: {last}")

# ---------------------------------------------------------------
# 2) حل أخير محلي: تحريك الصورة بـ FFmpeg (حركة خفيفة، ليس فيديو حقيقياً)
# ---------------------------------------------------------------
def local_motion_clip(canvas_path, seconds, out_path, variant=0):
    frames = int(seconds * config.FPS)
    # حركات مختلفة لكل مشهد حتى لا تتكرر
    motions = [
        "z='1.06+0.04*sin(on/9)':x='iw/2-(iw/zoom/2)+40*sin(on/11)':y='ih/2-(ih/zoom/2)+25*cos(on/8)'",
        "z='1.10-0.03*sin(on/10)':x='iw/2-(iw/zoom/2)-45*sin(on/12)':y='ih/2-(ih/zoom/2)+30*sin(on/7)'",
        "z='1.05+0.05*abs(sin(on/14))':x='iw/2-(iw/zoom/2)+30*cos(on/9)':y='ih/2-(ih/zoom/2)-30*sin(on/10)'",
    ]
    m = motions[variant % len(motions)]
    vf = (f"scale=1620:2880,zoompan={m}:d=1:s={config.WIDTH}x{config.HEIGHT}:fps={config.FPS},"
          f"format=yuv420p")
    run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(config.FPS), "-i", canvas_path,
         "-frames:v", str(frames), "-vf", vf, "-c:v", "libx264", "-an", out_path])
    if not has_video(out_path):
        raise RuntimeError("local motion failed")
    return out_path


# ---------------------------------------------------------------
# 0) Veo عبر Gemini API (مدفوع، أعلى جودة؛ مُعطّل ما لم يُفعَّل صراحةً)
# ---------------------------------------------------------------
_veo_seconds_used = 0

def veo_clip(image_path, prompt, seconds, out_path):
    global _veo_seconds_used
    if not config.VEO_ENABLED:
        raise RuntimeError("Veo disabled (set VEO_ENABLED=1 to use the paid Veo API)")
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing")
    secs = 8 if seconds > 6 else (6 if seconds > 4 else 4)
    if _veo_seconds_used + secs > config.VEO_MAX_SECONDS_PER_RUN:
        raise RuntimeError(f"Veo per-run cap reached ({config.VEO_MAX_SECONDS_PER_RUN}s)")
    img_b64 = base64.b64encode(open(image_path, "rb").read()).decode()
    headers = {"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"}
    base = "https://generativelanguage.googleapis.com/v1beta"
    last = None
    for model in config.VEO_MODELS:
        model = model.strip()
        body = {"instances": [{"prompt": prompt,
                               "image": {"bytesBase64Encoded": img_b64, "mimeType": "image/jpeg"}}],
                "parameters": {"aspectRatio": "9:16", "durationSeconds": secs,
                               "resolution": config.VEO_RESOLUTION}}
        try:
            r = request_retry("POST", f"{base}/models/{model}:predictLongRunning", json=body,
                              headers=headers, timeout=120)
            if r.status_code != 200:
                raise RuntimeError(f"{model} HTTP {r.status_code}: {r.text[:250]}")
            op = r.json()["name"]
            _veo_seconds_used += secs            # نحسبها فور بدء التوليد (الفاتورة تبدأ هنا)
            deadline = time.time() + 600
            while time.time() < deadline:
                time.sleep(10)
                pr = requests.get(f"{base}/{op}", headers=headers, timeout=60)
                pr.raise_for_status()
                j = pr.json()
                if j.get("done"):
                    if "error" in j:
                        raise RuntimeError(f"operation error: {str(j['error'])[:250]}")
                    resp = j["response"]["generateVideoResponse"]
                    samples = resp.get("generatedSamples")
                    if not samples:
                        raise RuntimeError(f"no samples (filtered?): {str(resp)[:250]}")
                    uri = samples[0]["video"]["uri"]
                    dl = requests.get(uri, headers={"x-goog-api-key": config.GEMINI_API_KEY},
                                      timeout=300, allow_redirects=True)
                    dl.raise_for_status()
                    raw = out_path + ".raw.mp4"
                    open(raw, "wb").write(dl.content)
                    run(["ffmpeg", "-y", "-i", raw, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                         "-an", out_path])
                    if not has_video(out_path) or duration(out_path) < 1.0:
                        raise RuntimeError("video invalid")
                    return out_path
            raise RuntimeError("Veo timeout")
        except Exception as e:
            last = e
            log(f"veo {model} failed: {str(e)[:250]}")
    raise RuntimeError(f"all Veo models failed: {last}")
