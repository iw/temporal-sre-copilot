"""Backward compatibility — maps existing DSQL environment variables to parameter keys.

When no preset is explicitly provided, existing env vars are treated as
overrides on the "starter" preset. The compiler also reports which env vars
are redundant with preset defaults.
"""

from __future__ import annotations

from pydantic import BaseModel

from copilot_core.types import ParameterOverrides

# Reverse mapping: env var name → parameter key
ENV_VAR_TO_PARAM: dict[str, str] = {
    "TEMPORAL_SQL_MAX_CONNS": "persistence.maxConns",
    "TEMPORAL_SQL_MAX_IDLE_CONNS": "persistence.maxIdleConns",
    "TEMPORAL_SQL_MAX_CONN_LIFETIME": "dsql.max_conn_lifetime",
    "TEMPORAL_SQL_CONNECTION_TIMEOUT": "dsql.connection_timeout",
    "DSQL_RESERVOIR_ENABLED": "dsql.reservoir_enabled",
    "DSQL_RESERVOIR_TARGET_READY": "dsql.reservoir_target_ready",
    "DSQL_RESERVOIR_BASE_LIFETIME": "dsql.reservoir_base_lifetime",
    "DSQL_RESERVOIR_LIFETIME_JITTER": "dsql.reservoir_lifetime_jitter",
    "DSQL_RESERVOIR_GUARD_WINDOW": "dsql.reservoir_guard_window",
    "DSQL_RESERVOIR_INFLIGHT_LIMIT": "dsql.reservoir_inflight_limit",
    "DSQL_CONNECTION_RATE_LIMIT": "dsql.connection_rate_limit",
    "DSQL_CONNECTION_BURST_LIMIT": "dsql.connection_burst_limit",
    "DSQL_DISTRIBUTED_RATE_LIMITER_ENABLED": "dsql.distributed_rate_limiter_enabled",
    "DSQL_DISTRIBUTED_RATE_LIMITER_TABLE": "dsql.distributed_rate_limiter_table",
    "DSQL_TOKEN_BUCKET_ENABLED": "dsql.token_bucket_enabled",
    "DSQL_TOKEN_BUCKET_RATE": "dsql.token_bucket_rate",
    "DSQL_TOKEN_BUCKET_CAPACITY": "dsql.token_bucket_capacity",
    "DSQL_DISTRIBUTED_CONN_LEASE_ENABLED": "dsql.slot_block_enabled",
    "DSQL_SLOT_BLOCK_SIZE": "dsql.slot_block_size",
    "DSQL_SLOT_BLOCK_COUNT": "dsql.slot_block_count",
    "DSQL_STAGGERED_STARTUP": "dsql.staggered_startup",
    "DSQL_STAGGERED_STARTUP_MAX_DELAY": "dsql.staggered_startup_max_delay",
}

# All known env var names (for acceptance check)
KNOWN_ENV_VARS: set[str] = set(ENV_VAR_TO_PARAM.keys())


class RedundantEnvVar(BaseModel):
    """An environment variable whose value matches the preset default."""

    env_var: str
    parameter_key: str
    value: str
    preset_default: str


def env_vars_to_overrides(env_vars: dict[str, str]) -> ParameterOverrides:
    """Convert a dict of environment variables to ParameterOverrides.

    Unknown env vars are silently ignored (they may be non-DSQL settings).
    """
    values: dict[str, int | float | str | bool] = {}
    for env_name, raw_value in env_vars.items():
        param_key = ENV_VAR_TO_PARAM.get(env_name)
        if param_key is None:
            continue
        values[param_key] = _coerce_value(raw_value)
    return ParameterOverrides(values=values)


def find_redundant_env_vars(
    env_vars: dict[str, str],
    preset_defaults: dict[str, int | float | str | bool],
) -> list[RedundantEnvVar]:
    """Identify env vars whose values match the preset-derived defaults."""
    redundant: list[RedundantEnvVar] = []
    for env_name, raw_value in env_vars.items():
        param_key = ENV_VAR_TO_PARAM.get(env_name)
        if param_key is None:
            continue
        if param_key not in preset_defaults:
            continue
        coerced = _coerce_value(raw_value)
        default = preset_defaults[param_key]
        if _values_match(coerced, default):
            redundant.append(
                RedundantEnvVar(
                    env_var=env_name,
                    parameter_key=param_key,
                    value=raw_value,
                    preset_default=str(default),
                )
            )
    return redundant


def _coerce_value(raw: str) -> int | float | str | bool:
    """Coerce a string env var value to the appropriate Python type."""
    lower = raw.strip().lower()
    if lower in ("true", "1", "yes"):
        return True
    if lower in ("false", "0", "no"):
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _values_match(a: int | float | str | bool, b: int | float | str | bool) -> bool:
    """Compare two values, handling type coercion for string/int/bool comparisons."""
    if a == b:
        return True
    # Handle "50" == 50, "true" == True, etc.
    return str(a).lower().strip() == str(b).lower().strip()
