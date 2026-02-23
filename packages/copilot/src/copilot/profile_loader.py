"""Load a DeploymentProfile from a local file or S3 URI.

The DEPLOYMENT_PROFILE env var points to either:
- A local file path (e.g., /app/deployment_profile.json)
- An S3 URI (e.g., s3://bucket/key)
"""

import logging
from pathlib import Path

from copilot_core.deployment import DeploymentProfile

_log = logging.getLogger(__name__)


def load_deployment_profile(location: str) -> DeploymentProfile:
    """Load a DeploymentProfile from a local file or S3 URI.

    Args:
        location: Local file path or s3://bucket/key URI.

    Returns:
        Parsed DeploymentProfile.

    Raises:
        FileNotFoundError: If local file does not exist.
        ValueError: If the JSON is not a valid DeploymentProfile.
    """
    if location.startswith("s3://"):
        return _load_from_s3(location)
    return _load_from_file(location)


def _load_from_file(path: str) -> DeploymentProfile:
    p = Path(path)
    if not p.exists():
        msg = f"Deployment profile not found: {path}"
        raise FileNotFoundError(msg)
    content = p.read_text()
    profile = DeploymentProfile.model_validate_json(content)
    _log.info(
        "Loaded deployment profile from file: preset=%s platform=%s dsql=%s",
        profile.preset_name,
        profile.resource_identity.platform_type if profile.resource_identity else "none",
        profile.resource_identity.dsql_endpoint if profile.resource_identity else "none",
    )
    return profile


def _load_from_s3(uri: str) -> DeploymentProfile:
    import boto3

    parts = uri.removeprefix("s3://").split("/", 1)
    if len(parts) != 2 or not parts[1]:
        msg = f"Invalid S3 URI: {uri}. Expected s3://bucket/key"
        raise ValueError(msg)
    bucket, key = parts[0], parts[1]
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=bucket, Key=key)
    content = resp["Body"].read().decode()
    profile = DeploymentProfile.model_validate_json(content)
    _log.info(
        "Loaded deployment profile from S3: preset=%s platform=%s uri=%s",
        profile.preset_name,
        profile.resource_identity.platform_type if profile.resource_identity else "none",
        uri,
    )
    return profile
