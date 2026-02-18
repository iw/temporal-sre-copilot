"""Shared base models used across copilot_core, dsql_config, and behaviour_profiles."""

from pydantic import BaseModel


class TelemetryBound(BaseModel):
    metric: str
    lower: float
    upper: float


class MetricAggregate(BaseModel):
    min: float
    max: float
    mean: float
    p50: float
    p95: float
    p99: float


class ServiceMetrics(BaseModel):
    history: MetricAggregate
    matching: MetricAggregate
    frontend: MetricAggregate
    worker: MetricAggregate
