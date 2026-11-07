"""تشخيص نشاط الحركة في الفيديو عبر optical flow.
لا يثبت أن الحركة صادرة من جسم الشخصية: حركة الكاميرا والخلفية قد ترفع الدرجة.
لا يُستخدم لادعاء تطابق الوجوه أو لرفض مقطع صالح تقنياً.
"""
import cv2
import numpy as np


def analyze_frames(frames):
    """Analyze grayscale frames; returns a conservative visual-activity summary."""
    if len(frames) < 2:
        raise ValueError("at least two frames are required")
    normalized = []
    for frame in frames:
        if frame is None:
            continue
        if frame.ndim == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        normalized.append(cv2.resize(frame, (160, 284), interpolation=cv2.INTER_AREA))
    if len(normalized) < 2:
        raise ValueError("not enough readable frames")
    magnitudes = []
    active_ratios = []
    for previous, current in zip(normalized, normalized[1:]):
        flow = cv2.calcOpticalFlowFarneback(
            previous, current, None, 0.5, 3, 15, 3, 5, 1.2, 0
        )
        mag = cv2.magnitude(flow[..., 0], flow[..., 1])
        magnitudes.append(float(np.mean(mag)))
        active_ratios.append(float(np.mean(mag >= 0.35)))
    mean_flow = float(np.mean(magnitudes))
    active_ratio = float(np.mean(active_ratios))
    status = "motion_detected" if mean_flow >= 0.35 and active_ratio >= 0.01 else "low_activity"
    return {
        "status": status,
        "mean_flow_px": round(mean_flow, 4),
        "active_pixel_ratio": round(active_ratio, 4),
        "sampled_frames": len(normalized),
        "meaning": "visual optical-flow activity only; camera motion is not separated from character motion",
    }


def analyze_clip(path, samples=6):
    """Sample frames across a clip and calculate optical-flow activity."""
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise RuntimeError("could not open video for motion analysis")
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if count < 2:
            raise RuntimeError("video has fewer than two frames")
        indexes = np.linspace(0, count - 1, num=min(max(samples, 2), count), dtype=int)
        frames = []
        for index in indexes:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
        return analyze_frames(frames)
    finally:
        cap.release()
