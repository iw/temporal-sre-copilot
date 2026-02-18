"""Config Compiler — resolves presets, applies modifiers and overrides, emits artifacts.

The compilation pipeline:
1. Resolve preset defaults for SLO and Topology parameters
2. Apply workload modifier adjustments
3. Apply adopter overrides
4. Derive Safety parameters from safety derivation rules
5. Derive Tuning parameters from tuning derivation rules
6. Build ConfigProfile
7. Run guard rails
8. Generate compilation trace and why section
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from copilot_core.types import (
    ParameterClassification,
    ParameterOverrides,
    ResolvedParameter,
)
from dsql_config.models import (
    CompilationResult,
    CompilationTrace,
    ConfigProfile,
    DSQLPluginConfig,
    PresetDescription,
    PresetSummary,
    RenderedSnippet,
)
from dsql_config.modifiers import MODIFIERS, WorkloadModifier
from dsql_config.presets import PRESETS, ScalePreset

if TYPE_CHECKING:
    from dsql_config.explain import KeyExplanation, PresetExplanation, ProfileExplanation
    from dsql_config.guard_rails import GuardRailEngine
    from dsql_config.registry import ParameterRegistry


class UnknownPresetError(ValueError):
    def __init__(self, name: str) -> None:
        available = ", ".join(PRESETS.keys())
        super().__init__(f"Unknown preset '{name}'. Available: {available}")


class UnknownModifierError(ValueError):
    def __init__(self, name: str) -> None:
        available = ", ".join(MODIFIERS.keys())
        super().__init__(f"Unknown modifier '{name}'. Available: {available}")


class UnknownParameterError(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(f"Unknown parameter key '{key}'")


class ConstraintViolationError(ValueError):
    pass


class CompilationError(Exception):
    """Raised when guard rails produce errors that halt compilation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Compilation failed with {len(errors)} error(s): {'; '.join(errors)}")


class ConfigCompiler:
    """Compiles a Scale Preset + optional modifier + overrides into a full ConfigProfile."""

    def __init__(
        self,
        registry: ParameterRegistry,
        *,
        guard_rail_engine: GuardRailEngine | None = None,
        temporal_server_version: str = "1.26.2",
        dsql_plugin_version: str = "1.26.2",
        compiler_version: str = "0.1.0",
    ) -> None:
        self._registry = registry
        self._guard_rail_engine = guard_rail_engine
        self._temporal_server_version = temporal_server_version
        self._dsql_plugin_version = dsql_plugin_version
        self._compiler_version = compiler_version

    def compile(
        self,
        preset: str,
        *,
        modifier: str | None = None,
        overrides: ParameterOverrides | None = None,
        sdk: str | None = None,
        platform: str | None = None,
    ) -> CompilationResult:
        scale_preset = PRESETS.get(preset)
        if scale_preset is None:
            raise UnknownPresetError(preset)

        workload_modifier: WorkloadModifier | None = None
        if modifier is not None:
            workload_modifier = MODIFIERS.get(modifier)
            if workload_modifier is None:
                raise UnknownModifierError(modifier)

        if overrides is None:
            overrides = ParameterOverrides()

        # Validate override keys exist in registry
        for key in overrides.values:
            if self._registry.get(key) is None:
                raise UnknownParameterError(key)

        # Validate override values against constraints
        for key, value in overrides.values.items():
            entry = self._registry.get(key)
            if entry and entry.constraints:
                c = entry.constraints
                if isinstance(value, (int, float)):
                    if c.min_value is not None and value < c.min_value:
                        raise ConstraintViolationError(
                            f"Override for '{key}' ({value}) is below minimum ({c.min_value})"
                        )
                    if c.max_value is not None and value > c.max_value:
                        raise ConstraintViolationError(
                            f"Override for '{key}' ({value}) exceeds maximum ({c.max_value})"
                        )
                if c.allowed_values is not None and value not in c.allowed_values:
                    raise ConstraintViolationError(
                        f"Override for '{key}' ({value}) not in allowed values: {c.allowed_values}"
                    )

        # Build resolved parameters and trace
        trace: list[CompilationTrace] = []
        resolved = self._resolve_all(scale_preset, workload_modifier, overrides, trace)

        from whenever import Instant

        profile = ConfigProfile(
            preset_name=preset,
            modifier=modifier,
            overrides=overrides,
            slo_params=resolved[ParameterClassification.SLO],
            topology_params=resolved[ParameterClassification.TOPOLOGY],
            safety_params=resolved[ParameterClassification.SAFETY],
            tuning_params=resolved[ParameterClassification.TUNING],
            temporal_server_version=self._temporal_server_version,
            dsql_plugin_version=self._dsql_plugin_version,
            compiled_at=str(Instant.now()),
            compiler_version=self._compiler_version,
        )

        # Run guard rails
        from dsql_config.guard_rails import GuardRailEngine

        engine = self._guard_rail_engine or GuardRailEngine()
        guard_rail_results = engine.evaluate(profile)

        errors = [r for r in guard_rail_results if r.severity == "error"]
        if errors:
            raise CompilationError([r.message for r in errors])

        # Generate outputs
        dynamic_config_yaml = self._emit_dynamic_config_yaml(profile)
        dsql_plugin_config = self._build_dsql_plugin_config(profile)
        why_section = self._generate_why_section(
            profile, scale_preset, workload_modifier, overrides
        )

        # Adapter rendering (placeholder — adapters wired in Task 5)
        sdk_snippets: list[RenderedSnippet] = []
        platform_snippets: list[RenderedSnippet] = []

        return CompilationResult(
            profile=profile,
            dynamic_config_yaml=dynamic_config_yaml,
            dsql_plugin_config=dsql_plugin_config,
            sdk_snippets=sdk_snippets,
            platform_snippets=platform_snippets,
            guard_rail_results=guard_rail_results,
            trace=trace,
            why_section=why_section,
        )

    def _resolve_all(
        self,
        preset: ScalePreset,
        modifier: WorkloadModifier | None,
        overrides: ParameterOverrides,
        trace: list[CompilationTrace],
    ) -> dict[ParameterClassification, list[ResolvedParameter]]:
        """Resolve all parameters from preset → modifier → overrides → derivations."""
        resolved: dict[ParameterClassification, list[ResolvedParameter]] = {
            c: [] for c in ParameterClassification
        }

        # Build a lookup of preset defaults
        preset_values: dict[str, int | float | str | bool] = {}
        for d in preset.slo_defaults:
            preset_values[d.key] = d.value
        for d in preset.topology_defaults:
            preset_values[d.key] = d.value

        # Resolve SLO parameters
        for entry in self._registry.list_by_classification(ParameterClassification.SLO):
            base_value = preset_values.get(entry.key, entry.default_value)
            final_value = overrides.values.get(entry.key, base_value)
            source = (
                "override"
                if entry.key in overrides.values
                else "preset"
                if entry.key in preset_values
                else "default"
            )
            resolved[ParameterClassification.SLO].append(
                ResolvedParameter(
                    key=entry.key,
                    value=final_value,
                    classification=ParameterClassification.SLO,
                    source=source,
                )
            )
            trace.append(
                CompilationTrace(
                    parameter_key=entry.key,
                    source=source,
                    base_value=base_value,
                    final_value=final_value,
                    derivation_chain=[
                        f"preset:{preset.name}"
                        if entry.key in preset_values
                        else "registry_default"
                    ],
                )
            )

        # Resolve Topology parameters (preset → modifier → override)
        for entry in self._registry.list_by_classification(ParameterClassification.TOPOLOGY):
            base_value = preset_values.get(entry.key, entry.default_value)
            chain = (
                [f"preset:{preset.name}"] if entry.key in preset_values else ["registry_default"]
            )

            # Apply modifier adjustment
            if modifier and entry.key in modifier.adjustments:
                base_value = modifier.adjustments[entry.key]
                chain.append(f"modifier:{modifier.name}")

            final_value = overrides.values.get(entry.key, base_value)
            source: str
            if entry.key in overrides.values:
                source = "override"
            elif modifier and entry.key in modifier.adjustments:
                source = "modifier"
            elif entry.key in preset_values:
                source = "preset"
            else:
                source = "default"

            resolved[ParameterClassification.TOPOLOGY].append(
                ResolvedParameter(
                    key=entry.key,
                    value=final_value,
                    classification=ParameterClassification.TOPOLOGY,
                    source=source,
                )
            )
            trace.append(
                CompilationTrace(
                    parameter_key=entry.key,
                    source=source,
                    base_value=preset_values.get(entry.key, entry.default_value),
                    final_value=final_value,
                    derivation_chain=chain,
                )
            )

        # Resolve Safety parameters from derivation rules
        # Build a context dict for expression evaluation
        derived_context: dict[str, int | float | str | bool] = {}
        for rule in preset.safety_derivations:
            value = self._evaluate_expression(rule.expression, derived_context)
            # Allow override of safety params too
            final_value = overrides.values.get(rule.key, value)
            source = "override" if rule.key in overrides.values else "derived"
            derived_context[rule.key] = final_value
            resolved[ParameterClassification.SAFETY].append(
                ResolvedParameter(
                    key=rule.key,
                    value=final_value,
                    classification=ParameterClassification.SAFETY,
                    source=source,
                )
            )
            trace.append(
                CompilationTrace(
                    parameter_key=rule.key,
                    source=source,
                    base_value=value,
                    final_value=final_value,
                    derivation_chain=[f"safety_rule:{rule.expression}"]
                    + ([f"depends_on:{','.join(rule.depends_on)}"] if rule.depends_on else []),
                )
            )

        # Resolve Tuning parameters from derivation rules
        for rule in preset.tuning_derivations:
            value = self._evaluate_expression(rule.expression, derived_context)
            # Apply modifier adjustments to tuning params
            if modifier and rule.key in modifier.adjustments:
                value = modifier.adjustments[rule.key]
            derived_context[rule.key] = value
            resolved[ParameterClassification.TUNING].append(
                ResolvedParameter(
                    key=rule.key,
                    value=value,
                    classification=ParameterClassification.TUNING,
                    source="modifier"
                    if modifier and rule.key in modifier.adjustments
                    else "derived",
                )
            )
            trace.append(
                CompilationTrace(
                    parameter_key=rule.key,
                    source="modifier"
                    if modifier and rule.key in modifier.adjustments
                    else "derived",
                    base_value=self._evaluate_expression(rule.expression, derived_context),
                    final_value=value,
                    derivation_chain=[f"tuning_rule:{rule.expression}"],
                )
            )

        return resolved

    @staticmethod
    def _evaluate_expression(
        expression: str,
        context: dict[str, int | float | str | bool],
    ) -> int | float | str | bool:
        """Evaluate a simple derivation expression.

        Supports:
        - Literal values: "50", "'55m'", "True", "False"
        - Context references: "persistence.maxConns" → looks up in context dict
        """
        stripped = expression.strip()

        # Context reference (e.g., "persistence.maxConns")
        if stripped in context:
            return context[stripped]

        # Boolean literals
        if stripped == "True":
            return True
        if stripped == "False":
            return False

        # String literals (single-quoted)
        if stripped.startswith("'") and stripped.endswith("'"):
            return stripped[1:-1]

        # Numeric literals
        try:
            return int(stripped)
        except ValueError:
            pass
        try:
            return float(stripped)
        except ValueError:
            pass

        return stripped

    def _emit_dynamic_config_yaml(self, profile: ConfigProfile) -> str:
        """Generate Temporal dynamic config YAML from resolved parameters."""
        import yaml

        config: dict[str, list[dict]] = {}
        for param in profile.all_params():
            entry = self._registry.get(param.key)
            if entry is None:
                continue
            if any(t == "dynamic_config" for t in entry.output_targets):
                config[param.key] = [{"value": param.value, "constraints": {}}]

        return yaml.dump(config, default_flow_style=False, sort_keys=True)

    @staticmethod
    def _build_dsql_plugin_config(profile: ConfigProfile) -> DSQLPluginConfig:
        """Extract DSQL plugin config from resolved safety parameters."""

        def _get(key: str, default: int | float | str | bool = 0) -> int | float | str | bool:
            p = profile.get_param(key)
            return p.value if p else default

        return DSQLPluginConfig(
            reservoir_enabled=bool(_get("dsql.reservoir_enabled", False)),
            reservoir_target_ready=int(_get("dsql.reservoir_target_ready", 50)),
            reservoir_base_lifetime_min=_parse_duration_minutes(
                str(_get("dsql.reservoir_base_lifetime", "11m"))
            ),
            reservoir_lifetime_jitter_min=_parse_duration_minutes(
                str(_get("dsql.reservoir_lifetime_jitter", "2m"))
            ),
            reservoir_guard_window_sec=_parse_duration_seconds(
                str(_get("dsql.reservoir_guard_window", "45s"))
            ),
            reservoir_inflight_limit=int(_get("dsql.reservoir_inflight_limit", 8)),
            max_conns=int(_get("persistence.maxConns", 50)),
            max_idle_conns=int(_get("persistence.maxIdleConns", 50)),
            max_conn_lifetime_min=_parse_duration_minutes(
                str(_get("dsql.max_conn_lifetime", "55m"))
            ),
            connection_rate_limit=int(_get("dsql.connection_rate_limit", 10)),
            connection_burst_limit=int(_get("dsql.connection_burst_limit", 100)),
            distributed_rate_limiter_enabled=bool(
                _get("dsql.distributed_rate_limiter_enabled", False)
            ),
            distributed_rate_limiter_table=str(_get("dsql.distributed_rate_limiter_table", ""))
            or None,
            token_bucket_enabled=bool(_get("dsql.token_bucket_enabled", False)),
            token_bucket_rate=int(_get("dsql.token_bucket_rate", 100))
            if _get("dsql.token_bucket_enabled", False)
            else None,
            token_bucket_capacity=int(_get("dsql.token_bucket_capacity", 1000))
            if _get("dsql.token_bucket_enabled", False)
            else None,
            slot_block_enabled=bool(_get("dsql.slot_block_enabled", False)),
            slot_block_size=int(_get("dsql.slot_block_size", 100))
            if _get("dsql.slot_block_enabled", False)
            else None,
            slot_block_count=int(_get("dsql.slot_block_count", 100))
            if _get("dsql.slot_block_enabled", False)
            else None,
        )

    @staticmethod
    def _generate_why_section(
        profile: ConfigProfile,
        preset: ScalePreset,
        modifier: WorkloadModifier | None,
        overrides: ParameterOverrides,
    ) -> str:
        """Generate a template-based explanation of the compilation result."""
        lines: list[str] = []
        lines.append(f"Configuration compiled from preset '{preset.name}'")
        lines.append(f"  Target: {preset.throughput_range.description}")

        if modifier:
            lines.append(f"  Workload modifier: {modifier.name} — {modifier.description}")

        if overrides.values:
            lines.append(f"  Overrides applied: {len(overrides.values)} parameter(s)")
            for key, value in overrides.values.items():
                lines.append(f"    {key} = {value}")

        lines.append("")
        lines.append("Key derived values:")

        # Highlight important safety params
        for param in profile.safety_params:
            if param.key in (
                "persistence.maxConns",
                "dsql.reservoir_enabled",
                "dsql.distributed_rate_limiter_enabled",
            ):
                lines.append(f"  {param.key} = {param.value} (source: {param.source})")

        # Highlight persistence QPS
        for param in profile.tuning_params:
            if "persistenceMaxQPS" in param.key:
                lines.append(f"  {param.key} = {param.value} (source: {param.source})")

        return "\n".join(lines)

    def list_presets(self) -> list[PresetSummary]:
        """Return summaries of all available presets."""
        return [
            PresetSummary(
                name=p.name,
                description=p.description,
                throughput_range=p.throughput_range,
            )
            for p in PRESETS.values()
        ]

    def describe_preset(
        self,
        preset: str,
        *,
        modifier: str | None = None,
    ) -> PresetDescription:
        """Describe a preset by resolving all parameters without running guard rails."""
        scale_preset = PRESETS.get(preset)
        if scale_preset is None:
            raise UnknownPresetError(preset)

        workload_modifier: WorkloadModifier | None = None
        if modifier is not None:
            workload_modifier = MODIFIERS.get(modifier)
            if workload_modifier is None:
                raise UnknownModifierError(modifier)

        trace: list[CompilationTrace] = []
        resolved = self._resolve_all(scale_preset, workload_modifier, ParameterOverrides(), trace)

        return PresetDescription(
            name=scale_preset.name,
            description=scale_preset.description,
            throughput_range=scale_preset.throughput_range,
            slo_params=resolved[ParameterClassification.SLO],
            topology_params=resolved[ParameterClassification.TOPOLOGY],
            safety_params=resolved[ParameterClassification.SAFETY],
            tuning_params=resolved[ParameterClassification.TUNING],
        )

    def explain_key(self, key: str, profile: ConfigProfile) -> KeyExplanation:
        """Level 1: Explain a single parameter from registry metadata."""
        from dsql_config.explain import KeyExplanation

        entry = self._registry.get(key)
        if entry is None:
            raise UnknownParameterError(key)

        param = profile.get_param(key)
        value = param.value if param else entry.default_value
        source = param.source if param else "default"

        return KeyExplanation(
            key=key,
            classification=entry.classification,
            value=value,
            description=entry.description,
            rationale=entry.rationale,
            source=source,
        )

    def explain_preset(
        self,
        preset: str,
        *,
        modifier: str | None = None,
    ) -> PresetExplanation:
        """Level 2: Explain a preset's reasoning chain."""
        from dsql_config.explain import LockedParam, PresetExplanation

        scale_preset = PRESETS.get(preset)
        if scale_preset is None:
            raise UnknownPresetError(preset)

        workload_modifier: WorkloadModifier | None = None
        if modifier is not None:
            workload_modifier = MODIFIERS.get(modifier)
            if workload_modifier is None:
                raise UnknownModifierError(modifier)

        trace: list[CompilationTrace] = []
        resolved = self._resolve_all(scale_preset, workload_modifier, ParameterOverrides(), trace)

        # Build topology derivation steps
        topology_steps: list[str] = []
        for p in resolved[ParameterClassification.TOPOLOGY]:
            entry = self._registry.get(p.key)
            rationale = entry.rationale if entry else ""
            topology_steps.append(f"{p.key} = {p.value} — {rationale}")

        # Build locked safety params
        locked: list[LockedParam] = []
        for p in resolved[ParameterClassification.SAFETY]:
            entry = self._registry.get(p.key)
            locked.append(
                LockedParam(
                    key=p.key,
                    value=p.value,
                    reason=entry.rationale if entry else "Auto-derived from preset",
                )
            )

        # Build narrative
        narrative_parts = [
            f"The '{scale_preset.name}' preset targets "
            f"{scale_preset.throughput_range.description}.",
        ]
        if workload_modifier:
            narrative_parts.append(
                f"The '{workload_modifier.name}' modifier adjusts "
                f"{len(workload_modifier.adjustments)} parameters "
                f"for {workload_modifier.description}."
            )
        narrative_parts.append(
            f"Safety parameters ({len(locked)}) are locked to values derived from "
            f"the preset's throughput target and topology."
        )

        return PresetExplanation(
            preset_name=scale_preset.name,
            modifier=modifier,
            slo_targets=resolved[ParameterClassification.SLO],
            topology_derivation=topology_steps,
            locked_safety_params=locked,
            reasoning_narrative=" ".join(narrative_parts),
        )

    def explain_profile(self, profile: ConfigProfile) -> ProfileExplanation:
        """Level 3: Explain a compiled profile's full composition."""
        from dsql_config.explain import OverrideDetail, ProfileExplanation

        scale_preset = PRESETS.get(profile.preset_name)
        if scale_preset is None:
            raise UnknownPresetError(profile.preset_name)

        # Rebuild trace to get derivation chains
        workload_modifier: WorkloadModifier | None = None
        if profile.modifier:
            workload_modifier = MODIFIERS.get(profile.modifier)

        trace: list[CompilationTrace] = []
        base_resolved = self._resolve_all(
            scale_preset, workload_modifier, ParameterOverrides(), trace
        )

        # Identify overrides
        overrides_applied: list[OverrideDetail] = []
        for key, override_value in profile.overrides.values.items():
            entry = self._registry.get(key)
            if entry is None:
                continue
            # Find the base value (what the preset would have produced)
            base_params = base_resolved.get(entry.classification, [])
            base_value = override_value
            for bp in base_params:
                if bp.key == key:
                    base_value = bp.value
                    break
            if base_value != override_value:
                overrides_applied.append(
                    OverrideDetail(
                        key=key,
                        preset_value=base_value,
                        override_value=override_value,
                        classification=entry.classification,
                    )
                )

        # Get guard rail results (warnings only, since errors would have halted)
        from dsql_config.guard_rails import GuardRailEngine

        engine = self._guard_rail_engine or GuardRailEngine()
        guard_rails_fired = engine.evaluate(profile)

        # Build narrative
        parts = [f"Compiled from preset '{profile.preset_name}'."]
        if profile.modifier:
            parts.append(f"Workload modifier '{profile.modifier}' applied.")
        if overrides_applied:
            parts.append(
                f"{len(overrides_applied)} override(s) changed values from preset defaults."
            )
        if guard_rails_fired:
            warnings = [r for r in guard_rails_fired if r.severity == "warning"]
            errors = [r for r in guard_rails_fired if r.severity == "error"]
            if warnings:
                parts.append(f"{len(warnings)} warning(s) noted.")
            if errors:
                parts.append(f"{len(errors)} error(s) detected.")

        return ProfileExplanation(
            base_preset=profile.preset_name,
            modifier=profile.modifier,
            overrides_applied=overrides_applied,
            guard_rails_fired=guard_rails_fired,
            derivation_chains=trace,
            composition_narrative=" ".join(parts),
        )


def _parse_duration_minutes(value: str) -> float:
    """Parse a duration string like '55m' or '2m' into minutes."""
    v = value.strip()
    if v.endswith("m"):
        return float(v[:-1])
    if v.endswith("s"):
        return float(v[:-1]) / 60.0
    if v.endswith("h"):
        return float(v[:-1]) * 60.0
    return float(v)


def _parse_duration_seconds(value: str) -> float:
    """Parse a duration string like '45s' or '2m' into seconds."""
    v = value.strip()
    if v.endswith("s"):
        return float(v[:-1])
    if v.endswith("m"):
        return float(v[:-1]) * 60.0
    if v.endswith("h"):
        return float(v[:-1]) * 3600.0
    return float(v)
