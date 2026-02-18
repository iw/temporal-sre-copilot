"""Unit tests for backward compatibility with existing env vars.

Validates: Requirements 8.1, 8.2
"""

from __future__ import annotations

from copilot_core.types import ParameterOverrides
from dsql_config.adapters.ecs import _DSQL_ENV_MAP
from dsql_config.compiler import ConfigCompiler
from dsql_config.registry import build_default_registry


def _compiler():
    return ConfigCompiler(build_default_registry())


class TestEnvVarFallbackToStarter:
    """Req 8.1: When no preset is provided, existing env vars work as overrides on starter."""

    def test_compile_starter_with_overrides(self):
        compiler = _compiler()
        result = compiler.compile(
            "starter",
            overrides=ParameterOverrides(values={"persistence.maxConns": 25}),
        )
        p = result.profile.get_param("persistence.maxConns")
        assert p is not None
        assert p.value == 25
        assert p.source == "override"

    def test_starter_is_default_baseline(self):
        compiler = _compiler()
        result = compiler.compile("starter")
        # Starter should compile without errors
        assert result.profile.preset_name == "starter"


class TestKnownDSQLEnvVarNames:
    """Req 8.2: All known DSQL env var names map to registry parameter keys."""

    def test_all_env_map_keys_exist_in_registry(self):
        registry = build_default_registry()
        for param_key in _DSQL_ENV_MAP:
            entry = registry.get(param_key)
            assert entry is not None, f"Registry missing key for env var mapping: {param_key}"

    def test_env_map_covers_dsql_params(self):
        """All DSQL plugin parameters in the registry have env var mappings."""
        from copilot_core.types import OutputTarget

        registry = build_default_registry()
        dsql_keys = {
            e.key for e in registry.all_entries() if OutputTarget.DSQL_PLUGIN in e.output_targets
        }
        mapped_keys = set(_DSQL_ENV_MAP.keys())
        # Every DSQL plugin param should have an env var mapping
        unmapped = dsql_keys - mapped_keys
        assert not unmapped, f"DSQL params without env var mapping: {unmapped}"


class TestOverrideRedundancyDetection:
    """Req 8.3: Overrides matching preset defaults are still accepted."""

    def test_redundant_override_accepted(self):
        compiler = _compiler()
        # Get starter's default maxConns
        baseline = compiler.compile("starter")
        default_val = baseline.profile.get_param("persistence.maxConns").value

        # Override with same value — should still work
        result = compiler.compile(
            "starter",
            overrides=ParameterOverrides(values={"persistence.maxConns": default_val}),
        )
        p = result.profile.get_param("persistence.maxConns")
        assert p.value == default_val
        assert p.source == "override"
