"""Unit tests for adapter outputs.

Validates: Requirements 4a.2, 4a.3, 4b.2, 4b.3
"""

from __future__ import annotations

import json

from dsql_config.adapters import discover_platform_adapters, discover_sdk_adapters
from dsql_config.adapters.compose import ComposeAdapter
from dsql_config.adapters.ecs import ECSAdapter
from dsql_config.adapters.go_sdk import GoSDKAdapter
from dsql_config.adapters.python_sdk import PythonSDKAdapter
from dsql_config.compiler import ConfigCompiler
from dsql_config.registry import build_default_registry


def _compile(preset):
    compiler = ConfigCompiler(build_default_registry())
    return compiler.compile(preset).profile


class TestGoSDKAdapter:
    def test_renders_worker_options(self):
        profile = _compile("mid-scale")
        snippet = GoSDKAdapter().render(profile)
        assert snippet.language == "go"
        assert snippet.filename == "worker_options.go"
        assert "worker.Options{" in snippet.content
        assert "MaxConcurrentActivityExecutionSize" in snippet.content

    def test_includes_preset_comment(self):
        profile = _compile("starter")
        snippet = GoSDKAdapter().render(profile)
        assert "Preset: starter" in snippet.content

    def test_modifier_in_comment(self):
        compiler = ConfigCompiler(build_default_registry())
        profile = compiler.compile("mid-scale", modifier="orchestrator").profile
        snippet = GoSDKAdapter().render(profile)
        assert "orchestrator" in snippet.content


class TestPythonSDKAdapter:
    def test_renders_worker_config(self):
        profile = _compile("mid-scale")
        snippet = PythonSDKAdapter().render(profile)
        assert snippet.language == "python"
        assert snippet.filename == "worker_config.py"
        assert "Worker(" in snippet.content
        assert "max_concurrent_activities" in snippet.content

    def test_includes_preset_comment(self):
        profile = _compile("high-throughput")
        snippet = PythonSDKAdapter().render(profile)
        assert "Preset: high-throughput" in snippet.content


class TestECSAdapter:
    def test_renders_shared_and_per_service(self):
        profile = _compile("mid-scale")
        snippets = ECSAdapter().render(profile)
        filenames = [s.filename for s in snippets]
        assert "ecs-shared-env.json" in filenames
        assert "ecs-history-env.json" in filenames
        assert "ecs-matching-env.json" in filenames

    def test_shared_env_is_valid_json(self):
        profile = _compile("mid-scale")
        snippets = ECSAdapter().render(profile)
        shared = next(s for s in snippets if s.filename == "ecs-shared-env.json")
        parsed = json.loads(shared.content)
        assert isinstance(parsed, list)
        assert all("name" in e and "value" in e for e in parsed)

    def test_dsql_env_vars_present(self):
        profile = _compile("mid-scale")
        snippets = ECSAdapter().render(profile)
        shared = next(s for s in snippets if s.filename == "ecs-shared-env.json")
        parsed = json.loads(shared.content)
        names = {e["name"] for e in parsed}
        assert "TEMPORAL_SQL_MAX_CONNS" in names
        assert "DSQL_RESERVOIR_ENABLED" in names


class TestComposeAdapter:
    def test_renders_dotenv_files(self):
        profile = _compile("mid-scale")
        snippets = ComposeAdapter().render(profile)
        filenames = [s.filename for s in snippets]
        assert "dsql.env" in filenames

    def test_shared_env_format(self):
        profile = _compile("mid-scale")
        snippets = ComposeAdapter().render(profile)
        shared = next(s for s in snippets if s.filename == "dsql.env")
        assert "TEMPORAL_SQL_MAX_CONNS=" in shared.content
        assert "DSQL_RESERVOIR_ENABLED=" in shared.content

    def test_per_service_replica_files(self):
        profile = _compile("mid-scale")
        snippets = ComposeAdapter().render(profile)
        filenames = [s.filename for s in snippets]
        assert "history.env" in filenames


class TestAdapterDiscovery:
    def test_sdk_adapters_discovered(self):
        adapters = discover_sdk_adapters()
        names = {a.name for a in adapters}
        assert "Go SDK" in names
        assert "Python SDK" in names

    def test_platform_adapters_discovered(self):
        adapters = discover_platform_adapters()
        names = {a.name for a in adapters}
        assert "AWS ECS" in names
        assert "Docker Compose" in names
