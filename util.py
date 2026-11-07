import json, random, subprocess, time
import requests

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def run(cmd, check=True, timeout=600):
    log("RUN: " + " ".join(str(c) for c in cmd)[:300])
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {r.stderr[-1500:]}")
    return r

def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path], check=False)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0

def has_audio(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=codec_type", "-of", "csv=p=0", path], check=False)
    return "audio" in r.stdout

def has_video(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
             "stream=codec_type", "-of", "csv=p=0", path], check=False)
    return "video" in r.stdout

def try_chain(name, candidates):
    """candidates: list of (label, callable). يرجع أول نتيجة ناجحة، ويسجل سبب كل فشل."""
    errors = []
    for label, fn in candidates:
        try:
            log(f"[{name}] trying {label}")
            result = fn()
            if result:
                log(f"[{name}] OK with {label}")
                return result, label, errors
            errors.append(f"{label}: empty result")
        except Exception as e:
            msg = f"{label}: {type(e).__name__}: {str(e)[:300]}"
            log(f"[{name}] FAILED {msg}")
            errors.append(msg)
    return None, None, errors

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def request_retry(method, url, tries=3, backoff=5, **kw):
    """طلب HTTP مع إعادة محاولة عند 429/5xx وأخطاء الشبكة (تباعد متزايد)."""
    last_exc, r = None, None
    for a in range(tries):
        try:
            r = requests.request(method, url, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and a < tries - 1:
                wait = backoff * (2 ** a) + random.random()
                log(f"HTTP {r.status_code} from {url.split('?')[0][-70:]}; retry in {wait:.0f}s")
                time.sleep(wait)
                continue
            return r
        except requests.RequestException as e:
            last_exc = e
            if a < tries - 1:
                time.sleep(backoff * (2 ** a))
    if r is not None:
        return r
    raise last_exc
