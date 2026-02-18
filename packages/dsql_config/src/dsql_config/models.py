"""Config Compiler models — ConfigProfile, CompilationResult, presets, and derivation rules."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from copilot_core.models import TelemetryBound  # noqa: TC001
from copilot_core.types import (
    ParameterClassification,
    ParameterOverrides,
    ResolvedParameter,
)
from copilot_core.versions import VersionType  # noqa: TC001


class ConfigProfile(BaseModel):
    preset_name: str
    modifier: str | None = None
    overrides: ParameterOverrides = ParameterOverrides()

    slo_params: list[ResolvedParameter]
    topology_params: list[ResolvedParameter]
    safety_params: list[ResolvedParameter]
    tuning_params: list[ResolvedParameter]

    temporal_server_version: VersionType
    dsql_plugin_version: VersionType

    compiled_at: str
    compiler_version: VersionType

    def get_param(self, key: str) -> ResolvedParameter | None:
        for param_list in (
            self.slo_params,
            self.topology_params,
            self.safety_params,
            self.tuning_params,
        ):
            for p in param_list:
                if p.key == key:
                    return p
        return None

    def all_params(self) -> list[ResolvedParameter]:
        return self.slo_params + self.topology_params + self.safety_params + self.tuning_params

    def params_by_classification(
        self,
        classification: ParameterClassification,
    ) -> list[ResolvedParameter]:
        match classification:
            case ParameterClassification.SLO:
                return self.slo_params
            case ParameterClassification.TOPOLOGY:
                return self.topology_params
            case ParameterClassification.SAFETY:
                return self.safety_params
            case ParameterClassification.TUNING:
                return self.tuning_params


class CompilationTrace(BaseModel):
    parameter_key: str
    source: Literal["preset", "modifier", "override", "derived", "default"]
    base_value: int | float | str | bool
    final_value: int | float | str | bool
    derivation_chain: list[str]


class DSQLPluginConfig(BaseModel):
    reservoir_enabled: bool
    reservoir_target_ready: int
    reservoir_base_lifetime_min: float
    reservoir_lifetime_jitter_min: float
    reservoir_guard_window_sec: float
    reservoir_inflight_limit: int
    max_conns: int
    max_idle_conns: int
    max_conn_lifetime_min: float
    connection_rate_limit: int
    connection_burst_limit: int
    distributed_rate_limiter_enabled: bool
    distributed_rate_limiter_table: str | None = None
    token_bucket_enabled: bool
    token_bucket_rate: int | None = None
    token_bucket_capacity: int | None = None
    slot_block_enabled: bool
    slot_block_size: int | None = None
    slot_block_count: int | None = None


class RenderedSnippet(BaseModel):
    language: str
    filename: str
    content: str


class GuardRailResult(BaseModel):
    rule_name: str
    severity: Literal["error", "warning"]
    message: str
    parameter_keys: list[str]


class CompilationResult(BaseModel):
    profile: ConfigProfile
    dynamic_config_yaml: str
    dsql_plugin_config: DSQLPluginConfig
    sdk_snippets: list[RenderedSnippet]
    platform_snippets: list[RenderedSnippet]
    guard_rail_results: list[GuardRailResult]
    trace: list[CompilationTrace]
    why_section: str


class ThroughputRange(BaseModel):
    min_st_per_sec: float
    max_st_per_sec: float | None
    description: str


class PresetDefault(BaseModel):
    key: str
    value: int | float | str | bool


class DerivationRule(BaseModel):
    key: str
    expression: str
    depends_on: list[str]


class ScalePreset(BaseModel):
    name: str
    description: str
    throughput_range: ThroughputRange
    slo_defaults: list[PresetDefault]
    topology_defaults: list[PresetDefault]
    safety_derivations: list[DerivationRule]
    tuning_derivations: list[DerivationRule]
    expected_bounds: list[TelemetryBound] | None = None


class PresetSummary(BaseModel):
    name: str
    description: str
    throughput_range: ThroughputRange


class PresetDescription(BaseModel):
    name: str
    description: str
    throughput_range: ThroughputRange
    slo_params: list[ResolvedParameter]
    topology_params: list[ResolvedParameter]
    safety_params: list[ResolvedParameter]
    tuning_params: list[ResolvedParameter]
