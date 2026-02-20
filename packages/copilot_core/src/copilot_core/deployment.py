"""Deployment models shared between dsql_config (produces) and copilot (consumes).

Layer 2 models describe the static deployment topology (what was deployed).
Layer 3 models describe the runtime deployment state (what's running now).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, model_validator


class AutoscalerType(StrEnum):
    KARPENTER = "karpenter"
    HPA = "hpa"
    FIXED = "fixed"


class ServiceResourceLimits(BaseModel):
    """Resource limits for a single Temporal service."""

    cpu_millicores: int | None = None
    memory_mib: int | None = None


class ServiceScalingBounds(BaseModel):
    """Scaling bounds for a single Temporal service."""

    min_replicas: int
    max_replicas: int
    resource_limits: ServiceResourceLimits = ServiceResourceLimits()

    @model_validator(mode="after")
    def _check_min_le_max(self) -> ServiceScalingBounds:
        if self.min_replicas > self.max_replicas:
            msg = f"min_replicas ({self.min_replicas}) must be ≤ max_replicas ({self.max_replicas})"
            raise ValueError(msg)
        return self


class ScalingTopology(BaseModel):
    """Scaling topology for all Temporal services."""

    history: ServiceScalingBounds
    matching: ServiceScalingBounds
    frontend: ServiceScalingBounds
    worker: ServiceScalingBounds
    autoscaler_type: AutoscalerType = AutoscalerType.FIXED


class ResourceIdentity(BaseModel):
    """Provisioned infrastructure identifiers."""

    dsql_endpoint: str
    platform_identifier: str
    platform_type: Literal["ecs", "eks", "compose"]
    amp_workspace_id: str | None = None


class DeploymentProfile(BaseModel):
    """Bridges 'what we compiled' to 'what we deployed'."""

    preset_name: str
    throughput_range_min: float
    throughput_range_max: float | None = None

    scaling_topology: ScalingTopology | None = None
    resource_identity: ResourceIdentity | None = None
    config_profile_id: str | None = None


# ---------------------------------------------------------------------------
# Layer 3: Runtime deployment state
# ---------------------------------------------------------------------------


class ServiceReplicaState(BaseModel):
    """Runtime state of a single Temporal service's replicas."""

    running: int
    desired: int
    pending: int = 0
    cpu_utilization_pct: float | None = None
    memory_utilization_pct: float | None = None


class AutoscalerState(BaseModel):
    """Runtime state of the autoscaler."""

    min_capacity: int
    max_capacity: int
    desired_capacity: int
    actively_scaling: bool = False


class DSQLConnectionState(BaseModel):
    """Runtime DSQL connection state."""

    current_connections: int
    max_connections: int
    connections_per_service: dict[str, int] = {}


class DeploymentContext(BaseModel):
    """Runtime snapshot of the monitored cluster's actual deployment state.

    Fetched by PlatformInspector, passed to evaluate_health_state()
    for threshold refinement.
    """

    history: ServiceReplicaState
    matching: ServiceReplicaState
    frontend: ServiceReplicaState
    worker: ServiceReplicaState
    autoscaler: AutoscalerState | None = None
    dsql: DSQLConnectionState | None = None
    timestamp: str  # ISO 8601 UTC
