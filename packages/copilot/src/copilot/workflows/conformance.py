"""Preset conformance assessment — validate telemetry against Scale_Preset bounds.

Compares a BehaviourProfile's telemetry against the expected_bounds defined
by a ScalePreset. Labels the profile as "conforming" or "drifted" with
per-metric pass/fail detail.

This module is deterministic — no LLM involvement.

Requirements: 16.1, 16.2, 16.3, 16.4
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from behaviour_profiles.comparison import _flatten_telemetry

if TYPE_CHECKING:
    from behaviour_profiles.models import BehaviourProfile
    from dsql_config.models import ScalePreset


class MetricConformance(BaseModel):
    """Per-metric conformance result."""

    metric: str
    observed_value: float
    lower_bound: float
    upper_bound: float
    result: Literal["pass", "fail"]
    detail: str = Field(description="Human-readable explanation of the result")


class ConformanceAssessment(BaseModel):
    """Complete conformance assessment for a profile against a preset."""

    preset_name: str
    profile_id: str
    profile_name: str
    label: Literal["conforming", "drifted"]
    metric_results: list[MetricConformance]
    summary: str = Field(description="Human-readable conformance summary")


def assess_conformance(
    profile: BehaviourProfile,
    preset: ScalePreset,
) -> ConformanceAssessment:
    """Compare profile telemetry against preset expected bounds.

    Args:
        profile: The BehaviourProfile to assess.
        preset: The ScalePreset whose expected_bounds define conformance.

    Returns:
        ConformanceAssessment with per-metric pass/fail and overall label.
    """
    if not preset.expected_bounds:
        return ConformanceAssessment(
            preset_name=preset.name,
            profile_id=profile.id,
            profile_name=profile.name,
            label="conforming",
            metric_results=[],
            summary=f"Preset '{preset.name}' has no expected bounds defined. "
            "Profile is considered conforming by default.",
        )

    flat_telemetry = _flatten_telemetry(profile)
    results: list[MetricConformance] = []

    for bound in preset.expected_bounds:
        agg = flat_telemetry.get(bound.metric)
        if agg is None:
            # Metric not found in profile telemetry — fail
            results.append(
                MetricConformance(
                    metric=bound.metric,
                    observed_value=0.0,
                    lower_bound=bound.lower,
                    upper_bound=bound.upper,
                    result="fail",
                    detail=f"Metric '{bound.metric}' not found in profile telemetry.",
                )
            )
            continue

        observed = agg.mean
        in_bounds = bound.lower <= observed <= bound.upper

        if in_bounds:
            results.append(
                MetricConformance(
                    metric=bound.metric,
                    observed_value=round(observed, 2),
                    lower_bound=bound.lower,
                    upper_bound=bound.upper,
                    result="pass",
                    detail=(
                        f"{bound.metric} = {observed:.2f} (within [{bound.lower}, {bound.upper}])"
                    ),
                )
            )
        else:
            direction = "below" if observed < bound.lower else "above"
            results.append(
                MetricConformance(
                    metric=bound.metric,
                    observed_value=round(observed, 2),
                    lower_bound=bound.lower,
                    upper_bound=bound.upper,
                    result="fail",
                    detail=(
                        f"{bound.metric} = {observed:.2f} "
                        f"is {direction} expected range [{bound.lower}, {bound.upper}]"
                    ),
                )
            )

    all_pass = all(r.result == "pass" for r in results)
    label: Literal["conforming", "drifted"] = "conforming" if all_pass else "drifted"
    summary = _build_conformance_summary(preset.name, profile.name, results, label)

    return ConformanceAssessment(
        preset_name=preset.name,
        profile_id=profile.id,
        profile_name=profile.name,
        label=label,
        metric_results=results,
        summary=summary,
    )


def _build_conformance_summary(
    preset_name: str,
    profile_name: str,
    results: list[MetricConformance],
    label: Literal["conforming", "drifted"],
) -> str:
    """Build a human-readable conformance summary."""
    failed = sum(1 for r in results if r.result == "fail")
    total = len(results)

    if label == "conforming":
        return (
            f"Profile '{profile_name}' conforms to preset '{preset_name}'. "
            f"All {total} metric(s) within expected bounds."
        )

    parts = [
        f"Profile '{profile_name}' has drifted from preset '{preset_name}'. "
        f"{failed}/{total} metric(s) out of range."
    ]
    for r in results:
        if r.result == "fail":
            parts.append(f"  FAIL: {r.detail}")

    return "\n".join(parts)
