"""ECS Platform Inspector — queries ECS + CloudWatch for deployment state."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from copilot_core.deployment import (
        AutoscalerState,
        DeploymentContext,
        DSQLConnectionState,
        ResourceIdentity,
        ServiceReplicaState,
    )

_log = logging.getLogger(__name__)

_TEMPORAL_SERVICES = ("history", "matching", "frontend", "worker")


class ECSInspector:
    platform: str = "ecs"
    name: str = "ecs-inspector"

    async def inspect(self, identity: ResourceIdentity) -> DeploymentContext | None:
        """Query ECS + CloudWatch for deployment state.

        Returns None on any exception (graceful fallback).
        """
        try:
            return await self._do_inspect(identity)
        except Exception:
            _log.warning("ECS inspection failed, returning None", exc_info=True)
            return None

    async def _do_inspect(self, identity: ResourceIdentity) -> DeploymentContext:
        import boto3
        from whenever import Instant

        from copilot_core.deployment import DeploymentContext

        cluster_arn = identity.platform_identifier
        region = cluster_arn.split(":")[3] if ":" in cluster_arn else "us-east-1"

        ecs = boto3.client("ecs", region_name=region)
        cw = boto3.client("cloudwatch", region_name=region)

        service_states = {}
        for svc in _TEMPORAL_SERVICES:
            state = await self._describe_service(ecs, cluster_arn, svc)
            service_states[svc] = state

        autoscaler = await self._get_autoscaling_state(cluster_arn, region)
        dsql = await self._get_dsql_state(cw, identity.dsql_endpoint, region)

        return DeploymentContext(
            history=service_states["history"],
            matching=service_states["matching"],
            frontend=service_states["frontend"],
            worker=service_states["worker"],
            autoscaler=autoscaler,
            dsql=dsql,
            timestamp=str(Instant.now()),
        )

    @staticmethod
    async def _describe_service(
        ecs_client: object,
        cluster_arn: str,
        service: str,
    ) -> ServiceReplicaState:
        from copilot_core.deployment import ServiceReplicaState

        resp = ecs_client.describe_services(  # type: ignore[union-attr]
            cluster=cluster_arn,
            services=[f"temporal-{service}"],
        )
        services = resp.get("services", [])
        if not services:
            return ServiceReplicaState(running=0, desired=0, pending=0)

        svc = services[0]
        return ServiceReplicaState(
            running=svc.get("runningCount", 0),
            desired=svc.get("desiredCount", 0),
            pending=svc.get("pendingCount", 0),
        )

    @staticmethod
    async def _get_autoscaling_state(
        cluster_arn: str,
        region: str,
    ) -> AutoscalerState | None:
        import boto3

        from copilot_core.deployment import AutoscalerState

        try:
            aas = boto3.client("application-autoscaling", region_name=region)
            resp = aas.describe_scalable_targets(
                ServiceNamespace="ecs",
                ResourceIds=[f"service/{cluster_arn.split('/')[-1]}/temporal-history"],
            )
            targets = resp.get("ScalableTargets", [])
            if not targets:
                return None

            target = targets[0]
            return AutoscalerState(
                min_capacity=target.get("MinCapacity", 0),
                max_capacity=target.get("MaxCapacity", 0),
                desired_capacity=target.get("MinCapacity", 0),
                actively_scaling=False,
            )
        except Exception:
            return None

    @staticmethod
    async def _get_dsql_state(
        cw_client: object,
        dsql_endpoint: str,
        region: str,
    ) -> DSQLConnectionState | None:
        from copilot_core.deployment import DSQLConnectionState

        try:
            from whenever import Instant, TimeDelta

            now = Instant.now()
            start = now - TimeDelta(minutes=5)

            resp = cw_client.get_metric_statistics(  # type: ignore[union-attr]
                Namespace="AWS/AuroraDSQL",
                MetricName="DatabaseConnections",
                Dimensions=[{"Name": "DBClusterIdentifier", "Value": dsql_endpoint}],
                StartTime=start.py_datetime(),
                EndTime=now.py_datetime(),
                Period=300,
                Statistics=["Average"],
            )
            datapoints = resp.get("Datapoints", [])
            current = int(datapoints[0]["Average"]) if datapoints else 0

            return DSQLConnectionState(
                current_connections=current,
                max_connections=10_000,
            )
        except Exception:
            return None
