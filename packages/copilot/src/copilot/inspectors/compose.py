"""Compose Platform Inspector — queries Docker Engine API for deployment state."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from copilot_core.deployment import DeploymentContext, ResourceIdentity, ServiceReplicaState

_log = logging.getLogger(__name__)

_SERVICE_NAMES = {
    "history": "temporal-history",
    "matching": "temporal-matching",
    "frontend": "temporal-frontend",
    "worker": "temporal-worker",
}


class ComposeInspector:
    platform: str = "compose"
    name: str = "compose-inspector"

    async def inspect(self, identity: ResourceIdentity) -> DeploymentContext | None:
        """Query Docker Engine API for Compose deployment state.

        Returns None if Docker Engine API is not accessible.
        """
        try:
            return await self._do_inspect(identity)
        except Exception:
            _log.warning("Compose inspection failed, returning None", exc_info=True)
            return None

    async def _do_inspect(self, identity: ResourceIdentity) -> DeploymentContext:
        import httpx
        from whenever import Instant

        from copilot_core.deployment import AutoscalerState, DeploymentContext

        docker_host = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
        project = identity.platform_identifier

        if docker_host.startswith("unix://"):
            transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
            base_url = "http://localhost"
        else:
            transport = None
            base_url = docker_host

        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            service_states = {}
            for role, container_name in _SERVICE_NAMES.items():
                state = await self._get_service_state(client, project, container_name)
                service_states[role] = state

        total_running = sum(s.running for s in service_states.values())

        return DeploymentContext(
            history=service_states["history"],
            matching=service_states["matching"],
            frontend=service_states["frontend"],
            worker=service_states["worker"],
            autoscaler=AutoscalerState(
                min_capacity=total_running,
                max_capacity=total_running,
                desired_capacity=total_running,
                actively_scaling=False,
            ),
            dsql=None,
            timestamp=str(Instant.now()),
        )

    @staticmethod
    async def _get_service_state(
        client: object,
        project: str,
        container_name: str,
    ) -> ServiceReplicaState:
        import httpx

        from copilot_core.deployment import ServiceReplicaState

        assert isinstance(client, httpx.AsyncClient)

        filters = (
            f'{{"label":["com.docker.compose.project={project}",'
            f'"com.docker.compose.service={container_name}"]}}'
        )
        resp = await client.get(
            "/containers/json",
            params={"filters": filters},
        )

        if resp.status_code != 200:
            return ServiceReplicaState(running=0, desired=0, pending=0)

        containers = resp.json()
        running = sum(1 for c in containers if c.get("State") == "running")

        return ServiceReplicaState(
            running=running,
            desired=running,
            pending=0,
        )
