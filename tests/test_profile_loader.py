"""Tests for deployment profile loading (Layer 4)."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from copilot.profile_loader import load_deployment_profile
from copilot_core.deployment import (
    AutoscalerType,
    DeploymentProfile,
    ResourceIdentity,
    ScalingTopology,
    ServiceScalingBounds,
)


def _make_profile(**overrides) -> DeploymentProfile:
    defaults = {
        "preset_name": "starter",
        "throughput_range_min": 0.0,
        "throughput_range_max": 50.0,
        "resource_identity": ResourceIdentity(
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
            platform_identifier="temporal-dev",
            platform_type="compose",
        ),
    }
    defaults.update(overrides)
    return DeploymentProfile(**defaults)


# --- File loading ---


def test_load_from_file(tmp_path):
    profile = _make_profile()
    path = tmp_path / "profile.json"
    path.write_text(profile.model_dump_json())

    loaded = load_deployment_profile(str(path))
    assert loaded.preset_name == "starter"
    assert loaded.resource_identity is not None
    assert loaded.resource_identity.platform_type == "compose"


def test_load_from_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        load_deployment_profile(str(tmp_path / "nonexistent.json"))


def test_load_from_file_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not json")
    with pytest.raises(ValidationError):
        load_deployment_profile(str(path))


def test_load_from_file_wrong_schema(tmp_path):
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps({"foo": "bar"}))
    with pytest.raises(ValidationError):
        load_deployment_profile(str(path))


def test_load_from_file_with_full_topology(tmp_path):
    profile = _make_profile(
        scaling_topology=ScalingTopology(
            history=ServiceScalingBounds(min_replicas=1, max_replicas=1),
            matching=ServiceScalingBounds(min_replicas=1, max_replicas=1),
            frontend=ServiceScalingBounds(min_replicas=1, max_replicas=1),
            worker=ServiceScalingBounds(min_replicas=1, max_replicas=1),
            autoscaler_type=AutoscalerType.FIXED,
        ),
    )
    path = tmp_path / "profile.json"
    path.write_text(profile.model_dump_json())

    loaded = load_deployment_profile(str(path))
    assert loaded.scaling_topology is not None
    assert loaded.scaling_topology.autoscaler_type == AutoscalerType.FIXED


# --- S3 loading ---


def test_load_from_s3():
    profile = _make_profile()
    body_mock = MagicMock()
    body_mock.read.return_value = profile.model_dump_json().encode()

    s3_mock = MagicMock()
    s3_mock.get_object.return_value = {"Body": body_mock}

    with patch("boto3.client", return_value=s3_mock):
        loaded = load_deployment_profile("s3://my-bucket/profiles/dev.json")

    s3_mock.get_object.assert_called_once_with(Bucket="my-bucket", Key="profiles/dev.json")
    assert loaded.preset_name == "starter"


def test_load_from_s3_invalid_uri():
    with pytest.raises(ValueError, match="Invalid S3 URI"):
        load_deployment_profile("s3://bucket-only")


# --- Round-trip property ---


def test_deployment_profile_file_round_trip(tmp_path):
    """Any valid DeploymentProfile written to file and loaded back is equivalent."""
    profile = _make_profile(
        preset_name="mid-scale",
        throughput_range_min=50.0,
        throughput_range_max=500.0,
        scaling_topology=ScalingTopology(
            history=ServiceScalingBounds(min_replicas=2, max_replicas=8),
            matching=ServiceScalingBounds(min_replicas=2, max_replicas=6),
            frontend=ServiceScalingBounds(min_replicas=2, max_replicas=4),
            worker=ServiceScalingBounds(min_replicas=1, max_replicas=2),
            autoscaler_type=AutoscalerType.HPA,
        ),
        resource_identity=ResourceIdentity(
            dsql_endpoint="prod.dsql.eu-west-1.on.aws",
            platform_identifier="arn:aws:ecs:eu-west-1:123456789:cluster/temporal",
            platform_type="ecs",
            amp_workspace_id="ws-abc123",
        ),
        config_profile_id="profile-v2",
    )
    path = tmp_path / "profile.json"
    path.write_text(profile.model_dump_json())

    loaded = load_deployment_profile(str(path))
    assert loaded == profile
