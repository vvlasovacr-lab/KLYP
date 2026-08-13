from __future__ import annotations

from typing import Any, Sequence

from .content_intelligence import analyze_content, select_style
from .semantic_analysis import EditingPlan


DIRECTOR_PROFILE_VERSION = 2


def select_director_profile(
    editing_plan: EditingPlan,
    words: Sequence[dict[str, Any]],
    duration: float,
    requested_profile: str = "AUTO",
    face_plan: dict[str, Any] | None = None,
    editorial_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Backward-compatible entry point for the new autonomous style layer."""
    decision = select_style(analyze_content(editing_plan, words, duration, face_plan, editorial_quality), requested_profile)
    decision["version"] = DIRECTOR_PROFILE_VERSION
    return decision
