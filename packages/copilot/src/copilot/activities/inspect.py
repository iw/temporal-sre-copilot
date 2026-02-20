"""Activity for fetching deployment context from the monitored cluster."""

import logging

from pydantic import BaseModel
from temporalio import activity

from copilot_core.deployment import (  # noqa: TC001 — Pydantic needs runtime
    DeploymentContext,
    ResourceIdentity,
)

_log = logging.getLogger(__name__)


class FetchDeploymentContextInput(BaseModel):
    """Input for the fetch_deployment_context activity."""

    resource_identity: ResourceIdentity


@activity.defn
async def fetch_deployment_context(
    input: FetchDeploymentContextInput,
) -> DeploymentContext | None:
    """Fetch deployment context from the monitored cluster.

    Discovers platform inspectors, finds one matching the platform type,
    and calls inspect(). Returns None if no inspector is available or
    if the inspector returns None.
    """
    from copilot.inspectors import discover_platform_inspectors

    inspectors = discover_platform_inspectors()
    target_platform = input.resource_identity.platform_type

    for inspector in inspectors:
        if inspector.platform == target_platform:
            activity.logger.info("Using %s inspector for %s", inspector.name, target_platform)
            result = await inspector.inspect(input.resource_identity)
            if result is None:
                activity.logger.warning("Inspector %s returned None", inspector.name)
            return result

    activity.logger.info("No inspector available for platform type: %s", target_platform)
    return None
