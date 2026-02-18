"""AWS ECS platform adapter.

Renders per-service environment variable maps for ECS task definitions.
"""

from dsql_config.models import ConfigProfile, RenderedSnippet

# Mapping from parameter keys to ECS environment variable names
_DSQL_ENV_MAP: dict[str, str] = {
    "persistence.maxConns": "TEMPORAL_SQL_MAX_CONNS",
    "persistence.maxIdleConns": "TEMPORAL_SQL_MAX_IDLE_CONNS",
    "dsql.max_conn_lifetime": "TEMPORAL_SQL_MAX_CONN_LIFETIME",
    "dsql.connection_timeout": "TEMPORAL_SQL_CONNECTION_TIMEOUT",
    "dsql.reservoir_enabled": "DSQL_RESERVOIR_ENABLED",
    "dsql.reservoir_target_ready": "DSQL_RESERVOIR_TARGET_READY",
    "dsql.reservoir_base_lifetime": "DSQL_RESERVOIR_BASE_LIFETIME",
    "dsql.reservoir_lifetime_jitter": "DSQL_RESERVOIR_LIFETIME_JITTER",
    "dsql.reservoir_guard_window": "DSQL_RESERVOIR_GUARD_WINDOW",
    "dsql.reservoir_inflight_limit": "DSQL_RESERVOIR_INFLIGHT_LIMIT",
    "dsql.connection_rate_limit": "DSQL_CONNECTION_RATE_LIMIT",
    "dsql.connection_burst_limit": "DSQL_CONNECTION_BURST_LIMIT",
    "dsql.distributed_rate_limiter_enabled": "DSQL_DISTRIBUTED_RATE_LIMITER_ENABLED",
    "dsql.distributed_rate_limiter_table": "DSQL_DISTRIBUTED_RATE_LIMITER_TABLE",
    "dsql.token_bucket_enabled": "DSQL_TOKEN_BUCKET_ENABLED",
    "dsql.token_bucket_rate": "DSQL_TOKEN_BUCKET_RATE",
    "dsql.token_bucket_capacity": "DSQL_TOKEN_BUCKET_CAPACITY",
    "dsql.slot_block_enabled": "DSQL_DISTRIBUTED_CONN_LEASE_ENABLED",
    "dsql.slot_block_size": "DSQL_SLOT_BLOCK_SIZE",
    "dsql.slot_block_count": "DSQL_SLOT_BLOCK_COUNT",
}

# Service-specific dynamic config keys
_SERVICE_DYNAMIC_CONFIG: dict[str, list[str]] = {
    "history": [
        "history.persistenceMaxQPS",
        "history.timerProcessorMaxPollRPS",
        "history.timerProcessorUpdateAckInterval",
        "history.maxBufferedQueryCount",
    ],
    "matching": [
        "matching.persistenceMaxQPS",
        "matching.maxTaskBatchSize",
        "matching.getTasksBatchSize",
        "matching.longPollExpirationInterval",
        "matching.numTaskqueueReadPartitions",
        "matching.numTaskqueueWritePartitions",
    ],
    "frontend": ["frontend.persistenceMaxQPS"],
    "worker": [],
}


class ECSAdapter:
    platform: str = "ecs"
    name: str = "AWS ECS"

    def render(self, profile: ConfigProfile) -> list[RenderedSnippet]:
        snippets: list[RenderedSnippet] = []

        # Shared DSQL environment variables (same for all services)
        shared_env = self._render_shared_env(profile)
        snippets.append(
            RenderedSnippet(
                language="json",
                filename="ecs-shared-env.json",
                content=shared_env,
            )
        )

        # Per-service snippets
        for service in ("history", "matching", "frontend", "worker"):
            service_env = self._render_service_env(profile, service)
            snippets.append(
                RenderedSnippet(
                    language="json",
                    filename=f"ecs-{service}-env.json",
                    content=service_env,
                )
            )

        return snippets

    @staticmethod
    def _render_shared_env(profile: ConfigProfile) -> str:
        import json

        env_list: list[dict[str, str]] = []
        for key, env_name in _DSQL_ENV_MAP.items():
            p = profile.get_param(key)
            if p:
                value = str(p.value).lower() if isinstance(p.value, bool) else str(p.value)
                env_list.append({"name": env_name, "value": value})

        return json.dumps(env_list, indent=2)

    @staticmethod
    def _render_service_env(profile: ConfigProfile, service: str) -> str:
        import json

        env_list: list[dict[str, str]] = []
        replicas_key = f"{service}.replicas"
        p = profile.get_param(replicas_key)
        if p:
            env_list.append({"name": f"TEMPORAL_{service.upper()}_REPLICAS", "value": str(p.value)})

        return json.dumps(env_list, indent=2)
