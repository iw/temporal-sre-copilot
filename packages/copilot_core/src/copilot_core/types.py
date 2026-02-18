"""Parameter classification system and core configuration types."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class ParameterClassification(StrEnum):
    SLO = "slo"
    TOPOLOGY = "topology"
    SAFETY = "safety"
    TUNING = "tuning"


class ParameterValueType(StrEnum):
    INT = "int"
    FLOAT = "float"
    STR = "str"
    DURATION = "duration"
    BOOL = "bool"


class ParameterUnit(StrEnum):
    PER_SEC = "per_sec"
    MILLISECONDS = "ms"
    SECONDS = "s"
    MINUTES = "m"
    CONNECTIONS = "connections"
    COUNT = "count"
    PERCENT = "percent"
    BYTES = "bytes"


class OutputTarget(StrEnum):
    DYNAMIC_CONFIG = "dynamic_config"
    ENV_VARS = "env_vars"
    WORKER_OPTIONS = "worker_options"
    DSQL_PLUGIN = "dsql_plugin"


class ParameterConstraints(BaseModel):
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: list[str | int | float | bool] | None = None


class ParameterEntry(BaseModel):
    key: str
    classification: ParameterClassification
    description: str
    rationale: str
    default_value: int | float | str | bool
    value_type: ParameterValueType
    unit: ParameterUnit | None = None
    constraints: ParameterConstraints | None = None
    output_targets: list[OutputTarget]


class ResolvedParameter(BaseModel):
    key: str
    value: int | float | str | bool
    classification: ParameterClassification
    source: Literal["preset", "modifier", "override", "derived", "default"]


class ParameterOverrides(BaseModel):
    values: dict[str, int | float | str | bool] = {}
