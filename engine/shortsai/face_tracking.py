from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from .config import FaceTrackingConfig


def analyze_faces(
    video: Path, duration: float, config: FaceTrackingConfig, *, rotation: int = 0,
) -> dict[str, Any]:
    fallback = {
        "enabled": config.enabled,
        "method": "safe_zone_fallback",
        "detected": False,
        "dominantPosition": "center",
        "textSide": "bottom",
        "cropAnchor": {"x": 0.5, "y": 0.42},
        "avoidancePadding": 0.06,
        "cropKeyframes": [],
        "freeZones": [
            {"position": "lower", "x": 0.08, "y": 0.62, "w": 0.84, "h": 0.20, "score": 1.0},
            {"position": "top", "x": 0.08, "y": 0.10, "w": 0.84, "h": 0.18, "score": 0.55},
        ],
        "samples": [],
        "sourceOrientation": {"rotation": int(rotation), "normalized": False},
    }
    if not config.enabled:
        return fallback
    try:
        import cv2  # type: ignore
    except ImportError:
        local_opencv = Path(__file__).resolve().parent.parent / ".tools" / "opencv"
        if local_opencv.is_dir() and str(local_opencv) not in sys.path:
            sys.path.insert(0, str(local_opencv))
        try:
            import cv2  # type: ignore
        except ImportError:
            fallback["reason"] = "opencv_not_installed"
            return fallback

    cv2_data = getattr(getattr(cv2, "data", None), "haarcascades", None)
    cascade_root = Path(cv2_data) if cv2_data else Path(cv2.__file__).resolve().parent / "data"
    cascade_path = cascade_root / "haarcascade_frontalface_alt2.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened() or detector.empty():
        fallback["reason"] = "video_or_detector_unavailable"
        return fallback
    orientation_auto = getattr(cv2, "CAP_PROP_ORIENTATION_AUTO", None)
    if orientation_auto is not None:
        capture.set(orientation_auto, 1)
    samples: list[dict[str, float]] = []
    timestamp = 0.0
    try:
        while timestamp < duration:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if not ok:
                timestamp += config.sample_interval
                continue
            frame_height, frame_width = frame.shape[:2]
            # Some OpenCV builds ignore QuickTime rotation metadata. Normalize only
            # when the returned frame still has the coded landscape orientation.
            if abs(rotation) % 180 == 90 and frame_width > frame_height:
                rotate_code = cv2.ROTATE_90_COUNTERCLOCKWISE if rotation < 0 else cv2.ROTATE_90_CLOCKWISE
                frame = cv2.rotate(frame, rotate_code)
            gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            faces = detector.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(54, 54))
            if len(faces):
                x, y, width, height = max(faces, key=lambda value: value[2] * value[3])
                frame_height, frame_width = gray.shape[:2]
                samples.append({
                    "time": round(timestamp, 3),
                    "x": round((x + width / 2) / frame_width, 4),
                    "y": round((y + height / 2) / frame_height, 4),
                    "w": round(width / frame_width, 4),
                    "h": round(height / frame_height, 4),
                })
            timestamp += max(0.25, config.sample_interval)
    finally:
        capture.release()
    if not samples:
        fallback["reason"] = "no_face_detected"
        return fallback
    smoothed: list[dict[str, float]] = []
    previous: dict[str, float] | None = None
    for sample in samples:
        if previous is None:
            current = dict(sample)
        else:
            current = {"time": sample["time"]}
            for key in ("x", "y", "w", "h"):
                current[key] = round(previous[key] * 0.62 + sample[key] * 0.38, 4)
        smoothed.append(current)
        previous = current
    x = sum(item["x"] for item in smoothed) / len(smoothed)
    y = sum(item["y"] for item in smoothed) / len(smoothed)
    width = sum(item["w"] for item in smoothed) / len(smoothed)
    height = sum(item["h"] for item in smoothed) / len(smoothed)
    position = "left" if x < 0.42 else "right" if x > 0.58 else "center"
    face_left = max(0.0, x - width / 2 - 0.06)
    face_right = min(1.0, x + width / 2 + 0.06)
    face_top = max(0.0, y - height / 2 - 0.06)
    face_bottom = min(1.0, y + height / 2 + 0.06)
    free_zones = [
        {"position": "lower", "x": 0.08, "y": round(max(0.58, face_bottom), 3), "w": 0.84, "h": 0.22, "score": 1.0},
        {"position": "top", "x": 0.08, "y": 0.08, "w": 0.84, "h": round(max(0.08, face_top - 0.08), 3), "score": round(max(0.0, face_top), 3)},
    ]
    if face_left >= 0.30:
        free_zones.append({"position": "side_left", "x": 0.04, "y": 0.34, "w": round(face_left - 0.05, 3), "h": 0.34, "score": round(face_left, 3)})
    if 1.0 - face_right >= 0.34:
        free_zones.append({"position": "side_right", "x": round(face_right + 0.02, 3), "y": 0.34, "w": round(0.96 - face_right, 3), "h": 0.34, "score": round(1.0 - face_right, 3)})
    return {
        "enabled": True,
        "method": "opencv_haar",
        "detected": True,
        "dominantPosition": position,
        "textSide": "right" if position == "left" else "left" if position == "right" else "bottom",
        "cropAnchor": {"x": round(x, 4), "y": round(max(0.25, min(0.55, y)), 4)},
        "avoidancePadding": 0.06,
        "averageFace": {"x": round(x, 4), "y": round(y, 4), "w": round(width, 4), "h": round(height, 4)},
        "cropKeyframes": [{"time": item["time"], "x": item["x"], "y": round(max(0.25, min(0.55, item["y"])), 4)} for item in smoothed],
        "freeZones": free_zones,
        "samples": smoothed,
        "sourceOrientation": {"rotation": int(rotation), "normalized": True},
    }
