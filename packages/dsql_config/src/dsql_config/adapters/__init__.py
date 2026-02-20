"""Adapter protocols and plugin discovery for SDK and Platform adapters.

Adapters are discovered at runtime via importlib.metadata entry_points.
New adapters can be shipped as separate packages that register under
well-known entry point groups.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from copilot_core.deployment import DeploymentProfile
    from dsql_config.models import ConfigProfile, RenderedSnippet

SDK_ADAPTER_GROUP = "temporal_dsql.sdk_adapters"
PLATFORM_ADAPTER_GROUP = "temporal_dsql.platform_adapters"
DEPLOYMENT_ADAPTER_GROUP = "temporal_dsql.deployment_adapters"


@runtime_checkable
class SDKAdapter(Protocol):
    language: str
    name: str

    def render(self, profile: ConfigProfile) -> RenderedSnippet: ...


@runtime_checkable
class PlatformAdapter(Protocol):
    platform: str
    name: str

    def render(self, profile: ConfigProfile) -> list[RenderedSnippet]: ...


def discover_sdk_adapters() -> list[SDKAdapter]:
    """Discover all registered SDK adapters via entry points."""
    eps = entry_points(group=SDK_ADAPTER_GROUP)
    adapters: list[SDKAdapter] = []
    for ep in eps:
        obj = ep.load()
        adapter = obj() if callable(obj) else obj
        if not isinstance(adapter, SDKAdapter):
            raise TypeError(f"{ep.name} does not implement SDKAdapter")
        adapters.append(adapter)
    return adapters


def discover_platform_adapters() -> list[PlatformAdapter]:
    """Discover all registered Platform adapters via entry points."""
    eps = entry_points(group=PLATFORM_ADAPTER_GROUP)
    adapters: list[PlatformAdapter] = []
    for ep in eps:
        obj = ep.load()
        adapter = obj() if callable(obj) else obj
        if not isinstance(adapter, PlatformAdapter):
            raise TypeError(f"{ep.name} does not implement PlatformAdapter")
        adapters.append(adapter)
    return adapters


@runtime_checkable
class DeploymentAdapter(Protocol):
    platform: str
    name: str

    def render_deployment(
        self,
        profile: ConfigProfile,
        annotations: dict[str, str],
    ) -> DeploymentProfile: ...


def discover_deployment_adapters() -> list[DeploymentAdapter]:
    """Discover all registered Deployment adapters via entry points."""
    eps = entry_points(group=DEPLOYMENT_ADAPTER_GROUP)
    adapters: list[DeploymentAdapter] = []
    for ep in eps:
        obj = ep.load()
        adapter = obj() if callable(obj) else obj
        if not isinstance(adapter, DeploymentAdapter):
            raise TypeError(f"{ep.name} does not implement DeploymentAdapter")
        adapters.append(adapter)
    return adapters
