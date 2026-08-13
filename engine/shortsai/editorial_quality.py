from __future__ import annotations

from dataclasses import asdict
from difflib import SequenceMatcher
from pathlib import Path
import re
import sys
from typing import Any, Sequence

from .config import EditorialQualityConfig
from .content_map import build_content_map
from .transcription import Transcript, TranscriptWord


TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё%]+", re.UNICODE)
LEAD_INS = frozenset("ну вот короче типа эм ээ значит ладно окей так вообще слушай смотрите".split())
WEAK_STARTS = frozenset("и а но потому поэтому при когда если чтобы который которая которые это там".split())
TECHNICAL = (
    "запись", "камера", "микрофон", "монтаж", "субтитр", "трекинг", "дубль",
    "еще раз", "заново", "тест", "окей я понял", "не получилось",
)
HOOK_WORDS = frozenset("почему как зачем сколько ошибка ошибки никогда деньги миллион причины секрет главное".split())
LOW_VALUE_OPENERS = frozenset("есть это вот ну эм эээ короче типа значит ладно окей".split())


def _tokens(text: str) -> list[str]:
    return [value.lower().replace("ё", "е") for value in TOKEN_RE.findall(text)]


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    overlap = len(set(a) & set(b)) / max(1, min(len(set(a)), len(set(b))))
    return max(overlap, SequenceMatcher(None, " ".join(a), " ".join(b)).ratio())


def _semantic_coverage(reference: str, candidate: str) -> float:
    reference_tokens, candidate_tokens = set(_tokens(reference)), set(_tokens(candidate))
    if not reference_tokens or not candidate_tokens:
        return 0.0
    return len(reference_tokens & candidate_tokens) / len(reference_tokens)


def _speech_score(text: str) -> dict[str, Any]:
    tokens = _tokens(text)
    normalized = " ".join(tokens)
    lead_count = 0
    for token in tokens:
        if token not in LEAD_INS:
            break
        lead_count += 1
    technical = any(phrase in normalized for phrase in TECHNICAL)
    complete = text.rstrip().endswith((".", "!", "?"))
    question = text.rstrip().endswith("?") or bool(tokens and tokens[0] in {"почему", "как", "зачем", "сколько"})
    standalone = len(tokens) >= 3 and (not tokens or tokens[0] not in WEAK_STARTS)
    curiosity = question or any(token in HOOK_WORDS for token in tokens[:8]) or any(char.isdigit() for char in text)
    trigrams = [tuple(tokens[index:index + 3]) for index in range(max(0, len(tokens) - 2))]
    repetition = 1.0 - len(set(trigrams)) / max(1, len(trigrams))
    score = 0.28 + min(0.20, len(tokens) * 0.025) + 0.16 * complete + 0.18 * standalone + 0.18 * curiosity
    score -= min(0.35, lead_count * 0.09) + (0.55 if technical else 0.0) + repetition * 0.34
    return {
        "score": round(max(0.0, min(1.0, score)), 3), "complete": complete,
        "standalone": standalone, "curiosity": curiosity, "technical": technical,
        "lead_words": lead_count,
        "repetition": round(repetition, 3),
    }


def _words_in_ranges(transcript: Transcript, ranges: Sequence[dict[str, Any]]) -> list[TranscriptWord]:
    result: list[TranscriptWord] = []
    for segment in transcript.segments:
        for word in segment.words:
            center = (word.start + word.end) / 2
            if any(float(item["source_start"]) <= center <= float(item["source_end"]) for item in ranges):
                result.append(word)
    return result


def _words_in_window(transcript: Transcript, start: float, end: float) -> list[TranscriptWord]:
    return [
        word for segment in transcript.segments for word in segment.words
        if word.end >= start and word.start <= end
    ]


def _phrases(words: Sequence[TranscriptWord]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    current: list[TranscriptWord] = []
    for word in words:
        if current and word.start - current[-1].end >= 0.75:
            result.append({"start": current[0].start, "end": current[-1].end, "text": " ".join(item.text for item in current)})
            current = []
        current.append(word)
        if word.text.rstrip().endswith((".", "!", "?", ";")) or len(current) >= 18:
            result.append({"start": current[0].start, "end": current[-1].end, "text": " ".join(item.text for item in current)})
            current = []
    if current:
        result.append({"start": current[0].start, "end": current[-1].end, "text": " ".join(item.text for item in current)})
    return result


def _repeated_take_phrases(words: Sequence[TranscriptWord]) -> list[dict[str, Any]]:
    tokens = [_tokens(word.text)[0] if _tokens(word.text) else "" for word in words]
    occurrences: dict[tuple[str, ...], list[int]] = {}
    for index in range(max(0, len(tokens) - 3)):
        gram = tuple(tokens[index:index + 4])
        if all(gram): occurrences.setdefault(gram, []).append(index)
    result: list[dict[str, Any]] = []
    used: set[tuple[float, float]] = set()
    for indices in occurrences.values():
        if len(indices) < 2 or any(right - left < 4 for left, right in zip(indices, indices[1:])):
            continue
        for offset, index in enumerate(indices):
            next_index = indices[offset + 1] if offset + 1 < len(indices) else min(len(words), index + 16)
            end_index = next_index
            for pointer in range(index, min(next_index, len(words))):
                if words[pointer].text.rstrip().endswith((".", "!", "?")):
                    end_index = pointer + 1; break
            if end_index - index < 4:
                continue
            key = (round(words[index].start, 3), round(words[end_index - 1].end, 3))
            if key in used: continue
            used.add(key)
            result.append({"start": words[index].start, "end": words[end_index - 1].end, "text": " ".join(word.text for word in words[index:end_index]), "repeated_take": True})
        break
    return result


def _word_boundary_alternatives(
    phrase: dict[str, Any], words: Sequence[TranscriptWord], config: EditorialQualityConfig,
) -> list[dict[str, Any]]:
    """Offer conservative visual trims without cutting a meaningful word.

    Only low-information opening tokens may be removed, and the remaining text
    must still form a standalone three-word-or-longer thought.  This covers raw
    takes where the speaker settles during a prolonged "есть/вот/ну", while
    preventing the gate from chopping a substantive sentence for a prettier
    frame.
    """
    inside = [
        word for word in words
        if word.start >= float(phrase["start"]) - 0.02 and word.end <= float(phrase["end"]) + 0.02
    ]
    result: list[dict[str, Any]] = []
    for index in range(1, min(4, len(inside) - 2)):
        removed = [token for word in inside[:index] for token in _tokens(word.text)]
        shift = float(inside[index].start) - float(phrase["start"])
        if not removed or not all(token in LOW_VALUE_OPENERS for token in removed):
            break
        if shift > config.max_visual_lead_trim_seconds:
            break
        text = " ".join(word.text for word in inside[index:])
        if not _speech_score(text)["standalone"]:
            continue
        result.append({
            **phrase, "start": inside[index].start, "text": text,
            "word_boundary_trim": True, "removed_lead_words": removed,
        })
    return result


def _remove_orphan_duplicate_ranges(
    transcript: Transcript, ranges: list[dict[str, float]],
) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
    cleaned: list[dict[str, float]] = []
    removed: list[dict[str, Any]] = []
    previous_tokens: set[str] = set()
    for item in ranges:
        range_words = _words_in_ranges(transcript, [item])
        tokens = _tokens(" ".join(word.text for word in range_words))
        duration = float(item["source_end"]) - float(item["source_start"])
        duplicate_fragment = bool(cleaned and duration <= 1.05 and len(tokens) <= 2 and tokens and set(tokens).issubset(previous_tokens))
        if duplicate_fragment:
            removed.append({**item, "text": " ".join(word.text for word in range_words), "reason": "orphan duplicate fragment at a retake boundary"})
            continue
        cleaned.append(item)
        if tokens:
            previous_tokens = set(tokens)
    return cleaned, removed


def _load_cv2():
    try:
        import cv2  # type: ignore
        return cv2
    except ImportError:
        local = Path(__file__).resolve().parent.parent / ".tools" / "opencv"
        if local.is_dir() and str(local) not in sys.path:
            sys.path.insert(0, str(local))
        try:
            import cv2  # type: ignore
            return cv2
        except ImportError:
            return None


class _VisualProbe:
    def __init__(self, video: Path, rotation: int, max_width: int) -> None:
        self.cv2 = _load_cv2()
        self.capture = None
        self.rotation = rotation
        self.max_width = max_width
        self.face = None
        self.eyes = None
        self.yunet = None
        if self.cv2 is None:
            return
        cascade_data = getattr(getattr(self.cv2, "data", None), "haarcascades", None)
        root = Path(cascade_data) if cascade_data else Path(self.cv2.__file__).resolve().parent / "data"
        self.face = self.cv2.CascadeClassifier(str(root / "haarcascade_frontalface_alt2.xml"))
        self.eyes = self.cv2.CascadeClassifier(str(root / "haarcascade_eye_tree_eyeglasses.xml"))
        model = Path(__file__).resolve().parent.parent / "assets" / "models" / "yunet" / "face_detection_yunet_2023mar.onnx"
        if model.is_file() and hasattr(self.cv2, "FaceDetectorYN_create"):
            try:
                self.yunet = self.cv2.FaceDetectorYN_create(str(model), "", (320, 320), 0.72, 0.3, 5000)
            except Exception:
                self.yunet = None
        self.capture = self.cv2.VideoCapture(str(video))
        auto = getattr(self.cv2, "CAP_PROP_ORIENTATION_AUTO", None)
        if self.capture.isOpened() and auto is not None:
            self.capture.set(auto, 1)

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()

    def frame(self, timestamp: float) -> dict[str, Any]:
        if self.capture is None or not self.capture.isOpened() or self.face is None or self.face.empty():
            return {"time": round(timestamp, 3), "available": False}
        cv2 = self.cv2
        self.capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp) * 1000)
        ok, frame = self.capture.read()
        if not ok:
            return {"time": round(timestamp, 3), "available": False}
        height, width = frame.shape[:2]
        if abs(self.rotation) % 180 == 90 and width > height:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE if self.rotation < 0 else cv2.ROTATE_90_CLOCKWISE)
            height, width = frame.shape[:2]
        if width > self.max_width:
            scale = self.max_width / width
            frame = cv2.resize(frame, (self.max_width, max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
            height, width = frame.shape[:2]
        gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        blur_value = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        landmark_row = None
        faces = []
        if self.yunet is not None:
            try:
                self.yunet.setInputSize((width, height))
                _, detections = self.yunet.detect(frame)
                if detections is not None and len(detections):
                    landmark_row = max(detections, key=lambda item: float(item[2]) * float(item[3]))
                    faces = [(int(landmark_row[0]), int(landmark_row[1]), int(landmark_row[2]), int(landmark_row[3]))]
            except Exception:
                landmark_row = None
        if not faces:
            faces = list(self.face.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(42, 42)))
        if not len(faces):
            return {"time": round(timestamp, 3), "available": True, "face": False, "blur": round(blur_value, 2), "frame_usability": round(min(1.0, blur_value / 110.0) * 0.35, 3)}
        x, y, fw, fh = max(faces, key=lambda item: item[2] * item[3])
        cx, cy = (x + fw / 2) / width, (y + fh / 2) / height
        inside = 1.0 if 0.08 <= cx <= 0.92 and 0.08 <= cy <= 0.82 else 0.45
        size_score = max(0.0, min(1.0, (fw / width - 0.10) / 0.14))
        eye_values: list[tuple[int, int, int, int]] = []
        downward_probability = 0.0
        if landmark_row is not None:
            right_eye = (float(landmark_row[4]), float(landmark_row[5]))
            left_eye = (float(landmark_row[6]), float(landmark_row[7]))
            nose = (float(landmark_row[8]), float(landmark_row[9]))
            mouth_right = (float(landmark_row[10]), float(landmark_row[11]))
            mouth_left = (float(landmark_row[12]), float(landmark_row[13]))
            eye_mid = ((right_eye[0] + left_eye[0]) / 2, (right_eye[1] + left_eye[1]) / 2)
            mouth_mid = ((mouth_right[0] + mouth_left[0]) / 2, (mouth_right[1] + mouth_left[1]) / 2)
            facial_mid_x = (eye_mid[0] + mouth_mid[0]) / 2
            yaw_proxy = abs(nose[0] - facial_mid_x) / max(1.0, fw)
            roll_proxy = abs(right_eye[1] - left_eye[1]) / max(1.0, fw)
            vertical_span = max(1.0, mouth_mid[1] - eye_mid[1])
            nose_ratio = (nose[1] - eye_mid[1]) / vertical_span
            pitch_proxy = abs(nose_ratio - 0.52)
            # This is a pose proxy, not eye tracking.  It becomes useful only
            # when aggregated over a sustained temporal window.
            downward_probability = max(0.0, min(1.0, (nose_ratio - 0.54) / 0.24))
            gaze = max(0.0, 1.0 - yaw_proxy / 0.16 - roll_proxy / 0.11 - pitch_proxy / 0.34)
            eye_confidence = float(landmark_row[14]) if len(landmark_row) > 14 else 0.9
            pose_method = "yunet_5_landmarks"
        else:
            if self.eyes is not None and not self.eyes.empty():
                eye_values = list(self.eyes.detectMultiScale(gray[y:y + max(1, int(fh * 0.62)), x:x + fw], scaleFactor=1.08, minNeighbors=4, minSize=(10, 10)))
            eye_values = sorted(eye_values, key=lambda item: item[2] * item[3], reverse=True)[:2]
        if landmark_row is None and len(eye_values) >= 2:
            centers = sorted([(ex + ew / 2, ey + eh / 2) for ex, ey, ew, eh in eye_values])
            eye_mid_x = (centers[0][0] + centers[1][0]) / 2
            yaw_proxy = abs(eye_mid_x - fw / 2) / max(1.0, fw)
            roll_proxy = abs(centers[0][1] - centers[1][1]) / max(1.0, fw)
            gaze = max(0.0, 1.0 - yaw_proxy / 0.18 - roll_proxy / 0.13)
            eye_confidence = 0.62
            pose_method = "haar_eye_proxy"
        elif landmark_row is None and len(eye_values) == 1:
            gaze, eye_confidence, pose_method, downward_probability = 0.42, 0.30, "single_eye_low_confidence", 0.0
        elif landmark_row is None:
            gaze, eye_confidence, pose_method, downward_probability = 0.30, 0.12, "face_box_only", 0.0
        blur_score = max(0.0, min(1.0, blur_value / 105.0))
        usability = blur_score * 0.34 + inside * 0.24 + size_score * 0.16 + gaze * 0.26
        return {
            "time": round(timestamp, 3), "available": True, "face": True,
            "x": round(cx, 4), "y": round(cy, 4), "w": round(fw / width, 4), "h": round(fh / height, 4),
            "blur": round(blur_value, 2), "blur_score": round(blur_score, 3),
            "gaze_readiness": round(gaze, 3), "eye_confidence": round(eye_confidence, 3),
            "head_pose_readiness": round(gaze, 3), "pose_method": pose_method,
            "downward_gaze_probability": round(downward_probability, 3),
            "frame_usability": round(usability, 3),
        }

    def window(self, timestamp: float, config: EditorialQualityConfig, *, before: bool = False) -> dict[str, Any]:
        count = max(3, round(config.sample_window / max(0.1, config.sample_step)))
        offsets = [-(count - index) * config.sample_step for index in range(count)] if before else [index * config.sample_step for index in range(count)]
        samples = [self.frame(max(0.0, timestamp + offset)) for offset in offsets]
        available = [item for item in samples if item.get("available")]
        faces = [item for item in available if item.get("face")]
        if not available:
            return {"available": False, "samples": samples}
        face_presence = len(faces) / len(available)
        gaze = sum(float(item.get("gaze_readiness", 0.25)) for item in faces) / max(1, len(faces))
        usability = sum(float(item.get("frame_usability", 0)) for item in available) / len(available)
        if len(faces) >= 2:
            x_values, y_values = [float(item["x"]) for item in faces], [float(item["y"]) for item in faces]
            w_values = [float(item["w"]) for item in faces]
            movement = (max(x_values) - min(x_values)) + (max(y_values) - min(y_values)) + (max(w_values) - min(w_values)) * 0.7
            stability = max(0.0, min(1.0, 1.0 - movement * 4.2))
        else:
            stability = 0.35 if faces else 0.0
        first = available[0]
        first_readiness = (
            (0.30 if first.get("face") else 0.0)
            + float(first.get("gaze_readiness", 0.0)) * 0.34
            + float(first.get("frame_usability", 0.0)) * 0.36
        )
        early = sum(float(item.get("frame_usability", 0)) for item in available[:2]) / max(1, len(available[:2]))
        late = sum(float(item.get("frame_usability", 0)) for item in available[-2:]) / max(1, len(available[-2:]))
        transition = max(0.0, late - early)
        visual = face_presence * 0.18 + gaze * 0.18 + stability * 0.16 + usability * 0.20 + first_readiness * 0.28 - transition * 0.22
        return {
            "available": True, "samples": samples, "face_presence": round(face_presence, 3),
            "gaze_readiness": round(gaze, 3), "pose_stability": round(stability, 3),
            "frame_usability": round(usability, 3), "visual_readiness": round(visual, 3),
            "first_frame_readiness": round(first_readiness, 3), "transition_score": round(transition, 3),
        }


def _trim_ranges(ranges: Sequence[dict[str, Any]], start: float, end: float) -> list[dict[str, float]]:
    result = []
    for item in ranges:
        left, right = max(start, float(item["source_start"])), min(end, float(item["source_end"]))
        if right - left >= 0.02:
            result.append({"source_start": round(left, 3), "source_end": round(right, 3)})
    return result


def _all_words(transcript: Transcript) -> list[TranscriptWord]:
    return [word for segment in transcript.segments for word in segment.words]


def _phrases_in_ranges(transcript: Transcript, ranges: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in ranges:
        words = _words_in_window(transcript, float(item["source_start"]), float(item["source_end"]))
        words = [
            word for word in words
            if word.start >= float(item["source_start"]) - 0.02
            and word.end <= float(item["source_end"]) + 0.02
        ]
        result.extend(_phrases(words))
    return result


def _runs(samples: Sequence[dict[str, Any]], predicate, step: float) -> list[dict[str, float]]:
    result: list[dict[str, float]] = []
    current: list[dict[str, Any]] = []
    for sample in samples:
        if predicate(sample):
            if current and float(sample["time"]) - float(current[-1]["time"]) > step * 1.7:
                result.append({
                    "start": float(current[0]["time"]),
                    "end": float(current[-1]["time"]) + step,
                    "duration": float(current[-1]["time"]) - float(current[0]["time"]) + step,
                })
                current = []
            current.append(sample)
        elif current:
            result.append({
                "start": float(current[0]["time"]),
                "end": float(current[-1]["time"]) + step,
                "duration": float(current[-1]["time"]) - float(current[0]["time"]) + step,
            })
            current = []
    if current:
        result.append({
            "start": float(current[0]["time"]),
            "end": float(current[-1]["time"]) + step,
            "duration": float(current[-1]["time"]) - float(current[0]["time"]) + step,
        })
    return [{key: round(value, 3) for key, value in item.items()} for item in result]


def _performance_quality(
    probe: _VisualProbe, phrase: dict[str, Any], transcript: Transcript,
    config: EditorialQualityConfig,
) -> dict[str, Any]:
    start, end = float(phrase["start"]), float(phrase["end"])
    step = max(0.20, float(config.internal_sample_step))
    count = max(2, int((end - start) / step) + 1)
    times = [min(end - 0.02, start + 0.04 + index * step) for index in range(count)]
    times = sorted(set(round(max(start, value), 3) for value in times if value <= end))
    samples = [probe.frame(value) for value in times]
    available = [item for item in samples if item.get("available")]
    faces = [item for item in available if item.get("face")]
    face_presence = len(faces) / max(1, len(available))
    camera_engagement = sum(float(item.get("gaze_readiness", 0.0)) for item in faces) / max(1, len(faces))
    head_pose_quality = sum(float(item.get("head_pose_readiness", 0.0)) for item in faces) / max(1, len(faces))
    gaze_quality = camera_engagement
    frame_usability = sum(float(item.get("frame_usability", 0.0)) for item in available) / max(1, len(available))
    blur_quality = sum(float(item.get("blur_score", 0.0)) for item in available) / max(1, len(available))
    if len(faces) >= 2:
        movement = sum(
            abs(float(right.get("x", 0.5)) - float(left.get("x", 0.5)))
            + abs(float(right.get("y", 0.5)) - float(left.get("y", 0.5)))
            + abs(float(right.get("w", 0.2)) - float(left.get("w", 0.2))) * 0.6
            for left, right in zip(faces, faces[1:])
        ) / max(1, len(faces) - 1)
        pose_stability = max(0.0, min(1.0, 1.0 - movement * 8.0))
    else:
        pose_stability = 0.35 if faces else 0.0
    words = _words_in_window(transcript, start, end)
    probabilities = [float(word.probability) for word in words if word.probability is not None]
    delivery_confidence = sum(probabilities) / len(probabilities) if probabilities else 0.5
    speech = _speech_score(str(phrase.get("text", "")))
    speech_quality = max(0.0, min(1.0, float(speech["score"]) * 0.56 + delivery_confidence * 0.44))
    semantic_completeness = (float(bool(speech["complete"])) * 0.55 + float(bool(speech["standalone"])) * 0.45)
    first_last = [item for item in (available[:1] + available[-1:]) if item]
    transition_risk = 1.0 - sum(float(item.get("frame_usability", 0.0)) for item in first_last) / max(1, len(first_last))
    performance = (
        camera_engagement * 0.20 + head_pose_quality * 0.11 + gaze_quality * 0.09
        + pose_stability * 0.12 + frame_usability * 0.13 + blur_quality * 0.07
        + speech_quality * 0.16 + semantic_completeness * 0.08
        + (1.0 - transition_risk) * 0.04
    )
    off_camera_runs = _runs(
        available,
        lambda item: not item.get("face") or float(item.get("gaze_readiness", 0.0)) < config.internal_gaze_threshold,
        step,
    )
    downward_runs = _runs(
        available,
        lambda item: bool(item.get("face"))
        and float(item.get("eye_confidence", 0.0)) >= 0.55
        and float(item.get("downward_gaze_probability", 0.0)) >= config.downward_gaze_threshold,
        step,
    )
    sustained_off = [item for item in off_camera_runs if item["duration"] >= config.sustained_bad_min_seconds]
    sustained_down = [item for item in downward_runs if item["duration"] >= config.sustained_downward_min_seconds]
    return {
        "performance_quality": round(max(0.0, min(1.0, performance)), 3),
        "camera_engagement": round(camera_engagement, 3),
        "head_pose_quality": round(head_pose_quality, 3),
        "gaze_quality": round(gaze_quality, 3),
        "delivery_confidence": round(delivery_confidence, 3),
        "pose_stability": round(pose_stability, 3),
        "frame_stability": round(pose_stability, 3),
        "frame_usability": round(frame_usability, 3),
        "motion_blur_quality": round(blur_quality, 3),
        "speech_quality": round(speech_quality, 3),
        "semantic_completeness": round(semantic_completeness, 3),
        "transition_risk": round(max(0.0, min(1.0, transition_risk)), 3),
        "face_presence": round(face_presence, 3),
        "sample_count": len(samples),
        "samples": samples,
        "sustained_off_camera": sustained_off,
        "sustained_downward_gaze": sustained_down,
    }


def _overlaps_ranges(start: float, end: float, ranges: Sequence[dict[str, Any]]) -> bool:
    return any(start < float(item["source_end"]) and end > float(item["source_start"]) for item in ranges)


def _splice_range(
    ranges: Sequence[dict[str, Any]], target_start: float, target_end: float,
    replacement: dict[str, float] | None, minimum_keep: float,
) -> list[dict[str, float]] | None:
    output: list[dict[str, float]] = []
    changed = False
    for item in ranges:
        left, right = float(item["source_start"]), float(item["source_end"])
        if target_end <= left or target_start >= right:
            output.append({"source_start": round(left, 3), "source_end": round(right, 3)})
            continue
        changed = True
        before, after = target_start - left, right - target_end
        if 0.02 < before < minimum_keep or 0.02 < after < minimum_keep:
            return None
        if before >= minimum_keep:
            output.append({"source_start": round(left, 3), "source_end": round(target_start, 3)})
        if replacement:
            output.append({"source_start": round(replacement["source_start"], 3), "source_end": round(replacement["source_end"], 3)})
        if after >= minimum_keep:
            output.append({"source_start": round(target_end, 3), "source_end": round(right, 3)})
    return output if changed else None


def _output_coordinates(ranges: Sequence[dict[str, Any]], source_start: float, source_end: float) -> dict[str, float] | None:
    cursor = 0.0
    for item in ranges:
        left, right = float(item["source_start"]), float(item["source_end"])
        if source_start >= left - 0.02 and source_end <= right + 0.02:
            return {
                "start": round(cursor + max(0.0, source_start - left), 3),
                "end": round(cursor + min(right - left, source_end - left), 3),
            }
        cursor += right - left
    return None


def _internal_editorial_pass(
    probe: _VisualProbe, transcript: Transcript, semantic_ranges: Sequence[dict[str, Any]],
    initial_ranges: list[dict[str, float]], config: EditorialQualityConfig,
) -> dict[str, Any]:
    if not config.internal_enabled or not hasattr(probe, "frame"):
        return {"ranges": initial_ranges, "actions": [], "candidates": [], "warnings": [], "summary": {"enabled": False}}
    phrases = _phrases_in_ranges(transcript, initial_ranges)
    all_phrases = _phrases(_all_words(transcript))
    ranges = [dict(item) for item in initial_ranges]
    actions: list[dict[str, Any]] = []
    replacement_candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    previous_text = ""
    action_count = 0
    for phrase in phrases:
        metrics = _performance_quality(probe, phrase, transcript, config)
        # Looking away from the lens can be an intentional visual action (for
        # example reading a contract or demonstrating an object).  Do not
        # classify that as a bad take when delivery remains complete and
        # confident, the pose/frame are stable, and there is no sustained
        # downward-gaze failure.  Truly weak/off-camera takes still fail these
        # conservative gates and continue through replacement/review logic.
        intentional_visual_delivery = (
            bool(metrics["sustained_off_camera"])
            and not bool(metrics["sustained_downward_gaze"])
            and float(metrics["speech_quality"]) >= 0.74
            and float(metrics["semantic_completeness"]) >= 0.90
            and float(metrics["delivery_confidence"]) >= 0.76
            and float(metrics["pose_stability"]) >= 0.86
            and float(metrics["frame_usability"]) >= 0.64
            and float(metrics["motion_blur_quality"]) >= 0.84
        )
        weak = (
            metrics["performance_quality"] < config.min_internal_performance
            and bool(metrics["sustained_off_camera"] or metrics["sustained_downward_gaze"])
            and not intentional_visual_delivery
        )
        action_type, confidence, reason = (
            "KEEP", 0.86 if intentional_visual_delivery else 0.82,
            "intentional visual/prop delivery with stable speech and pose" if intentional_visual_delivery
            else "natural delivery variation within tolerance",
        )
        source_start, source_end = float(phrase["start"]), float(phrase["end"])
        replacement: dict[str, Any] | None = None
        if weak and action_count < config.max_internal_actions:
            target_text = str(phrase.get("text", ""))
            candidates: list[dict[str, Any]] = []
            for candidate in all_phrases:
                candidate_start, candidate_end = float(candidate["start"]), float(candidate["end"])
                if _overlaps_ranges(candidate_start, candidate_end, semantic_ranges):
                    continue
                similarity = _similarity(target_text, str(candidate.get("text", "")))
                if similarity < config.min_take_similarity:
                    continue
                candidate_speech = _speech_score(str(candidate.get("text", "")))
                if not candidate_speech["standalone"] or _semantic_coverage(target_text, str(candidate.get("text", ""))) < 0.72:
                    continue
                candidate_metrics = _performance_quality(probe, candidate, transcript, config)
                gain = float(candidate_metrics["performance_quality"]) - float(metrics["performance_quality"])
                replacement_confidence = max(0.0, min(0.98, similarity * 0.50 + candidate_metrics["performance_quality"] * 0.34 + min(0.14, max(0.0, gain))))
                candidate_value = {
                    "source_range": {"start": round(candidate_start, 3), "end": round(candidate_end, 3)},
                    "text": candidate.get("text", ""), "semantic_similarity": round(similarity, 3),
                    "speech_completeness": candidate_metrics["semantic_completeness"],
                    "performance_quality": candidate_metrics["performance_quality"],
                    "performance_gain": round(gain, 3), "replacement_confidence": round(replacement_confidence, 3),
                    "reason": "semantically equivalent raw-session take with stronger sustained delivery",
                }
                candidates.append({**candidate_value, "_metrics": candidate_metrics})
            candidates.sort(key=lambda item: (float(item["replacement_confidence"]), float(item["performance_gain"])), reverse=True)
            replacement_candidates.extend([{key: value for key, value in item.items() if key != "_metrics"} for item in candidates[:3]])
            best = candidates[0] if candidates else None
            if (
                best and float(best["performance_gain"]) >= config.min_take_performance_gain
                and float(best["replacement_confidence"]) >= config.min_replacement_confidence
            ):
                candidate_range = {
                    "source_start": float(best["source_range"]["start"]),
                    "source_end": float(best["source_range"]["end"]),
                }
                updated = _splice_range(ranges, source_start, source_end, candidate_range, config.min_kept_shot_seconds)
                if updated:
                    ranges, replacement = updated, best
                    action_type, confidence, reason = "REPLACE_TAKE", float(best["replacement_confidence"]), str(best["reason"])
                    action_count += 1
            if replacement is None:
                speech = _speech_score(target_text)
                target_tokens = _tokens(target_text)
                filler_ratio = sum(token in LEAD_INS for token in target_tokens) / max(1, len(target_tokens))
                duplicate = _similarity(previous_text, target_text) >= 0.80 if previous_text else False
                removable = (
                    (speech["technical"] or filler_ratio >= 0.55 or duplicate)
                    and source_end - source_start >= config.min_safe_internal_cut_seconds
                    and bool(speech["complete"] or target_text.rstrip().endswith((".", "!", "?", ";")))
                )
                updated = _splice_range(ranges, source_start, source_end, None, config.min_kept_shot_seconds) if removable else None
                if updated:
                    ranges = updated
                    action_type, confidence, reason = "TRIM", 0.78, "weak complete transitional/filler phrase at a speech-safe boundary"
                    action_count += 1
                else:
                    action_type, confidence = "REVIEW_REQUIRED", round(max(0.55, 1.0 - float(metrics["performance_quality"])), 3)
                    reason = "important continuous speech has sustained weak delivery and no safe equivalent replacement"
                    action_count += 1
                    warnings.append("poor_internal_performance")
                    if metrics["sustained_downward_gaze"]:
                        warnings.append("sustained_downward_gaze")
                    if metrics["sustained_off_camera"]:
                        warnings.append("weak_camera_engagement")
                    if float(metrics["transition_risk"]) >= 0.55:
                        warnings.append("bad_transition_frame")
        replacement_range = replacement.get("source_range") if replacement else None
        coordinate_source_start = float(replacement_range["start"]) if replacement_range else source_start
        coordinate_source_end = float(replacement_range["end"]) if replacement_range else source_end
        actions.append({
            "type": action_type,
            "source_coordinates": {"start": round(source_start, 3), "end": round(source_end, 3)},
            "replacement_source_coordinates": replacement_range,
            "output_coordinates": _output_coordinates(ranges, coordinate_source_start, coordinate_source_end),
            "text": phrase.get("text", ""), "confidence": round(float(confidence), 3),
            "reason": reason, "performance": metrics,
        })
        previous_text = str(phrase.get("text", ""))
    # Reject editing patterns that would create a burst of micro shots.  Since
    # actions are phrase-boundary based, this is a final defensive cadence gate.
    modified = sorted(
        (item for item in actions if item["type"] in {"TRIM", "REPLACE_TAKE"}),
        key=lambda item: float(item["source_coordinates"]["start"]),
    )
    for left, right in zip(modified, modified[1:]):
        if float(right["source_coordinates"]["start"]) - float(left["source_coordinates"]["end"]) < config.min_jump_cut_gap_seconds:
            warnings.append("bad_transition_frame")
    for action in actions:
        replacement_range = action.get("replacement_source_coordinates")
        coordinates = replacement_range or action["source_coordinates"]
        action["output_coordinates"] = _output_coordinates(
            ranges, float(coordinates["start"]), float(coordinates["end"]),
        )
        if action["type"] == "TRIM" and action["output_coordinates"] is None:
            cursor = 0.0
            cut_at = float(action["source_coordinates"]["start"])
            for item in ranges:
                left, right = float(item["source_start"]), float(item["source_end"])
                if right <= cut_at:
                    cursor += right - left
            action["output_coordinates"] = {"start": round(cursor, 3), "end": round(cursor, 3)}
    review = sum(item["type"] == "REVIEW_REQUIRED" for item in actions)
    return {
        "ranges": ranges, "actions": actions, "candidates": replacement_candidates,
        "warnings": sorted(set(warnings)),
        "summary": {
            "enabled": True, "segments_analyzed": len(actions),
            "internal_trims": sum(item["type"] == "TRIM" for item in actions),
            "take_replacements": sum(item["type"] == "REPLACE_TAKE" for item in actions),
            "review_required": review,
            "sustained_off_camera": sum(bool(item["performance"]["sustained_off_camera"]) for item in actions),
            "sustained_downward_gaze": sum(bool(item["performance"]["sustained_downward_gaze"]) for item in actions),
            "average_performance_quality": round(sum(float(item["performance"]["performance_quality"]) for item in actions) / max(1, len(actions)), 3),
        },
    }


def build_editorial_quality_plan(
    video: Path, transcript: Transcript, episode: dict[str, Any], source_duration: float,
    config: EditorialQualityConfig, *, rotation: int = 0, conservative: bool = False,
) -> dict[str, Any]:
    semantic_ranges = [dict(item) for item in episode.get("selected_ranges", [])]
    if not semantic_ranges:
        raise ValueError("Editorial Quality Gate requires semantic episode ranges")
    semantic_in = float(semantic_ranges[0]["source_start"])
    semantic_out = float(semantic_ranges[-1]["source_end"])
    words = _words_in_ranges(transcript, semantic_ranges)
    phrases = _phrases(words)
    initial_phrase = phrases[0] if phrases else {"start": semantic_in, "end": semantic_out, "text": ""}
    probe = _VisualProbe(video, rotation, config.detector_max_width)
    try:
        search_words = _words_in_window(
            transcript, max(0.0, semantic_in - config.alternate_take_search_seconds),
            min(source_duration, semantic_in + config.max_start_search_seconds),
        )
        base_phrases = [*_phrases(search_words), *_repeated_take_phrases(search_words)]
        search_phrases = []
        for phrase in base_phrases:
            search_phrases.append(phrase)
            search_phrases.extend(_word_boundary_alternatives(phrase, search_words, config))
        candidates = []
        seen_starts: set[float] = set()
        for phrase in [{**initial_phrase}, *search_phrases]:
            if float(phrase["start"]) - semantic_in > config.max_start_search_seconds:
                break
            if float(phrase["start"]) < semantic_in - config.alternate_take_search_seconds:
                continue
            start_key = round(float(phrase["start"]), 3)
            if start_key in seen_starts:
                continue
            seen_starts.add(start_key)
            speech = _speech_score(str(phrase["text"]))
            if phrase.get("repeated_take"):
                speech["complete"] = True
                speech["standalone"] = True
                speech["score"] = round(min(1.0, float(speech["score"]) + 0.14), 3)
            visual = probe.window(float(phrase["start"]), config)
            visual_score = float(visual.get("visual_readiness", 0.5 if not visual.get("available") else 0.0))
            start_readiness = speech["score"] * 0.42 + visual_score * 0.58
            candidates.append({
                **phrase, "speech_readiness": speech, "visual": visual,
                "start_readiness": round(start_readiness, 3),
                "semantic_similarity": round(_similarity(str(initial_phrase["text"]), str(phrase["text"])), 3),
                "semantic_coverage": round(_semantic_coverage(str(initial_phrase["text"]), str(phrase["text"])), 3),
            })
        if not candidates:
            candidates = [{**initial_phrase, "speech_readiness": _speech_score(str(initial_phrase["text"])), "visual": {"available": False}, "start_readiness": 0.5, "semantic_similarity": 1.0}]
        before = min(candidates, key=lambda item: abs(float(item["start"]) - semantic_in))
        chosen = before
        reason = None
        warnings: list[str] = []
        for candidate in candidates[1:]:
            boundary_shift = float(candidate["start"]) - semantic_in
            trim = max(0.0, boundary_shift)
            # Similarity alone treats a truncated subset as a perfect match.
            # Coverage prevents an unfinished retake from winning only because
            # its opening words and visual pose look cleaner.
            required_coverage = max(0.74, float(before.get("semantic_coverage", 1.0)) - 0.15)
            duplicate_take = float(candidate["semantic_similarity"]) >= 0.64 and float(candidate.get("semantic_coverage", 0.0)) >= required_coverage
            short_safe_trim = 0.0 <= boundary_shift <= config.max_auto_lead_trim_seconds and bool(candidate["speech_readiness"]["standalone"])
            related_earlier_take = boundary_shift < 0 and float(candidate.get("semantic_coverage", 0.0)) >= required_coverage
            word_boundary_trim = bool(candidate.get("word_boundary_trim")) and trim <= config.max_visual_lead_trim_seconds and (boundary_shift >= 0 or related_earlier_take)
            score_gain = float(candidate["start_readiness"]) - float(before["start_readiness"])
            visual_gain = float(candidate["visual"].get("visual_readiness", 0.0)) - float(before["visual"].get("visual_readiness", 0.0))
            first_frame_gain = float(candidate["visual"].get("first_frame_readiness", 0.0)) - float(before["visual"].get("first_frame_readiness", 0.0))
            speech_gain = float(candidate["speech_readiness"]["score"]) - float(before["speech_readiness"]["score"])
            eligible = duplicate_take or short_safe_trim or word_boundary_trim
            if conservative:
                eligible = short_safe_trim and bool(before["speech_readiness"]["technical"] or before["speech_readiness"]["lead_words"])
            sufficient_gain = score_gain >= config.min_readiness_improvement or (duplicate_take and visual_gain >= 0.10 and score_gain >= 0.04) or (duplicate_take and speech_gain >= 0.14) or (word_boundary_trim and visual_gain >= 0.08 and score_gain >= -0.02) or (word_boundary_trim and first_frame_gain >= 0.05 and score_gain >= 0.0)
            if eligible and sufficient_gain and float(candidate["start_readiness"]) >= config.min_start_readiness:
                chosen_first = float(chosen["visual"].get("first_frame_readiness", 0.0))
                candidate_first = float(candidate["visual"].get("first_frame_readiness", 0.0))
                first_frame_upgrade = word_boundary_trim and candidate_first >= chosen_first + 0.045 and float(candidate["start_readiness"]) >= float(chosen["start_readiness"]) - 0.01
                if chosen is before or float(candidate["start_readiness"]) > float(chosen["start_readiness"]) + 0.03 or first_frame_upgrade:
                    chosen = candidate
                    reason = "VISUAL_NOT_READY" if word_boundary_trim else "RETAKE_BOUNDARY" if duplicate_take and abs(boundary_shift) > config.max_auto_lead_trim_seconds else "TECHNICAL_LEAD_IN" if before["speech_readiness"]["technical"] else "VISUAL_NOT_READY"
        confidence = min(0.96, 0.46 + abs(float(chosen["start_readiness"]) - float(before["start_readiness"])) * 1.2 + float(chosen["visual"].get("face_presence", 0.4)) * 0.25)
        if chosen is not before and confidence < config.min_editorial_confidence:
            chosen = before; reason = None
            warnings.append("START_QUALITY_WARNING")
        initial_visual = float(before["visual"].get("visual_readiness", 0.5))
        initial_gaze = float(before["visual"].get("gaze_readiness", 0.5))
        initial_first = float(before["visual"].get("first_frame_readiness", 0.5))
        if (float(before["start_readiness"]) < config.min_start_readiness or initial_visual < 0.60 or initial_first < 0.58) and chosen is before:
            warnings.extend(["START_QUALITY_WARNING", "SUBJECT_NOT_READY_AT_START"])
            if initial_gaze < 0.20:
                warnings.append("EXCESSIVE_OFF_CAMERA_START")

        selected_visual = float(chosen["visual"].get("visual_readiness", 0.5))
        selected_first = float(chosen["visual"].get("first_frame_readiness", 0.5))
        selected_gaze = float(chosen["visual"].get("gaze_readiness", 0.5))
        if selected_visual < 0.60 or selected_first < 0.58:
            warnings.extend(["START_QUALITY_WARNING", "SUBJECT_NOT_READY_AT_START"])
            if selected_gaze < 0.20:
                warnings.append("EXCESSIVE_OFF_CAMERA_START")

        editorial_in = float(chosen["start"])
        end_visual = probe.window(semantic_out, config, before=True)
        end_readiness = float(end_visual.get("visual_readiness", 0.5 if not end_visual.get("available") else 0.0))
        editorial_out = semantic_out
        end_reason = None
        final_text = str(phrases[-1]["text"] if phrases else "")
        final_speech = _speech_score(final_text)
        if final_speech["technical"] and len(phrases) >= 2:
            previous_end = float(phrases[-2]["end"])
            if semantic_out - previous_end <= config.max_end_trim_seconds:
                editorial_out, end_reason = previous_end, "POST_SPEECH_TAIL"
        elif final_speech["complete"]:
            # Small AAC/video tail protects the final consonant without retaining a new utterance.
            next_word = min((word.start for segment in transcript.segments for word in segment.words if word.start > semantic_out), default=source_duration)
            editorial_out = min(source_duration, semantic_out + config.tail_padding_seconds, next_word - 0.03)
            editorial_out = max(semantic_out, editorial_out)
            if editorial_out > semantic_out + 0.01:
                end_reason = "SAFE_TAIL_PADDING"
        if end_readiness < 0.46:
            warnings.append("WEAK_EPISODE_TAIL")

        chosen_outside_first_range = not (
            float(semantic_ranges[0]["source_start"]) <= editorial_in <= float(semantic_ranges[0]["source_end"])
        )
        if chosen is not before and float(chosen["semantic_similarity"]) >= 0.64 and chosen_outside_first_range:
            editorial_ranges = [{"source_start": round(editorial_in, 3), "source_end": round(float(chosen["end"]), 3)}]
            editorial_ranges.extend({"source_start": round(float(item["source_start"]), 3), "source_end": round(float(item["source_end"]), 3)} for item in semantic_ranges if float(item["source_start"]) > float(chosen["end"]) + 0.02)
        elif chosen is not before and float(chosen["semantic_similarity"]) >= 0.64:
            editorial_ranges = [{"source_start": round(editorial_in, 3), "source_end": round(float(chosen["end"]), 3)}]
            editorial_ranges.extend({"source_start": round(float(item["source_start"]), 3), "source_end": round(float(item["source_end"]), 3)} for item in semantic_ranges[1:])
        else:
            editorial_ranges = _trim_ranges(semantic_ranges, editorial_in, semantic_out)
        editorial_ranges, orphan_fragments = _remove_orphan_duplicate_ranges(transcript, editorial_ranges)
        if orphan_fragments and reason is None:
            reason = "RETAKE_BOUNDARY"
        if editorial_out > semantic_out and editorial_ranges:
            editorial_ranges[-1]["source_end"] = round(editorial_out, 3)
        internal = _internal_editorial_pass(
            probe, transcript, semantic_ranges, editorial_ranges, config,
        )
        editorial_ranges = internal["ranges"]
        warnings.extend(internal["warnings"])
        content_map = build_content_map(
            transcript, editorial_ranges,
            duplicate_threshold=config.semantic_duplicate_threshold,
            review_threshold=config.semantic_duplicate_review_threshold,
            minimum_keep=config.semantic_duplicate_min_keep_seconds,
        ) if config.semantic_duplicate_enabled else {
            "version": 1, "method": "disabled", "units": [], "actions": [],
            "selected_ranges": editorial_ranges, "warnings": [],
            "summary": {"units": 0, "kept": 0, "trimmed_duplicates": 0, "replacement_takes": 0, "review_required": 0},
        }
        editorial_ranges = content_map["selected_ranges"]
        warnings.extend(content_map.get("warnings", []))
        for action in internal["actions"]:
            replacement_range = action.get("replacement_source_coordinates")
            coordinates = replacement_range or action["source_coordinates"]
            action["output_coordinates"] = _output_coordinates(
                editorial_ranges, float(coordinates["start"]), float(coordinates["end"]),
            )
        for action in content_map.get("actions", []):
            coordinates = action.get("source_coordinates", {})
            action["output_coordinates"] = _output_coordinates(
                editorial_ranges, float(coordinates.get("start", 0)), float(coordinates.get("end", 0)),
            )
        for unit in content_map.get("units", []):
            unit["editorial_output_coordinates"] = _output_coordinates(
                editorial_ranges, float(unit.get("start", 0)), float(unit.get("end", 0)),
            )
        semantic_duration = sum(float(item["source_end"]) - float(item["source_start"]) for item in semantic_ranges)
        editorial_duration = sum(float(item["source_end"]) - float(item["source_start"]) for item in editorial_ranges)
        trim_amount = max(0.0, semantic_duration - editorial_duration)
        strong_opening = float(chosen["speech_readiness"]["score"]) * 0.60 + float(chosen["visual"].get("visual_readiness", 0.5)) * 0.40
        if "START_QUALITY_WARNING" in warnings:
            strong_opening = min(strong_opening, 0.58)
        return {
            "version": 3, "enabled": config.enabled, "method": "content_map_plus_semantic_duplicate_detection_plus_performance_timeline",
            "config": asdict(config), "episode_id": episode.get("episode_id"),
            "semantic_boundary": {"in": round(semantic_in, 3), "out": round(semantic_out, 3), "ranges": semantic_ranges},
            "editorial_boundary": {"in": round(editorial_in, 3), "out": round(editorial_out, 3), "ranges": editorial_ranges},
            "start": {
                "before": before, "after": chosen, "start_readiness": round(float(chosen["start_readiness"]), 3),
                "visual_readiness": chosen["visual"].get("visual_readiness"), "gaze_readiness": chosen["visual"].get("gaze_readiness"),
                "pose_stability": chosen["visual"].get("pose_stability"), "frame_usability": chosen["visual"].get("frame_usability"),
                "strong_opening": round(strong_opening, 3), "reason": reason,
            },
            "end": {"end_readiness": round(end_readiness, 3), "visual": end_visual, "reason": end_reason},
            "editorial_confidence": round(confidence, 3), "trimmed_seconds": round(trim_amount, 3),
            "warnings": sorted(set(warnings)),
            "decisions": list(dict.fromkeys([
                *(value for value in [reason, end_reason] if value),
                *(str(item["type"]) for item in internal["actions"] if item["type"] != "KEEP"),
            ])),
            "removed_fragments": orphan_fragments,
            "candidates": candidates,
            "performance_quality": internal["summary"],
            "content_map": content_map,
            "editorial_decisions": [*internal["actions"], *content_map.get("actions", [])],
            "editorial_internal_actions": internal["actions"],
            "take_replacement_candidates": internal["candidates"],
        }
    finally:
        probe.close()
