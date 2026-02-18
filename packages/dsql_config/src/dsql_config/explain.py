"""Explain capability — deterministic, template-based explanations at three levels.

Level 1: explain-key — single parameter from registry metadata
Level 2: explain-preset — reasoning chain from SLO targets to resolved values
Level 3: explain-profile — full composition trace including overrides and guard rails

All output is template-based. No LLM involvement.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from copilot_core.types import ParameterClassification, ResolvedParameter  # noqa: TC001
from dsql_config.models import CompilationTrace, GuardRailResult  # noqa: TC001


class KeyExplanation(BaseModel):
    """Level 1: Explanation of a single parameter."""

    key: str
    classification: ParameterClassification
    value: int | float | str | bool
    description: str
    rationale: str
    source: Literal["preset", "modifier", "override", "derived", "default"]

    def to_text(self) -> str:
        return (
            f"Parameter: {self.key}\n"
            f"  Classification: {self.classification.value}\n"
            f"  Value: {self.value} (source: {self.source})\n"
            f"  Purpose: {self.description}\n"
            f"  Rationale: {self.rationale}"
        )

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


class LockedParam(BaseModel):
    """A safety parameter that is locked (auto-derived, not adopter-configurable)."""

    key: str
    value: int | float | str | bool
    reason: str


class PresetExplanation(BaseModel):
    """Level 2: Explanation of a preset's reasoning chain."""

    preset_name: str
    modifier: str | None
    slo_targets: list[ResolvedParameter]
    topology_derivation: list[str]
    locked_safety_params: list[LockedParam]
    reasoning_narrative: str

    def to_text(self) -> str:
        lines = [
            f"Preset: {self.preset_name}" + (f" + {self.modifier}" if self.modifier else ""),
            "",
            "SLO Targets:",
        ]
        for p in self.slo_targets:
            lines.append(f"  {p.key} = {p.value}")

        lines.append("")
        lines.append("Topology Derivation:")
        for step in self.topology_derivation:
            lines.append(f"  {step}")

        lines.append("")
        lines.append("Locked Safety Parameters:")
        for lp in self.locked_safety_params:
            lines.append(f"  {lp.key} = {lp.value}")
            lines.append(f"    Reason: {lp.reason}")

        lines.append("")
        lines.append("Reasoning:")
        lines.append(f"  {self.reasoning_narrative}")
        return "\n".join(lines)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


class OverrideDetail(BaseModel):
    """Detail of an override applied during compilation."""

    key: str
    preset_value: int | float | str | bool
    override_value: int | float | str | bool
    classification: ParameterClassification


class ProfileExplanation(BaseModel):
    """Level 3: Full composition explanation of a compiled profile."""

    base_preset: str
    modifier: str | None
    overrides_applied: list[OverrideDetail]
    guard_rails_fired: list[GuardRailResult]
    derivation_chains: list[CompilationTrace]
    composition_narrative: str

    def to_text(self) -> str:
        lines = [
            f"Profile compiled from preset '{self.base_preset}'"
            + (f" with modifier '{self.modifier}'" if self.modifier else ""),
            "",
        ]

        if self.overrides_applied:
            lines.append(f"Overrides ({len(self.overrides_applied)}):")
            for o in self.overrides_applied:
                lines.append(
                    f"  {o.key}: {o.preset_value} → {o.override_value} [{o.classification.value}]"
                )
            lines.append("")

        if self.guard_rails_fired:
            lines.append(f"Guard Rails ({len(self.guard_rails_fired)}):")
            for gr in self.guard_rails_fired:
                lines.append(f"  [{gr.severity}] {gr.rule_name}: {gr.message}")
            lines.append("")

        lines.append(f"Derivation chains ({len(self.derivation_chains)} parameters):")
        for chain in self.derivation_chains:
            if chain.source != "default":
                lines.append(
                    f"  {chain.parameter_key}: "
                    f"{chain.base_value} → {chain.final_value} "
                    f"({chain.source})"
                )
                if chain.derivation_chain:
                    lines.append(f"    Chain: {' → '.join(chain.derivation_chain)}")

        lines.append("")
        lines.append("Composition:")
        lines.append(f"  {self.composition_narrative}")
        return "\n".join(lines)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)
