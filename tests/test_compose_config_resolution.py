"""Tests for Compose deployment adapter config resolution (Layer 4)."""

import pytest

from dsql_config.adapters.compose import (
    ComposeDeploymentAdapter,
    _parse_compose_config,
    _parse_memory_mib,
)
from dsql_config.compiler import ConfigCompiler
from dsql_config.models import ConfigProfile  # noqa: TC001 — used in helper return type
from dsql_config.registry import build_default_registry


def _compile_starter() -> ConfigProfile:
    compiler = ConfigCompiler(build_default_registry())
    return compiler.compile("starter").profile


# --- _parse_compose_config ---


def test_parse_compose_config_extracts_dsql_endpoint():
    yaml_content = """
services:
  temporal-history:
    environment:
      TEMPORAL_SQL_HOST: test.dsql.eu-west-1.on.aws
"""
    result = _parse_compose_config(yaml_content)
    assert result["dsql_endpoint"] == "test.dsql.eu-west-1.on.aws"


def test_parse_compose_config_extracts_resource_limits():
    yaml_content = """
services:
  temporal-dsql-history:
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: "4G"
  temporal-dsql-matching:
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: "2G"
"""
    result = _parse_compose_config(yaml_content)
    assert result["history_cpu_limit"] == "2000"
    assert result["history_memory_limit"] == "4096"
    assert result["matching_cpu_limit"] == "1000"
    assert result["matching_memory_limit"] == "2048"


def test_parse_compose_config_env_list_format():
    yaml_content = """
services:
  temporal-history:
    environment:
      - TEMPORAL_SQL_HOST=test.dsql.eu-west-1.on.aws
      - OTHER_VAR=value
"""
    result = _parse_compose_config(yaml_content)
    assert result["dsql_endpoint"] == "test.dsql.eu-west-1.on.aws"


def test_parse_compose_config_invalid_yaml():
    result = _parse_compose_config("not: valid: yaml: [")
    assert result == {}


def test_parse_compose_config_empty():
    result = _parse_compose_config("")
    assert result == {}


def test_parse_compose_config_no_temporal_services():
    yaml_content = """
services:
  redis:
    image: redis:latest
"""
    result = _parse_compose_config(yaml_content)
    assert "dsql_endpoint" not in result


# --- _parse_memory_mib ---


def test_parse_memory_mib_gigabytes():
    assert _parse_memory_mib("4G") == 4096
    assert _parse_memory_mib("1GB") == 1024


def test_parse_memory_mib_megabytes():
    assert _parse_memory_mib("512M") == 512
    assert _parse_memory_mib("256MB") == 256


def test_parse_memory_mib_numeric():
    # Bytes as integer
    assert _parse_memory_mib(536870912) == 512  # 512 MiB in bytes


# --- ComposeDeploymentAdapter with compose_config ---


def test_adapter_with_compose_config():
    profile = _compile_starter()
    adapter = ComposeDeploymentAdapter()

    compose_yaml = """
services:
  temporal-dsql-history:
    environment:
      TEMPORAL_SQL_HOST: dev.dsql.eu-west-1.on.aws
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: "4G"
  temporal-dsql-matching:
    environment:
      TEMPORAL_SQL_HOST: dev.dsql.eu-west-1.on.aws
"""
    result = adapter.render_deployment(
        profile,
        {"compose_config": compose_yaml, "compose_project_name": "dev"},
    )
    assert result.resource_identity is not None
    assert result.resource_identity.dsql_endpoint == "dev.dsql.eu-west-1.on.aws"
    assert result.resource_identity.platform_type == "compose"
    assert result.resource_identity.platform_identifier == "dev"
    assert result.scaling_topology is not None
    assert result.scaling_topology.history.resource_limits.cpu_millicores == 2000
    assert result.scaling_topology.history.resource_limits.memory_mib == 4096


def test_adapter_annotation_overrides_compose_config():
    """Manual annotations take precedence over compose config values."""
    profile = _compile_starter()
    adapter = ComposeDeploymentAdapter()

    compose_yaml = """
services:
  temporal-dsql-history:
    environment:
      TEMPORAL_SQL_HOST: compose.dsql.eu-west-1.on.aws
"""
    result = adapter.render_deployment(
        profile,
        {
            "compose_config": compose_yaml,
            "dsql_endpoint": "override.dsql.eu-west-1.on.aws",
        },
    )
    assert result.resource_identity is not None
    assert result.resource_identity.dsql_endpoint == "override.dsql.eu-west-1.on.aws"


def test_adapter_requires_dsql_endpoint():
    """Adapter raises when no dsql_endpoint is available from any source."""
    profile = _compile_starter()
    adapter = ComposeDeploymentAdapter()

    with pytest.raises(KeyError, match="dsql_endpoint"):
        adapter.render_deployment(profile, {})


def test_adapter_without_compose_config():
    """Adapter works with manual annotations only (no compose config)."""
    profile = _compile_starter()
    adapter = ComposeDeploymentAdapter()

    result = adapter.render_deployment(
        profile,
        {"dsql_endpoint": "test.dsql.eu-west-1.on.aws"},
    )
    assert result.preset_name == "starter"
    assert result.scaling_topology is not None
    assert result.scaling_topology.history.min_replicas == 1
    assert result.scaling_topology.history.max_replicas == 1
