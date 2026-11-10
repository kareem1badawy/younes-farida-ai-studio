"""فحص الجاهزية.
  python selftest.py --offline   : يبني فيديو تجريبياً كاملاً بدون إنترنت (ffmpeg + الخط العربي + الترجمة)
  python selftest.py --online    : يفحص المفاتيح ومزودي الصوت ومساحات الفيديو (بدون توليد فيديو كامل)
"""
import os, sys, tempfile
import config, compose
from PIL import Image, ImageDraw
import voice_providers as voice_mod, video_providers as video_mod, motion_audit
from util import run, duration, has_audio, has_video

rows = []
def row(name, ok, note=""):
    rows.append((name, ok, note))
    print(("PASS " if ok else "FAIL ") + name + (f" - {note}" if note else ""), flush=True)

def location_guard_test():
    """A forest keyframe fallback must stop before any video provider is called."""
    import main
    original = main.keyframes.make_keyframe
    def fake_keyframe(*args, **kwargs):
        return "unused.jpg", "reference_crop(FALLBACK: playroom, forest image failed)", ["simulated image quota failure"]
    main.keyframes.make_keyframe = fake_keyframe
    try:
        shot = {"i": 0, "who": "younis", "text": "hello", "start": 0.0, "end": 1.5,
                "dur": 1.5, "kind": "wide", "camera": "wide"}
        try:
            main.make_shots("unused.jpg", {"location": "forest"}, [shot], "unused.wav",
                            tempfile.gettempdir())
        except main.LocationFallback:
            row("forest fallback blocked", True, "no mismatched playroom clip can be generated")
        else:
            row("forest fallback blocked", False, "mismatched scene was not rejected")
    finally:
        main.keyframes.make_keyframe = original


def motion_audit_test():
    """Optical-flow diagnostics detect frozen vs visibly changing synthetic frames."""
    import numpy as np
    still = np.zeros((128, 128), dtype=np.uint8)
    frozen = motion_audit.analyze_frames([still.copy() for _ in range(5)])
    row("motion audit detects frozen frames", frozen["status"] == "low_activity",
        f"mean flow={frozen['mean_flow_px']:.4f}px")
    moving = []
    for x in (10, 14, 18, 22, 26):
        frame = np.zeros((128, 128), dtype=np.uint8)
        frame[35:85, x:x + 28] = 255
        moving.append(frame)
    active = motion_audit.analyze_frames(moving)
    row("motion audit detects visible changes", active["status"] == "motion_detected",
        f"mean flow={active['mean_flow_px']:.4f}px")


def motion_prompt_scope_test():
    """Wide and solo prompts must not contain contradictory framing or motion demands."""
    import text_gen
    ep = {"location": "home", "actions": ["the children walk and wave"]}
    wide = text_gen.shot_prompt(ep, {"i": 0, "kind": "wide", "camera": "wide shot", "who": "younis"}).lower()
    solo = text_gen.shot_prompt(ep, {"i": 1, "kind": "speech", "camera": "close-up", "who": "farida"}).lower()
    row("wide prompt requests both-child full-body action",
        "both children" in wide and "full-body" in wide)
    row("solo prompt avoids conflicting two-child/full-body demands",
        "only the named speaker" in solo and "upper-body" in solo
        and "second child out of frame" in solo and "full-body composition" in solo
        and "both children" not in solo and "full-body two-shot" not in solo)

def interaction_choreography_test():
    """Wide shots need reciprocal action; solo shots must keep the partner off-screen."""
    import text_gen
    ep = {"location": "home", "actions": ["Younis offers a ball and Farida catches it"]}
    wide = text_gen.shot_prompt(ep, {"i": 0, "kind": "wide", "camera": "wide shot", "who": "younis"}).lower()
    solo = text_gen.shot_prompt(ep, {"i": 1, "kind": "speech", "camera": "close-up", "who": "farida"}).lower()
    row("wide interaction has cause-and-effect choreography",
        "cause-and-effect interaction" in wide and "initiates" in wide
        and "responds" in wide and "both complete" in wide
        and "shared prop consistent" in wide)
    row("solo action keeps partner off-screen",
        "only their own visible part" in solo and "off-screen position" in solo
        and "never imply that the second child is visible" in solo
        and "second child out of frame" in solo)


def episode_motion_metadata_test():
    """Episode construction must not reference an undefined motion-lock symbol."""
    import text_gen
    ep = text_gen.make_episode([], "home")
    prompts = ep.get("motion", [])
    row("episode motion metadata is built", len(prompts) == config.SCENES
        and all("ANIMATE BOTH CHARACTERS" in prompt for prompt in prompts))


def idea_dedup_test():
    """Regression tests for semantic topic detection and history persistence."""
    import text_gen

    old_handwash = [{"date": "20261101", "title": "يونس وفريدة يغسلان أيديهما"}]
    detected = text_gen._candidate_topics({
        "title": "مغامرة جديدة في البيت",
        "lines": [{"who": "younis", "text": "نضع الصابون ونفرك الكفين جيداً."}],
        "actions": ["the kids wash their hands with soap bubbles"],
    })
    row("handwashing detected from dialogue and action", "handwashing" in detected)

    cleanup = {"title": "يونس وفريدة ينظفان مكان النزهة",
               "lines": [{"who": "farida", "text": "نجمع المخلفات في كيس النفايات."}],
               "actions": ["the kids pick up litter in the forest"]}
    cleanup_topics = text_gen._candidate_topics(cleanup)
    row("nature cleanup stays separate from handwashing",
        "nature_cleanup" in cleanup_topics and "handwashing" not in cleanup_topics)

    vague = {"title": "يونس وفريدة يحافظان على نظافة الغابة",
             "lines": [{"who": "younis", "text": "نحب المكان الجميل."}], "actions": []}
    row("generic cleanliness wording does not imply handwashing",
        "handwashing" not in text_gen._candidate_topics(vague))

    old_full = [{"date": "20261101", "title": "موضوع مختلف", "topic": "handwashing",
                 "narration": "نغسل أيدينا بالصابون ونفرك الكفين جيداً قبل الطعام.",
                 "lines": [{"who": "farida", "text": "نغسل أيدينا بالصابون."}],
                 "actions": ["the children wash their hands"]}]
    row("full history content is indexed", "handwashing" in text_gen._history_topics(old_full))

    # A generated episode that disguises handwashing under a new title must be rejected.
    original = text_gen._ask_gemini
    try:
        text_gen._ask_gemini = lambda *_: {
            "title": "مفاجأة في الصباح",
            "lines": [{"who": "younis", "text": "نضع الصابون ونغسل أيدينا."},
                      {"who": "farida", "text": "نفرك الكفين جيداً."}],
            "actions": ["the kids wash their hands with soap"],
            "description": "قصة جديدة"}
        ep = text_gen.make_episode(old_handwash, "home")
        row("Gemini disguised duplicate is rejected", ep.get("topic") != "handwashing"
            and ep.get("source") == "fallback_bank")
    except Exception as exc:
        row("Gemini disguised duplicate is rejected", False, str(exc))
    finally:
        text_gen._ask_gemini = original

    # Every fallback topic is rejected once recorded; never silently recycle an idea.
    exhausted = [{"title": b["title"], "topic": b["topic"], "location": b["location"]}
                 for b in text_gen.FALLBACK_BANK if b["location"] == "home"]
    try:
        text_gen.make_episode(exhausted, "home")
        row("fallback exhaustion blocks duplicate publication", False)
    except RuntimeError as exc:
        row("fallback exhaustion blocks duplicate publication", "No unused fallback ideas" in str(exc))


def provider_notice_test():
    """Provider notices must be safe when email is not configured and deduplicated."""
    import deliver
    import os
    old_user = os.environ.pop("EMAIL_USER", None)
    old_password = os.environ.pop("EMAIL_APP_PASSWORD", None)
    try:
        category = "selftest-provider-notice"
        first = deliver.notify_provider_usage(category, "offline-test")
        second = deliver.notify_provider_usage(category, "offline-test")
        row("provider notice skips safely without email credentials",
            first == "skipped (email credentials not configured)")
        row("provider notice is deduplicated",
            second == "skipped (already notified)")
    finally:
        if old_user is not None:
            os.environ["EMAIL_USER"] = old_user
        if old_password is not None:
            os.environ["EMAIL_APP_PASSWORD"] = old_password


def completion_email_body_test():
    """Completion email must contain real line breaks and a usable artifact review URL."""
    import deliver
    meta = {"title": "اختبار", "description": "وصف", "tags": [], "narration": "نص"}
    report = {"idea_source": "offline", "voice_provider": "offline",
              "keyframes": ["reference"], "video_providers": ["local"]}
    keys = ("GITHUB_RUN_NUMBER", "GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID")
    old = {key: os.environ.get(key) for key in keys}
    try:
        os.environ.update({"GITHUB_RUN_NUMBER": "123", "GITHUB_SERVER_URL": "https://github.com",
                           "GITHUB_REPOSITORY": "owner/repo", "GITHUB_RUN_ID": "456"})
        body = deliver.build_completion_email_body(meta, report)
        expected_url = "https://github.com/owner/repo/actions/runs/456"
        row("completion email explains private upload follow-up and real line breaks",
            "Private" in body and "رسالة متابعة" in body
            and expected_url in body and body.endswith(expected_url + "\n")
            and "\\nhttps://" not in body)
        row("completion email names the exact artifact",
            "episode-123" in body and "Artifact" in body)
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value



def quota_fallback_test():
    """When remote providers are unavailable, keep output playable but label it degraded."""
    import main
    original_chain = main.try_chain
    original_local = main.video_mod.local_motion_clip
    original_order = main.config.VIDEO_ORDER
    original_spaces = main.config.VIDEO_SPACES
    try:
        main.config.VIDEO_ORDER = ["hf_spaces"]
        main.config.VIDEO_SPACES = []
        main.try_chain = lambda *_: (None, None, ["simulated quota exhaustion"])
        def fake_local(canvas, seconds, out, variant=0):
            run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                 f"color=c=blue:s=360x640:d={seconds}", "-an",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", out])
            return out
        main.video_mod.local_motion_clip = fake_local
        main.DEGRADED_SHOTS.clear()
        result, label, errors = main.gen_clip(
            "canvas.jpg", "test", 2,
            os.path.join(tempfile.gettempdir(), "quota-fallback-test.mp4"), 3, set()
        )
        row("quota fallback preserves episode with degraded label",
            label == "local_motion_degraded" and 4 in main.DEGRADED_SHOTS
            and any("manual review required" in e for e in errors))
    except Exception as exc:
        row("quota fallback preserves episode with degraded label", False, str(exc)[:200])
    finally:
        main.try_chain = original_chain
        main.video_mod.local_motion_clip = original_local
        main.config.VIDEO_ORDER = original_order
        main.config.VIDEO_SPACES = original_spaces
        main.DEGRADED_SHOTS.clear()

def offline():
    work = tempfile.mkdtemp(prefix="selftest_")
    row("20-second target", config.MIN_SECONDS == 20.0 and config.MAX_SECONDS == 20.0)
    location_guard_test()
    motion_audit_test()
    motion_prompt_scope_test()
    interaction_choreography_test()
    episode_motion_metadata_test()
    idea_dedup_test()
    provider_notice_test()
    completion_email_body_test()
    quota_fallback_test()
    for tool in ("ffmpeg", "ffprobe"):
        r = run([tool, "-version"], check=False); row(tool, r.returncode == 0)
    font = compose.find_arabic_font(); row("arabic font", bool(font), str(font))
    if compose.RAQM:
        row("arabic shaping", True, "Pillow RAQM enabled")
    else:
        try:
            import arabic_reshaper
            try:
                from bidi import get_display
            except ImportError:
                from bidi.algorithm import get_display
            row("arabic shaping", True, "arabic-reshaper + python-bidi")
        except ImportError:
            row("arabic shaping", False, "install arabic-reshaper and python-bidi")
    img = Image.new("RGB", (1600, 900), (120, 190, 255)); d = ImageDraw.Draw(img)
    d.ellipse((500, 250, 800, 550), fill=(255, 220, 180)); d.ellipse((850, 280, 1100, 530), fill=(255, 200, 200))
    p = os.path.join(work, "img.jpg"); img.save(p)
    canvas = compose.make_canvas(p, os.path.join(work, "canvas.jpg")); row("canvas", os.path.exists(canvas))
    wav = os.path.join(work, "tone.wav")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=17", "-ar", "44100", "-ac", "1", wav])
    audio, alen = compose.fit_audio(wav, os.path.join(work, "fit.wav"))
    clips = [video_mod.local_motion_clip(canvas, alen / 3, os.path.join(work, f"s{i}.mp4"), i) for i in range(3)]
    row("local motion clips", all(has_video(c) for c in clips))
    text = "مرحباً يا أصدقاء أنا يونس وهذه أختي فريدة اليوم سنتعلم شيئاً جديداً ومفيداً معاً هيا بنا نبدأ"
    out = os.path.join(work, "final.mp4")
    compose.build_final(clips, audio, text, work, out)
    d = duration(out)
    row("final video", has_video(out) and has_audio(out)
        and config.MIN_SECONDS - 0.8 <= d <= config.MAX_SECONDS + 0.8,
        f"{d:.1f}s (expected {config.MIN_SECONDS:.1f}-{config.MAX_SECONDS:.1f}s) -> {out}")
    return out

def email_test():
    import deliver
    meta = {"title": "رسالة تجريبية", "description": "اختبار التسليم", "tags": [], "narration": "اختبار"}
    work = tempfile.mkdtemp(prefix="selftest_mail_")
    vid = os.path.join(work, "test.mp4")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=skyblue:s=360x640:d=2", "-f", "lavfi",
         "-i", "sine=frequency=300:duration=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", vid])
    try:
        row("email", True, deliver.send_email(vid, meta, {"quality": "ok"}))
    except Exception as e:
        row("email", False, f"{type(e).__name__}: {str(e)[:250]}")

def online_speech(work, ip):
    wav = os.path.join(work, "t.wav")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=2", "-ar", "16000", "-ac", "1", wav])
    for sp in config.SPEECH_SPACES:
        try:
            c = video_mod._client(sp)
            plans = video_mod._plan_calls(c, ip, "test", 5, audio_path=wav)
            row(f"speech:{sp}", bool(plans), f"endpoints usable: {[a for a, _ in plans][:3]}")
        except Exception as e:
            row(f"speech:{sp}", False, str(e)[:200])

def online():
    row("GEMINI_API_KEY set", bool(config.GEMINI_API_KEY))
    row("HF_TOKEN set (optional but recommended)", bool(config.HF_TOKEN))
    work = tempfile.mkdtemp(prefix="selftest_online_")
    text = "مرحباً يا أصدقاء، أنا يونس."
    for name, fn in voice_mod.PROVIDERS.items():
        try:
            w = fn(text, work); row(f"voice:{name}", duration(w) > 1, f"{duration(w):.1f}s")
        except Exception as e:
            row(f"voice:{name}", False, str(e)[:200])
    img = Image.new("RGB", (512, 512), (200, 230, 255)); ip = os.path.join(work, "t.jpg"); img.save(ip)
    if config.SPEECH_ENABLED:
        online_speech(work, ip)
    else:
        row("speech video", True, "disabled to preserve free daily GPU quota; using image-to-video")
    for sp in config.VIDEO_SPACES:
        try:
            c = video_mod._client(sp)
            plans = video_mod._plan_calls(c, ip, "test", 5)
            row(f"space:{sp}", bool(plans), f"endpoints usable: {[a for a, _ in plans][:3]}")
        except Exception as e:
            row(f"space:{sp}", False, str(e)[:200])

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--offline"
    if mode == "--online":
        online()
    elif mode == "--email":
        email_test()
    else:
        offline()
    failed = [r for r in rows if not r[1]]
    summ = "\n".join(f"- {'✅' if ok else '❌'} {n} {note}" for n, ok, note in rows)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(f"## Self test {mode}\n{summ}\n")
    # online: نفشل لو لم يعمل أي مزود صوت أو أي مساحة فيديو (لأن البديل المحلي ليس حركة حقيقية)
    if mode == "--online":
        voice_ok = any(ok for n, ok, _ in rows if n.startswith("voice:"))
        space_ok = any(ok for n, ok, _ in rows if n.startswith(("space:", "speech:")))
        sys.exit(0 if (voice_ok and space_ok) else 1)
    sys.exit(1 if failed else 0)
