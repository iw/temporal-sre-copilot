"""Platform inspector protocols and plugin discovery.

Inspectors query the monitored cluster's actual deployment state at runtime.
They are discovered via importlib.metadata entry_points, following the same
pattern as dsql_config adapters.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from copilot_core.deployment import DeploymentContext, ResourceIdentity

PLATFORM_INSPECTOR_GROUP = "temporal_copilot.platform_inspectors"


@runtime_checkable
class PlatformInspector(Protocol):
    platform: str
    name: str

    async def inspect(self, identity: ResourceIdentity) -> DeploymentContext | None: ...


def discover_platform_inspectors() -> list[PlatformInspector]:
    """Discover all registered Platform inspectors via entry points."""
    eps = entry_points(group=PLATFORM_INSPECTOR_GROUP)
    inspectors: list[PlatformInspector] = []
    for ep in eps:
        obj = ep.load()
        inspector = obj() if callable(obj) else obj
        if not isinstance(inspector, PlatformInspector):
            raise TypeError(f"{ep.name} does not implement PlatformInspector")
        inspectors.append(inspector)
    return inspectors
