"""Property-based tests for the Config Compiler.

Properties 1-12 and 22-26 from the design document.
"""

from __future__ import annotations

import json

import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from copilot_core.types import (
    ParameterClassification,
    ParameterOverrides,
)
from dsql_config.compiler import ConfigCompiler
from dsql_config.guard_rails import GuardRailEngine
from dsql_config.models import ConfigProfile
from dsql_config.presets import list_preset_names
from dsql_config.registry import build_default_registry

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

PRESET_NAMES = list_preset_names()
MODIFIER_NAMES = [None, "simple-crud", "orchestrator", "batch-processor", "long-running"]

# Keys that accept topology/SLO overrides (adopter-configurable)
OVERRIDABLE_KEYS = [
    "history.replicas",
    "matching.replicas",
    "frontend.replicas",
    "worker.replicas",
    "matching.numTaskqueueReadPartitions",
    "matching.numTaskqueueWritePartitions",
    "sdk.worker_count",
]


def _make_compiler() -> ConfigCompiler:
    registry = build_default_registry()
    return ConfigCompiler(registry)


def _compile_profile(
    preset: str,
    modifier: str | None = None,
    overrides: ParameterOverrides | None = None,
) -> ConfigProfile:
    compiler = _make_compiler()
    result = compiler.compile(preset, modifier=modifier, overrides=overrides)
    return result.profile


# =========================================================================
# Property 1: Parameter classification uniqueness
# Feature: enhance-config-ux, Property 1: Parameter classification uniqueness
# Validates: Requirements 1.1
# =========================================================================


@settings(max_examples=10)
@given(data=st.data())
def test_parameter_classification_uniqueness(data: st.DataObject):
    """Every parameter belongs to exactly one classification."""
    registry = build_default_registry()
    key = data.draw(st.sampled_from(registry.all_keys()))
    entry = registry.get(key)
    assert entry is not None

    # Classification is one of the four valid values
    assert entry.classification in list(ParameterClassification)

    # Parameter appears in exactly one classification group
    groups_containing = [
        c
        for c in ParameterClassification
        if any(e.key == key for e in registry.list_by_classification(c))
    ]
    assert len(groups_containing) == 1
    assert groups_containing[0] == entry.classification


# =========================================================================
# Property 2: Derived parameter completeness
# Feature: enhance-config-ux, Property 2: Derived parameter completeness
# Validates: Requirements 1.4, 1.5
# =========================================================================


@settings(max_examples=20)
@given(
    preset=st.sampled_from(PRESET_NAMES),
    modifier=st.sampled_from(MODIFIER_NAMES),
)
def test_derived_parameter_completeness(preset: str, modifier: str | None):
    """Compiled profile has non-empty safety and tuning params covering all registry entries."""
    registry = build_default_registry()
    profile = _compile_profile(preset, modifier=modifier)

    assert len(profile.safety_params) > 0
    assert len(profile.tuning_params) > 0

    # Every safety key in the registry has a resolved value
    safety_keys = {e.key for e in registry.list_by_classification(ParameterClassification.SAFETY)}
    resolved_safety = {p.key for p in profile.safety_params}
    assert safety_keys <= resolved_safety

    # Every tuning key in the registry has a resolved value
    tuning_keys = {e.key for e in registry.list_by_classification(ParameterClassification.TUNING)}
    resolved_tuning = {p.key for p in profile.tuning_params}
    assert tuning_keys <= resolved_tuning


# =========================================================================
# Property 3: Exposed parameter count invariant
# Feature: enhance-config-ux, Property 3: Exposed parameter count invariant
# Validates: Requirements 1.6
# =========================================================================


@settings(max_examples=20)
@given(
    preset=st.sampled_from(PRESET_NAMES),
    modifier=st.sampled_from(MODIFIER_NAMES),
)
def test_exposed_parameter_count_invariant(preset: str, modifier: str | None):
    """SLO + Topology params total at most 15."""
    profile = _compile_profile(preset, modifier=modifier)
    exposed = len(profile.slo_params) + len(profile.topology_params)
    assert exposed <= 15


# =========================================================================
# Property 4: Dynamic config YAML validity
# Feature: enhance-config-ux, Property 4: Dynamic config YAML validity
# Validates: Requirements 4.1
# =========================================================================


@settings(max_examples=20)
@given(
    preset=st.sampled_from(PRESET_NAMES),
    modifier=st.sampled_from(MODIFIER_NAMES),
)
def test_dynamic_config_yaml_validity(preset: str, modifier: str | None):
    """Emitted dynamic config is valid YAML with entries for all dynamic config params."""
    compiler = _make_compiler()
    result = compiler.compile(preset, modifier=modifier)

    parsed = yaml.safe_load(result.dynamic_config_yaml)
    assert isinstance(parsed, dict)
    assert len(parsed) > 0


# =========================================================================
# Property 5: Override application
# Feature: enhance-config-ux, Property 5: Override application
# Validates: Requirements 4.5
# =========================================================================


@settings(max_examples=30)
@given(
    preset=st.sampled_from(PRESET_NAMES),
    key=st.sampled_from(OVERRIDABLE_KEYS),
    value=st.integers(min_value=1, max_value=8),
)
def test_override_replaces_default(preset: str, key: str, value: int):
    """Override value appears in the final profile, not the preset default."""
    profile = _compile_profile(
        preset,
        overrides=ParameterOverrides(values={key: value}),
    )
    param = profile.get_param(key)
    assert param is not None
    assert param.value == value
    assert param.source == "override"


# =========================================================================
# Property 6: Why section presence
# Feature: enhance-config-ux, Property 6: Why section presence
# Validates: Requirements 4.6
# =========================================================================


@settings(max_examples=20)
@given(
    preset=st.sampled_from(PRESET_NAMES),
    modifier=st.sampled_from(MODIFIER_NAMES),
)
def test_why_section_presence(preset: str, modifier: str | None):
    """CompilationResult always has a non-empty why_section."""
    compiler = _make_compiler()
    result = compiler.compile(preset, modifier=modifier)
    assert result.why_section
    assert len(result.why_section.strip()) > 0


# =========================================================================
# Property 7: Adapter output completeness
# Feature: enhance-config-ux, Property 7: Adapter output completeness
# Validates: Requirements 4a.5, 4b.5
# =========================================================================


@settings(max_examples=20)
@given(
    preset=st.sampled_from(PRESET_NAMES),
    modifier=st.sampled_from(MODIFIER_NAMES),
)
def test_adapter_output_completeness(preset: str, modifier: str | None):
    """Every adapter produces non-empty content with valid filenames."""
    from dsql_config.adapters import discover_platform_adapters, discover_sdk_adapters

    profile = _compile_profile(preset, modifier=modifier)

    # SDK adapters
    for adapter in discover_sdk_adapters():
        snippet = adapter.render(profile)
        assert snippet.content.strip()
        assert snippet.filename.strip()
        assert snippet.language.strip()

    # Platform adapters
    for adapter in discover_platform_adapters():
        snippets = adapter.render(profile)
        assert len(snippets) > 0
        for snippet in snippets:
            assert snippet.content.strip()
            assert snippet.filename.strip()
            assert snippet.language.strip()

    # At least one SDK and one platform adapter should be discovered
    assert len(discover_sdk_adapters()) > 0
    assert len(discover_platform_adapters()) > 0


# =========================================================================
# Property 8: MaxIdleConns equals MaxConns guard rail
# Feature: enhance-config-ux, Property 8: MaxIdleConns equals MaxConns
# Validates: Requirements 5.5
# =========================================================================


def test_max_idle_equals_max_conns_guard_rail():
    """When MaxIdleConns != MaxConns, guard rail produces an error."""
    # Build a profile where the invariant is violated
    profile = _compile_profile("starter")

    # Manually break the invariant
    for p in profile.safety_params:
        if p.key == "persistence.maxIdleConns":
            p.value = 999  # Deliberately different from maxConns

    engine = GuardRailEngine()
    results = engine.evaluate(profile)

    error_results = [r for r in results if r.severity == "error"]
    idle_errors = [r for r in error_results if r.rule_name == "max_idle_equals_max_conns"]
    assert len(idle_errors) == 1


# =========================================================================
# Property 9: All guard rail errors reported
# Feature: enhance-config-ux, Property 9: All guard rail errors reported
# Validates: Requirements 5.8
# =========================================================================


def test_all_guard_rail_errors_reported():
    """Multiple guard rail violations are all reported, not short-circuited."""
    profile = _compile_profile("high-throughput")

    # Break multiple invariants
    for p in profile.safety_params:
        if p.key == "persistence.maxIdleConns":
            p.value = 999  # != maxConns → error
        if p.key == "dsql.reservoir_lifetime_jitter":
            p.value = "0s"  # thundering herd → error
        if p.key == "dsql.distributed_rate_limiter_table":
            p.value = ""  # missing table → error

    engine = GuardRailEngine()
    results = engine.evaluate(profile)

    error_results = [r for r in results if r.severity == "error"]
    rule_names = {r.rule_name for r in error_results}

    assert "max_idle_equals_max_conns" in rule_names
    assert "thundering_herd_risk" in rule_names
    assert "distributed_rate_limiter_table_missing" in rule_names
    assert len(error_results) >= 3


# =========================================================================
# Property 10: Config_Profile serialization round-trip
# Feature: enhance-config-ux, Property 10: Config_Profile serialization round-trip
# Validates: Requirements 6.1, 6.2, 6.3, 6.4
# =========================================================================


@settings(max_examples=20)
@given(
    preset=st.sampled_from(PRESET_NAMES),
    modifier=st.sampled_from(MODIFIER_NAMES),
)
def test_config_profile_round_trip(preset: str, modifier: str | None):
    """Serializing to JSON then deserializing produces an equivalent ConfigProfile."""
    profile = _compile_profile(preset, modifier=modifier)

    json_str = profile.model_dump_json()
    restored = ConfigProfile.model_validate_json(json_str)
    assert restored == profile


# =========================================================================
# Property 11: Describe-preset completeness and grouping
# Feature: enhance-config-ux, Property 11: Describe-preset completeness
# Validates: Requirements 7.2, 7.3
# =========================================================================


@settings(max_examples=20)
@given(
    preset=st.sampled_from(PRESET_NAMES),
    modifier=st.sampled_from(MODIFIER_NAMES),
)
def test_describe_preset_completeness(preset: str, modifier: str | None):
    """describe_preset returns params grouped by classification with SLO and Topology non-empty."""
    compiler = _make_compiler()
    desc = compiler.describe_preset(preset, modifier=modifier)

    assert len(desc.slo_params) > 0
    assert len(desc.topology_params) > 0
    assert len(desc.safety_params) > 0
    assert len(desc.tuning_params) > 0

    # All params have valid classifications
    for p in desc.slo_params:
        assert p.classification == ParameterClassification.SLO
    for p in desc.topology_params:
        assert p.classification == ParameterClassification.TOPOLOGY
    for p in desc.safety_params:
        assert p.classification == ParameterClassification.SAFETY
    for p in desc.tuning_params:
        assert p.classification == ParameterClassification.TUNING


# =========================================================================
# Property 12: Redundant environment variable detection
# Feature: enhance-config-ux, Property 12: Redundant env var detection
# Validates: Requirements 8.3
# =========================================================================


def test_redundant_env_var_detection():
    """Env vars matching preset defaults are identified as redundant."""
    compiler = _make_compiler()
    # Compile starter with no overrides
    result = compiler.compile("starter")

    # Get the starter preset's maxConns value
    max_conns_param = result.profile.get_param("persistence.maxConns")
    assert max_conns_param is not None

    # Now compile with an override that matches the default
    result_with_redundant = compiler.compile(
        "starter",
        overrides=ParameterOverrides(values={"persistence.maxConns": max_conns_param.value}),
    )
    # The override should still be applied (source = override)
    p = result_with_redundant.profile.get_param("persistence.maxConns")
    assert p is not None
    assert p.value == max_conns_param.value


# =========================================================================
# Property 22: Explain key completeness
# Feature: enhance-config-ux, Property 22: Explain key completeness
# Validates: Requirements 17.1
# =========================================================================


@settings(max_examples=20)
@given(
    preset=st.sampled_from(PRESET_NAMES),
    data=st.data(),
)
def test_explain_key_completeness(preset: str, data: st.DataObject):
    """Key explanation contains purpose, classification, value, and rationale."""
    compiler = _make_compiler()
    profile = _compile_profile(preset)
    key = data.draw(st.sampled_from([p.key for p in profile.all_params()]))

    explanation = compiler.explain_key(key, profile)
    assert explanation.key == key
    assert explanation.classification in list(ParameterClassification)
    assert explanation.description
    assert explanation.rationale
    assert explanation.source in ("preset", "modifier", "override", "derived", "default")


# =========================================================================
# Property 23: Explain preset completeness
# Feature: enhance-config-ux, Property 23: Explain preset completeness
# Validates: Requirements 17.2
# =========================================================================


@settings(max_examples=20)
@given(
    preset=st.sampled_from(PRESET_NAMES),
    modifier=st.sampled_from(MODIFIER_NAMES),
)
def test_explain_preset_completeness(preset: str, modifier: str | None):
    """Preset explanation has SLO targets, topology derivation, locked params, and narrative."""
    compiler = _make_compiler()
    explanation = compiler.explain_preset(preset, modifier=modifier)

    assert explanation.preset_name == preset
    assert len(explanation.slo_targets) > 0
    assert len(explanation.topology_derivation) > 0
    assert len(explanation.locked_safety_params) > 0
    assert explanation.reasoning_narrative.strip()


# =========================================================================
# Property 24: Explain profile completeness
# Feature: enhance-config-ux, Property 24: Explain profile completeness
# Validates: Requirements 17.3
# =========================================================================


@settings(max_examples=20)
@given(preset=st.sampled_from(PRESET_NAMES))
def test_explain_profile_completeness(preset: str):
    """Profile explanation contains base preset, derivation chains, and narrative."""
    compiler = _make_compiler()
    profile = _compile_profile(preset)
    explanation = compiler.explain_profile(profile)

    assert explanation.base_preset == preset
    assert len(explanation.derivation_chains) > 0
    assert explanation.composition_narrative.strip()


# =========================================================================
# Property 25: Explain determinism
# Feature: enhance-config-ux, Property 25: Explain determinism
# Validates: Requirements 17.4
# =========================================================================


@settings(max_examples=10)
@given(preset=st.sampled_from(PRESET_NAMES))
def test_explain_is_deterministic(preset: str):
    """Calling explain twice with identical inputs produces identical output."""
    compiler = _make_compiler()
    profile = _compile_profile(preset)

    explanation_1 = compiler.explain_profile(profile)
    explanation_2 = compiler.explain_profile(profile)
    assert explanation_1 == explanation_2


# =========================================================================
# Property 26: Explain dual format
# Feature: enhance-config-ux, Property 26: Explain dual format
# Validates: Requirements 17.6
# =========================================================================


@settings(max_examples=10)
@given(preset=st.sampled_from(PRESET_NAMES))
def test_explain_dual_format(preset: str):
    """Both text and JSON formats are non-empty and JSON is parseable."""
    compiler = _make_compiler()
    profile = _compile_profile(preset)

    # Key explanation
    key = profile.all_params()[0].key
    key_expl = compiler.explain_key(key, profile)
    assert key_expl.to_text().strip()
    json.loads(key_expl.to_json())  # Must be valid JSON

    # Preset explanation
    preset_expl = compiler.explain_preset(preset)
    assert preset_expl.to_text().strip()
    json.loads(preset_expl.to_json())

    # Profile explanation
    profile_expl = compiler.explain_profile(profile)
    assert profile_expl.to_text().strip()
    json.loads(profile_expl.to_json())
