"""خط الإنتاج اليومي: فكرة وحوار -> أصوات أطفال -> لقطات (واسعة / متحدث) -> فيديو -> تجميع -> تسليم.
أول حلقة في البيت، والتالية في الغابة، وهكذا. لا شيء يُرفع لليوتيوب إلا لو فعّلت أسراره."""
import datetime, math, os, shutil, sys, tempfile
import requests
from PIL import Image
import config, compose, text_gen, keyframes, deliver, consistency, motion_audit
import voice_providers as voice_mod
import video_providers as video_mod
from util import log, run, try_chain, load_json, save_json, duration, has_video, has_audio

SCORES = []   # درجات تشابه الألوان التشخيصية (ليست هوية وجه)
MOTION_SCORES = []  # نشاط الحركة البصرية (لا يثبت حركة الجسم)
DEGRADED_SHOTS = []  # لقطات احتياطية محلية؛ تُوسم الحلقة للمراجعة


class LocationFallback(RuntimeError):
    """Raised when a forest scene cannot be rendered without using a playroom crop."""
    pass


# ------------------------------------------------------------------ الإعداد
def fetch_character(work):
    local = next((p for p in ("character.jpg", "assets/character.jpg") if os.path.exists(p)), None)
    path = os.path.join(work, "character.jpg")
    if local:
        shutil.copy(local, path)
    else:
        urls = [u for u in (config.CHARACTER_IMAGE_URL, config.CHARACTER_IMAGE_BACKUP_URL) if u]
        if not urls:
            raise RuntimeError("no character image: upload character.jpg to the repository root")
        errors = []
        for url in urls:
            try:
                r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                open(path, "wb").write(r.content)
                break
            except Exception as e:
                errors.append(f"{url}: {e}")
        else:
            raise RuntimeError("could not download character image: " + "; ".join(errors))
    Image.open(path).verify()
    return path


def pick_location(history):
    if config.LOCATION_OVERRIDE in ("home", "forest"):
        return config.LOCATION_OVERRIDE
    last = history[-1].get("location") if history else None
    if last in ("home", "forest"):
        return "forest" if last == "home" else "home"       # تناوب: يوم بيت ويوم غابة
    return "home" if datetime.date.today().toordinal() % 2 == 0 else "forest"


# ------------------------------------------------------------------ مزودو الفيديو
def _checked(fn, canvas, label, min_sim=None):
    """يتحقق من سلامة ملف الفيديو؛ ودرجة الألوان تشخيصية فقط وليست حكماً على هوية الوجه."""
    def run_it():
        res = fn()
        if not res or not os.path.isfile(res) or not has_video(res):
            raise RuntimeError(f"{label}: provider returned no valid video file")
        d = duration(res)
        if d < 1.0:
            raise RuntimeError(f"{label}: video is too short ({d:.2f}s)")
        try:
            sc = consistency.clip_score(res, canvas)
            SCORES.append({"provider": label, "score": round(sc, 3),
                           "meaning": "color-histogram diagnostic only; not face identity"})
            log(f"[visual diagnostic] {label}: color similarity {sc:.2f} (not an identity score)")
        except Exception as e:
            SCORES.append({"provider": label, "score": None, "diagnostic_error": str(e)[:160]})
            log(f"[visual diagnostic] {label}: unavailable ({str(e)[:160]}); video kept after technical validation")
        try:
            motion = motion_audit.analyze_clip(res)
            MOTION_SCORES.append({"provider": label, **motion})
            log(f"[motion diagnostic] {label}: {motion['status']} "
                f"(mean flow={motion['mean_flow_px']:.3f}px; camera and subject motion are not separated)")
        except Exception as e:
            MOTION_SCORES.append({"provider": label, "status": "unavailable",
                                  "diagnostic_error": str(e)[:160]})
            log(f"[motion diagnostic] {label}: unavailable ({str(e)[:160]}); video kept after technical validation")
        return res
    return run_it


def gen_clip(canvas, prompt, seconds, out, idx, dead, audio=None):
    """يجرّب بالترتيب: فيديو بالكلام (لو معنا صوت) ثم Veo ثم المساحات المجانية ثم التحريك المحلي."""
    cands = []
    if audio and config.SPEECH_ENABLED:
        for sp in config.SPEECH_SPACES:
            if sp in dead:
                continue
            def fn(sp=sp):
                try:
                    return _checked(lambda: video_mod.hf_space_clip(
                        sp, canvas, prompt, math.ceil(seconds), out, audio_path=audio),
                        canvas, f"speech:{sp}", config.SIM_MIN_SPEECH)()
                except Exception as e:
                    if "identity drift" not in str(e):
                        dead.add(sp)
                    msg = str(e).lower()
                    if "zerogpu" in msg and ("quota" in msg or "runs limit" in msg):
                        dead.update(config.VIDEO_SPACES)
                        dead.update(config.SPEECH_SPACES)
                        log("[quota guard] Hugging Face ZeroGPU quota exhausted; skipping all remaining HF Spaces")
                    raise
            cands.append((f"speech:{sp}", fn))
    for order in config.VIDEO_ORDER:
        order = order.strip()
        if order == "veo" and config.VEO_ENABLED:
            cands.append(("veo", _checked(lambda: video_mod.veo_clip(canvas, prompt, seconds, out), canvas, "veo")))
        elif order == "hf_spaces":
            for sp in config.VIDEO_SPACES:
                if sp in dead:
                    continue
                # إذا كان الفيديو صالحاً تقنياً لكن فشل فحص الثبات، أعد التوليد
                # من نفس الصورة المرجعية قبل الانتقال لمزود مختلف.
                for attempt in range(config.VIDEO_RETRIES_PER_SPACE):
                    def fn2(sp=sp, attempt=attempt):
                        if sp in dead:
                            raise RuntimeError(f"{sp}: skipped after an endpoint failure")
                        retry_prompt = prompt
                        if attempt:
                            retry_prompt += (
                                " RETRY: prioritize exact character identity from the input image. "
                                "Keep both faces, hair, clothing colors and body proportions unchanged. "
                                "Use clear simple body actions with moderate motion; avoid fast turns, "
                                "occlusion, camera cuts and dramatic camera movement."
                            )
                        try:
                            return _checked(lambda: video_mod.hf_space_clip(
                                sp, canvas, retry_prompt, math.ceil(seconds), out),
                                canvas, f"space:{sp}:attempt{attempt + 1}")()
                        except Exception as e:
                            if "identity drift" not in str(e):
                                dead.add(sp)  # خطأ endpoint حقيقي: لا تكرر طلباً لنفس المساحة
                            msg = str(e).lower()
                            if "zerogpu" in msg and ("quota" in msg or "runs limit" in msg):
                                dead.update(config.VIDEO_SPACES)
                                dead.update(config.SPEECH_SPACES)
                                log("[quota guard] Hugging Face ZeroGPU quota exhausted; skipping all remaining HF Spaces")
                            raise
                    cands.append((f"space:{sp}:attempt{attempt + 1}", fn2))
        elif order == "local_motion":
            if config.ALLOW_CAMERA_ONLY_FALLBACK:
                cands.append(("local_motion", lambda: video_mod.local_motion_clip(canvas, seconds, out, variant=idx)))
            else:
                log("[quality gate] skipped local_motion: camera-only fallback is disabled")
    if cands:
        result, label, errors = try_chain(f"video shot {idx + 1}", cands)
        if result:
            return result, label, errors
    else:
        result, label, errors = None, None, [
            f"shot {idx + 1}: all remote video providers skipped or unavailable"
        ]

    # Last-resort continuity path: playable episode, but explicitly degraded.
    # This is camera-only motion, not generated character animation.
    try:
        log(f"[degraded fallback] shot {idx + 1}: local still-image motion; no AI character motion is claimed")
        fallback = video_mod.local_motion_clip(canvas, seconds, out, variant=idx)
        if not fallback or not os.path.isfile(fallback) or not has_video(fallback):
            raise RuntimeError("local fallback returned no valid video")
        if duration(fallback) < 1.0:
            raise RuntimeError("local fallback video is too short")
        DEGRADED_SHOTS.append(idx + 1)
        errors.append(f"shot {idx + 1}: local camera-only fallback used; manual review required")
        return fallback, "local_motion_degraded", errors
    except Exception as exc:
        errors.append(f"shot {idx + 1}: local fallback failed: {type(exc).__name__}: {str(exc)[:180]}")
        raise RuntimeError("all remote video providers and local fallback failed: " + " | ".join(errors[-5:]))


# ------------------------------------------------------------------ اللقطات
def plan_shots(ep, timeline, alen):
    """لقطة لكل جملة حوار: الأولى والأخيرة واسعة بالاثنين، والباقي لقطات قريبة للمتحدث."""
    n = len(timeline)
    bounds = [0.0] + [timeline[i]["start"] for i in range(1, n)] + [alen]
    shots = []
    for i, ln in enumerate(timeline):
        wide = (i == 0 or i == n - 1)
        cam = ep["cameras"][0] if i == 0 else ep["cameras"][-1] if wide else ep["cameras"][min(i, len(ep["cameras"]) - 1)]
        shots.append({"i": i, "who": ln["who"], "text": ln["text"], "start": ln["start"], "end": ln["end"],
                      "dur": max(bounds[i + 1] - bounds[i], 1.5), "kind": "wide" if wide else "speech",
                      "camera": cam})
    return shots


def make_shots(ref_image, ep, shots, audio, work):
    """Prepare every keyframe before spending video-provider quota.

    A forest episode must never silently use a playroom reference crop. If any
    forest keyframe falls back, the caller can rebuild the whole episode at home.
    """
    clips, used, errors, key_used, durs = [], [], [], [], []
    dead = set()
    prepared = []

    # Preflight all scene images first. This prevents wasting Wan GPU calls on
    # an episode that would later contain a mismatched forest/playroom scene.
    for sh in shots:
        i = sh["i"]
        try:
            key, klabel, kerrs = keyframes.make_keyframe(
                i, text_gen.shot_prompt(ep, sh), ref_image, work, ep["location"],
                sh["camera"], sh["kind"], sh["who"]
            )
        except Exception as e:
            if ep["location"] == "forest":
                raise LocationFallback(
                    f"forest keyframe {i + 1} could not be generated: {type(e).__name__}: {e}"
                ) from e
            raise
        errors += kerrs
        if ep["location"] == "forest" and "FALLBACK" in klabel:
            raise LocationFallback(
                f"forest keyframe {i + 1} fell back to a playroom crop; "
                f"refusing a mismatched scene. Provider errors: {' | '.join(kerrs)[:500]}"
            )
        key_used.append(klabel)
        deliver.notify_provider_usage("صورة المشهد", klabel)
        canvas = compose.make_canvas(key, os.path.join(work, f"canvas_{i}.jpg"))
        prepared.append((sh, canvas))

    # Only after all keyframes pass the location check do we spend video quota.
    for sh, canvas in prepared:
        i = sh["i"]
        seg = None
        if sh["kind"] == "speech" and config.SPEECH_ENABLED:
            seg = os.path.join(work, f"seg_{i}.wav")
            run(["ffmpeg", "-y", "-ss", f"{sh['start']:.2f}", "-t",
                 f"{max(sh['end'] - sh['start'], 0.8):.2f}",
                 "-i", audio, "-ar", "16000", "-ac", "1", seg])
        res, label, errs = gen_clip(
            canvas, text_gen.shot_prompt(ep, sh), sh["dur"],
            os.path.join(work, f"shot_{i}.mp4"), i, dead, seg
        )
        errors += errs
        if not res:
            raise RuntimeError(f"all video providers failed for shot {i + 1}")
        clips.append(res)
        used.append(label)
        deliver.notify_provider_usage("الفيديو", label)
        durs.append(sh["dur"])
    return clips, used, errors, key_used, durs


# ------------------------------------------------------------------ التشغيل
def main():
    DEGRADED_SHOTS.clear()
    today = datetime.date.today().strftime("%Y%m%d")
    out_dir = config.OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="ep_")
    report = {"date": today, "errors": []}

    image = fetch_character(work)
    history = load_json(config.HISTORY_FILE, [])
    location = pick_location(history)
    requested_location = location
    report["requested_location"] = requested_location

    # If forest image generation fails, rebuild the entire episode at home.
    # Never combine a forest story with a playroom reference image.
    for location_attempt in range(2):
        ep = text_gen.make_episode(history, location)
        report.update(title=ep["title"], idea_source=ep["source"], location=location,
                      gemini_text_error=ep.get("gemini_error", ""))
        deliver.notify_provider_usage("النص", ep["source"])
        log(f"episode: {ep['title']} ({ep['source']}) | location: {location}")

        res, vlabel, verrs = try_chain("voice", voice_mod.dialogue_candidates(ep["lines"], work))
        report["errors"] += verrs
        if not res:
            raise RuntimeError("all voice providers failed: " + " | ".join(verrs))
        dialogue_wav, timeline = res
        report["voice_provider"] = vlabel
        deliver.notify_provider_usage("الصوت", vlabel)
        old_len = duration(dialogue_wav)
        audio, alen = compose.fit_audio(dialogue_wav, os.path.join(work, "voice_fit.wav"))
        scale = alen / old_len if (old_len > config.MAX_SECONDS and alen < old_len) else 1.0
        for ln in timeline:
            ln["start"] *= scale
            ln["end"] = min(ln["end"] * scale, alen)

        shots = plan_shots(ep, timeline, alen)
        SCORES.clear()
        MOTION_SCORES.clear()
        try:
            clips, used, verrs, key_used, durs = make_shots(image, ep, shots, audio, work)
            report["errors"] += verrs
            break
        except LocationFallback as e:
            if location != "forest" or location_attempt > 0:
                raise
            report["errors"].append(str(e)[:700])
            report["location_fallback"] = (
                "Forest image generation was unavailable; the complete episode was regenerated at home."
            )
            log("[location safety] forest keyframe unavailable; regenerating the full episode at home")
            location = "home"
    else:
        raise RuntimeError("episode generation did not complete after the safe location fallback")

    report["keyframes"] = key_used
    report["video_providers"] = used
    report["consistency_scores"] = SCORES
    report["motion_diagnostics"] = MOTION_SCORES
    report["speech_shots"] = sum(1 for u in used if u.startswith("speech:"))
    report["degraded_shots"] = sorted(set(DEGRADED_SHOTS))
    report["degraded_fallback_used"] = bool(DEGRADED_SHOTS)
    # No automatic face-identity verifier is configured. Every episode needs human visual review.
    report["quality"] = "degraded" if DEGRADED_SHOTS else "review_required"

    final = os.path.join(out_dir, f"episode_{today}.mp4")
    compose.build_final(clips, audio, timeline, work, final, durations=durs)

    d = duration(final)
    assert has_video(final) and has_audio(final), "final video missing video or audio stream"
    assert config.MIN_SECONDS - 0.8 <= d <= config.MAX_SECONDS + 0.8, f"bad duration {d:.1f}s"
    report["duration_seconds"] = round(d, 1)

    meta = {"title": ep["title"], "description": ep["description"], "tags": ep.get("tags", []),
            "narration": ep["narration"], "location": location, "file": os.path.basename(final)}
    save_json(os.path.join(out_dir, f"episode_{today}.json"), meta)
    report["delivery"] = deliver.deliver_all(final, meta, report)
    save_json(os.path.join(out_dir, "report.json"), report)

    history.append({"date": today, "title": ep["title"], "location": location,
                    "topic": ep.get("topic", ""), "narration": ep.get("narration", ""),
                    "lines": ep.get("lines", []), "actions": ep.get("actions", [])})
    save_json(config.HISTORY_FILE, history[-200:])

    place = "في البيت" if location == "home" else "في الغابة"
    summary = [f"## حلقة {today}: {ep['title']} ({place})",
               f"- المدة: {d:.1f} ثانية", f"- الأصوات: {vlabel}",
               f"- اللقطات ({len(used)}): {', '.join(used)}",
               f"- لقطات بحركة شفايف متزامنة مع الصوت: {report['speech_shots']}",
               f"- صور اللقطات: {', '.join(key_used)}",
               f"- مصدر الفكرة: {ep['source']}"]
    for k, v in report["delivery"].items():
        summary.append(f"- التسليم ({k}): {v}")
    if ep.get("gemini_error"):
        summary.append(f"- سبب فشل Gemini للنص: {ep['gemini_error']}")
    if report.get("location_fallback"):
        summary.append("- **تنبيه:** تعذّر إنشاء صور الغابة؛ أُعيد إنشاء الحلقة كاملة في البيت لتجنّب خلفية غير مطابقة.")
    summary.append("- **مراجعة الجودة:** مطلوبة بصرياً؛ درجات الألوان ليست فحصاً لهوية الوجوه.")
    if DEGRADED_SHOTS:
        summary.append(f"- **تنبيه جودة مهم:** اللقطات {', '.join(map(str, sorted(set(DEGRADED_SHOTS))))} استخدمت تحريكاً محلياً لصورة ثابتة بعد تعذر مزودي الفيديو؛ حركة الشخصيات غير مولّدة بالذكاء الاصطناعي في هذه اللقطات. لا تنشر الحلقة قبل مراجعتها.")
    if any("FALLBACK" in k for k in key_used):
        summary.append("- **تنبيه:** صورة الغابة فشل توليدها فاستُخدمت صور غرفة اللعب بدلاً منها.")
    if config.SPEECH_ENABLED and report["speech_shots"] == 0:
        summary.append("- **تنبيه:** مساحة الفيديو بالكلام لم تعمل اليوم، فالشفايف غير متزامنة مع الصوت.")
    if report["quality"] == "degraded":
        summary.append("- **تنبيه:** كل اللقطات خرجت بالتحريك المحلي لأن مزودي الفيديو المجانيين فشلوا اليوم. "
                       "راجع الأخطاء في report.json قبل النشر.")
    text = "\n".join(summary)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(text + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL: {e}")
        sys.exit(1)
