from __future__ import annotations

import math
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Any, Iterable, Sequence

from .transcription import Transcript


def _cv2():
    try:
        import cv2  # type: ignore
        return cv2
    except ImportError:
        local = Path(__file__).resolve().parent.parent / ".tools" / "opencv"
        if local.is_dir() and str(local) not in sys.path:
            sys.path.insert(0, str(local))
        import cv2  # type: ignore
        return cv2


def _median(values: Iterable[float]) -> float:
    actual = list(values)
    return round(statistics.median(actual), 4) if actual else 0.0


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return float(ordered[index])


def _group(samples: list[dict[str, Any]], predicate, interval: float, minimum: float = 0.35) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for sample in samples:
        if predicate(sample):
            if current and sample["time"] - current[-1]["time"] > interval * 1.8:
                groups.append(current); current = []
            current.append(sample)
        elif current:
            groups.append(current); current = []
    if current:
        groups.append(current)
    result = []
    for items in groups:
        start, end = items[0]["time"], items[-1]["time"] + interval
        if end - start >= minimum:
            result.append({"start": round(start, 3), "end": round(end, 3), "samples": items})
    return result


def _text_groups(samples: list[dict[str, Any]], interval: float) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for sample in samples:
        box = sample.get("text_bbox")
        if box is None:
            if current:
                groups.append(current); current = []
            continue
        split = False
        if current:
            previous = current[-1]["text_bbox"]
            area_ratio = max(box["area"], previous["area"]) / max(0.001, min(box["area"], previous["area"]))
            center_delta = abs((box["x"] + box["w"] / 2) - (previous["x"] + previous["w"] / 2)) + abs((box["y"] + box["h"] / 2) - (previous["y"] + previous["h"] / 2))
            split = area_ratio > 1.55 or center_delta > 0.16 or sample["time"] - current[0]["time"] >= 1.5
        if split:
            groups.append(current); current = []
        current.append(sample)
    if current:
        groups.append(current)
    return [
        {"start": round(items[0]["time"], 3), "end": round(items[-1]["time"] + interval, 3), "duration": round(items[-1]["time"] + interval - items[0]["time"], 3), "samples": items}
        for items in groups if items[-1]["time"] + interval - items[0]["time"] >= 0.30
    ]


def _spoken_text(transcript: Transcript | None, start: float, end: float) -> str | None:
    if transcript is None:
        return None
    selected = [word.text for segment in transcript.segments for word in segment.words if word.end > start and word.start < end]
    return " ".join(selected).strip() or None


def _text_bbox_from_mask(mask: Any, cv2: Any) -> dict[str, float] | None:
    frame_height, frame_width = mask.shape[:2]
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    components: list[dict[str, float]] = []
    for x, y, width, height, area in stats[1:count]:
        fill = area / max(1, width * height)
        if not (
            width >= frame_width * 0.025 and height >= frame_height * 0.007
            and width <= frame_width * 0.62 and height <= frame_height * 0.115
            and area >= 18 and 0.08 <= fill <= 0.82
        ):
            continue
        components.append({"x": float(x), "y": float(y), "w": float(width), "h": float(height), "area": float(area)})
    if not components:
        return None
    rows: list[list[dict[str, float]]] = []
    for component in sorted(components, key=lambda item: item["y"] + item["h"] / 2):
        center = component["y"] + component["h"] / 2
        row = next((items for items in rows if abs(center - statistics.mean(item["y"] + item["h"] / 2 for item in items)) <= frame_height * 0.045), None)
        if row is None:
            rows.append([component])
        else:
            row.append(component)
    row_boxes = []
    for row in rows:
        x1, y1 = min(item["x"] for item in row), min(item["y"] for item in row)
        x2, y2 = max(item["x"] + item["w"] for item in row), max(item["y"] + item["h"] for item in row)
        if x2 - x1 < frame_width * 0.14:
            continue
        row_boxes.append({"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1, "ink": sum(item["area"] for item in row)})
    if not row_boxes:
        return None
    clusters: list[list[dict[str, float]]] = []
    for row in sorted(row_boxes, key=lambda item: item["y"]):
        compatible = next((cluster for cluster in clusters if row["y"] - max(item["y"] + item["h"] for item in cluster) <= frame_height * 0.075 and abs((row["x"] + row["w"] / 2) - statistics.mean(item["x"] + item["w"] / 2 for item in cluster)) <= frame_width * 0.24), None)
        if compatible is None:
            clusters.append([row])
        else:
            compatible.append(row)
    candidates = []
    for cluster in clusters:
        x1, y1 = min(item["x"] for item in cluster), min(item["y"] for item in cluster)
        x2, y2 = max(item["x"] + item["w"] for item in cluster), max(item["y"] + item["h"] for item in cluster)
        width, height = x2 - x1, y2 - y1
        if height > frame_height * 0.34:
            continue
        center_y = (y1 + y2) / 2 / frame_height
        center_weight = 1.0 - min(0.45, abs(center_y - 0.57) * 0.5)
        score = sum(item["ink"] for item in cluster) * center_weight * (1 + 0.12 * (len(cluster) - 1))
        candidates.append((score, {"x": x1 / frame_width, "y": y1 / frame_height, "w": width / frame_width, "h": height / frame_height, "area": width * height / (frame_width * frame_height)}))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _audio_transients(video: Path, ffmpeg: Path, duration: float) -> list[dict[str, Any]]:
    try:
        import numpy as np  # type: ignore
        result = subprocess.run(
            [str(ffmpeg), "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1"],
            capture_output=True, check=True,
        )
        signal = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        frame = 400
        if signal.size < frame:
            return []
        rms = np.sqrt(np.mean(signal[: signal.size // frame * frame].reshape(-1, frame) ** 2, axis=1) + 1e-9)
        baseline = np.maximum(0.006, np.convolve(rms, np.ones(15) / 15, mode="same"))
        onset = rms / baseline
        threshold = max(3.0, float(np.percentile(onset, 99.0)))
        candidates = np.where(onset >= threshold)[0]
        events: list[dict[str, Any]] = []
        last = -10.0
        for index in candidates:
            time = float(index * 0.05)
            if time - last < 0.48 or time > duration:
                continue
            strength = min(1.0, float((onset[index] - 1.0) / 4.0))
            category = "IMPACT" if strength > 0.72 else "POP" if strength > 0.45 else "CLICK"
            events.append({"time": round(time, 3), "category": category, "strength": round(strength, 3), "confidence": 0.48, "method": "audio_transient"})
            last = time
        return events
    except Exception:
        return []


def analyze_reference_visuals(
    video: Path, duration: float, *, transcript: Transcript | None = None,
    ffmpeg: Path | None = None, sample_interval: float = 0.25,
) -> dict[str, Any]:
    """Measure observable edit behavior; uncertain semantics stay explicitly approximate."""
    cv2 = _cv2()
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open reference video: {video}")
    cascade_root = Path(getattr(getattr(cv2, "data", None), "haarcascades", Path(cv2.__file__).parent / "data"))
    detector = cv2.CascadeClassifier(str(cascade_root / "haarcascade_frontalface_alt2.xml"))
    samples: list[dict[str, Any]] = []
    previous_hist = previous_gray = None
    time = 0.0
    try:
        while time < duration:
            capture.set(cv2.CAP_PROP_POS_MSEC, time * 1000)
            ok, frame = capture.read()
            if not ok:
                time += sample_interval; continue
            height, width = frame.shape[:2]
            analysis_width = min(432, width)
            scale = analysis_width / width
            small = cv2.resize(frame, (analysis_width, max(1, round(height * scale))))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            equalized = cv2.equalizeHist(gray)
            faces = detector.detectMultiScale(equalized, scaleFactor=1.09, minNeighbors=5, minSize=(32, 32)) if not detector.empty() else []
            face = max(faces, key=lambda box: box[2] * box[3]) if len(faces) else None
            face_data = None if face is None else {
                "x": round((face[0] + face[2] / 2) / small.shape[1], 4),
                "y": round((face[1] + face[3] / 2) / small.shape[0], 4),
                "w": round(face[2] / small.shape[1], 4), "h": round(face[3] / small.shape[0], 4),
                "area": round(face[2] * face[3] / (small.shape[0] * small.shape[1]), 5),
            }
            white = cv2.inRange(hsv, (0, 0, 185), (180, 125, 255))
            saturated = cv2.inRange(hsv, (0, 105, 145), (40, 255, 255)) | cv2.inRange(hsv, (165, 105, 145), (180, 255, 255))
            mask = cv2.morphologyEx(white | saturated, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)))
            text_bbox = _text_bbox_from_mask(mask, cv2)
            hist = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
            cv2.normalize(hist, hist)
            hist_change = 0.0 if previous_hist is None else float(cv2.compareHist(previous_hist, hist, cv2.HISTCMP_BHATTACHARYYA))
            frame_change = 0.0 if previous_gray is None else float(cv2.mean(cv2.absdiff(previous_gray, gray))[0] / 255.0)
            samples.append({
                "time": round(time, 3), "face": face_data, "text_bbox": text_bbox,
                "brightness": round(float(gray.mean()), 3), "hist_change": round(hist_change, 4),
                "frame_change": round(frame_change, 4), "cut": hist_change > 0.43 and frame_change > 0.17,
            })
            previous_hist, previous_gray = hist, gray
            time += sample_interval
    finally:
        capture.release()

    face_coverage = sum(item["face"] is not None for item in samples) / max(1, len(samples))
    text_groups = _text_groups(samples, sample_interval)
    text_scenes: list[dict[str, Any]] = []
    for index, group in enumerate(text_groups):
        boxes = [item["text_bbox"] for item in group["samples"] if item["text_bbox"]]
        box = max(boxes, key=lambda item: item["area"])
        center_x, center_y = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
        role = "HERO" if box["area"] >= 0.24 or box["h"] >= 0.30 else "DISPLAY" if box["area"] >= 0.11 else "BODY"
        position = "top" if center_y < 0.35 else "lower" if center_y > 0.61 else "center"
        spoken = _spoken_text(transcript, group["start"], group["end"])
        words_count = len(spoken.split()) if spoken else None
        lines = max(1, min(4, round(box["h"] / max(0.045, box["w"] * 0.14))))
        text_scenes.append({
            "id": f"text-{index + 1:03d}", "start": group["start"], "end": group["end"],
            "duration": round(group["end"] - group["start"], 3), "actual_text": spoken,
            "text_source": "aligned_speech_proxy" if spoken else "not_ocr_verified",
            "word_count": words_count, "line_count": lines,
            "relative_width": round(box["w"], 4), "relative_height": round(box["h"], 4),
            "position": position, "alignment": "center" if 0.35 <= center_x <= 0.65 else "left" if center_x < 0.35 else "right",
            "role": role, "relative_font_size": round(min(1.0, box["h"] / max(1, lines) / 0.12), 3),
            "approximate_weight": "bold" if box["area"] > 0.045 else "medium",
            "font_character": "unknown", "stroke": "probable" if box["area"] > 0.025 else "uncertain",
            "shadow": "uncertain", "background_card": False,
            "animation_type": "POP_OR_SCALE" if group["samples"][0]["frame_change"] > 0.08 else "FADE_OR_STATIC",
            "animation_duration": round(min(0.28, group["duration"] * 0.25), 3),
            "measurement_confidence": 0.58,
        })

    cuts = [{"time": item["time"], "type": "HARD_CUT", "confidence": round(min(0.95, 0.55 + item["hist_change"] * 0.5), 3)} for item in samples if item["cut"]]
    broll_groups = _group(samples, lambda item: face_coverage >= 0.25 and item["face"] is None, sample_interval, 0.55)
    broll = []
    for index, group in enumerate(broll_groups):
        duration_value = group["end"] - group["start"]
        if duration_value > 8.0 and face_coverage < 0.5:
            continue
        shot_cuts = [cut for cut in cuts if group["start"] < cut["time"] < group["end"]]
        spoken = _spoken_text(transcript, group["start"], group["end"])
        broll.append({
            "id": f"insert-{index + 1:02d}", "start": group["start"], "end": group["end"], "duration": round(duration_value, 3),
            "presentation": "FULL_SCREEN", "shots": max(1, len(shot_cuts) + 1), "burst": len(shot_cuts) >= 1,
            "approximate_topic": spoken, "illustrated_thought": spoken,
            "timing_to_key_word": "UNKNOWN", "returns_to_speaker": group["end"] < duration - 0.5,
            "transition_type": "CUT" if shot_cuts else "UNKNOWN", "semantic_function": "ILLUSTRATE" if spoken else "INSUFFICIENT_EVIDENCE",
            "confidence": 0.62,
        })

    camera = []
    face_samples = [item for item in samples if item["face"]]
    baseline_area = _median([item["face"]["area"] for item in face_samples])
    last_event = -10.0
    previous = None
    for item in face_samples:
        if previous is None:
            previous = item; continue
        ratio = item["face"]["area"] / max(0.0001, previous["face"]["area"])
        if item["time"] - last_event >= 0.8 and (ratio >= 1.16 or ratio <= 0.86):
            cut_near = any(abs(cut["time"] - item["time"]) <= sample_interval * 1.2 for cut in cuts)
            effect = "CUT_TO_CLOSER" if ratio >= 1.16 and cut_near else "PUNCH_ZOOM" if ratio >= 1.35 else "SUBTLE_PUSH" if ratio >= 1.16 else "RECOVERY"
            camera.append({
                "time": item["time"], "effect": effect, "scale_delta": round(math.sqrt(max(0.01, ratio)) - 1.0, 3),
                "duration": 0.0 if cut_near else round(item["time"] - previous["time"], 3), "confidence": 0.56,
            })
            last_event = item["time"]
        previous = item

    brightness = [item["brightness"] for item in samples]
    median_brightness = _median(brightness)
    effects = []
    for item in samples:
        if item["brightness"] > median_brightness + 34 and item["frame_change"] > 0.11:
            effects.append({"time": item["time"], "type": "FLASH", "confidence": 0.61})
        elif 0.26 < item["hist_change"] <= 0.43 and item["frame_change"] > 0.12:
            effects.append({"time": item["time"], "type": "TRANSITION", "confidence": 0.5})
    # Cooldown avoids counting the same multi-frame effect repeatedly.
    effects = [event for index, event in enumerate(effects) if index == 0 or event["time"] - effects[index - 1]["time"] >= 0.35]
    sfx = _audio_transients(video, ffmpeg, duration) if ffmpeg else []

    boundaries = {0.0, round(duration, 3)}
    for collection in (text_scenes, broll):
        for item in collection:
            boundaries.update((item["start"], item["end"]))
    for event in camera + effects:
        boundaries.add(float(event["time"]))
    ordered = sorted(value for value in boundaries if 0 <= value <= duration)
    rhythm = []
    for start, end in zip(ordered, ordered[1:]):
        middle = (start + end) / 2
        broll_active = next((item for item in broll if item["start"] <= middle < item["end"]), None)
        text_active = next((item for item in text_scenes if item["start"] <= middle < item["end"]), None)
        strong_camera = next((item for item in camera if abs(item["time"] - middle) <= 0.45), None)
        strong_effect = next((item for item in effects if abs(item["time"] - middle) <= 0.3), None)
        if broll_active:
            state, reason = "BROLL", "speaker replaced by visual insert"
        elif text_active and text_active["role"] == "HERO":
            state, reason = "HERO", "large text composition"
        elif text_active:
            state, reason = "NORMAL_TEXT" if text_active["role"] == "BODY" else "ACCENT", "visible typography"
        elif strong_camera or strong_effect:
            state, reason = "VISUAL_EVENT", "camera or effect stimulation"
        else:
            state, reason = "SPEAKER_ONLY", "no strong text, camera, insert or effect"
        rhythm.append({"start": round(start, 3), "end": round(end, 3), "state": state, "reason": reason})
    rest = [item for item in rhythm if item["state"] in {"SPEAKER_ONLY", "NORMAL_TEXT"}]
    text_duration = sum(item["end"] - item["start"] for item in text_scenes)
    broll_duration = sum(item["duration"] for item in broll)
    rest_duration = sum(item["end"] - item["start"] for item in rest)
    text_words = [item["word_count"] for item in text_scenes if item["word_count"] is not None]
    gaps = [broll[index]["start"] - broll[index - 1]["end"] for index in range(1, len(broll))]
    calm_camera = max(0.0, duration - sum(max(0.25, item.get("duration", 0.0)) for item in camera))
    detected_style = "aggressive_social" if len(effects) / max(1.0, duration) > 0.12 or len(camera) / max(1.0, duration) > 0.12 else "clean_expert" if text_duration / max(duration, 1) > 0.55 else "podcast"
    return {
        "version": 3, "method": "opencv_clustered_text_measurement_v3", "sample_interval": sample_interval,
        "limitations": ["No font-family guessing", "Text is speech-aligned proxy, not OCR", "SFX categories are transient estimates"],
        "typography": {"scenes": text_scenes, "summary": {
            "text_coverage": round(min(1.0, text_duration / max(duration, 1)), 3),
            "text_free_coverage": round(max(0.0, 1 - text_duration / max(duration, 1)), 3),
            "median_scene_duration": _median([item["duration"] for item in text_scenes]),
            "median_words_per_scene": _median(text_words), "maximum_words": max(text_words, default=0),
            "hero_count": sum(item["role"] == "HERO" for item in text_scenes),
            "accent_count": sum(item["role"] == "DISPLAY" for item in text_scenes),
            "number_count": sum(bool(item.get("actual_text") and any(char.isdigit() for char in item["actual_text"])) for item in text_scenes),
            "composition_change_cadence": round(duration / max(1, len(text_scenes)), 3),
        }},
        "camera": {"events": camera, "summary": {"count": len(camera), "calm_coverage": round(calm_camera / max(1, duration), 3), "median_gap": _median([camera[i]["time"] - camera[i - 1]["time"] for i in range(1, len(camera))])}},
        "broll": {"events": broll, "summary": {"count": len(broll), "coverage": round(broll_duration / max(1, duration), 3), "average_duration": round(broll_duration / max(1, len(broll)), 3), "median_duration": _median([item["duration"] for item in broll]), "average_gap": round(sum(gaps) / len(gaps), 3) if gaps else None, "shots_per_burst": _median([item["shots"] for item in broll])}},
        "motion": {"events": effects, "summary": {"count": len(effects), "event_density": round(len(effects) / max(1, duration), 3)}},
        "visual_rest": {"intervals": rest, "summary": {"coverage": round(rest_duration / max(1, duration), 3), "median_duration": _median([item["end"] - item["start"] for item in rest])}},
        "sfx": {"events": sfx, "summary": {"count": len(sfx), "event_density": round(len(sfx) / max(1, duration), 3), "confidence": 0.48 if sfx else 0.0}},
        "cuts": {"events": cuts, "summary": {"count": len(cuts), "average_cadence": round(duration / max(1, len(cuts)), 3)}},
        "composition_rhythm": rhythm,
        "speaker": {"face_coverage": round(face_coverage, 3), "speaker_only_coverage": round(max(0.0, 1 - broll_duration / max(1, duration)), 3), "baseline_face_area": baseline_area},
        "style": {"human_label": None, "detected_style": detected_style, "style_confidence": 0.58, "style_characteristics": {"text_density": round(text_duration / max(1, duration), 3), "camera_density": round(len(camera) / max(1, duration), 3), "effect_density": round(len(effects) / max(1, duration), 3)}},
    }
