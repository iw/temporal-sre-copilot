"""FastAPI router for Behaviour Profile CRUD and comparison.

Endpoints:
  POST   /profiles           — create a profile (query AMP, store in S3 + DSQL)
  GET    /profiles           — list profiles with optional filters
  GET    /profiles/{id}      — retrieve full profile from S3
  POST   /profiles/{id}/baseline — designate as baseline
  POST   /profiles/compare   — compare two profiles
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from whenever import Instant, TimeDelta

from behaviour_profiles.comparison import compare_profiles
from behaviour_profiles.models import (
    BehaviourProfile,
    CompareRequest,
    ConfigSnapshot,
    CreateProfileRequest,
    DSQLPluginSnapshot,
    ProfileComparison,
    ProfileMetadata,
    WorkerOptionsSnapshot,
)

if TYPE_CHECKING:
    from behaviour_profiles.storage import ProfileStorage

logger = logging.getLogger("behaviour_profiles.api")

router = APIRouter(prefix="/profiles", tags=["profiles"])

# These are set at mount time by the copilot app via `configure_profile_router`
_storage: ProfileStorage | None = None
_amp_endpoint: str | None = None


def configure_profile_router(
    *,
    storage: ProfileStorage,
    amp_endpoint: str,
) -> None:
    """Inject dependencies into the profile router.

    Called by the copilot app during startup before mounting the router.
    """
    global _storage, _amp_endpoint
    _storage = storage
    _amp_endpoint = amp_endpoint


def _get_storage() -> ProfileStorage:
    if _storage is None:
        raise HTTPException(status_code=503, detail="Profile storage not configured")
    return _storage


_MAX_WINDOW = TimeDelta(hours=24)


@router.post("/", status_code=201)
async def create_profile(request: CreateProfileRequest) -> ProfileMetadata:
    """Create a behaviour profile by querying AMP and storing the result."""
    from behaviour_profiles.telemetry import collect_telemetry

    # Validate time range
    start = Instant.parse_iso(request.time_window_start)
    end = Instant.parse_iso(request.time_window_end)
    if end - start > _MAX_WINDOW:
        raise HTTPException(
            status_code=400,
            detail=f"Time window exceeds maximum of 24 hours (requested: {end - start})",
        )
    if end <= start:
        raise HTTPException(
            status_code=400, detail="time_window_end must be after time_window_start"
        )

    if _amp_endpoint is None:
        raise HTTPException(status_code=503, detail="AMP endpoint not configured")

    storage = _get_storage()

    # Collect telemetry from AMP
    telemetry = await collect_telemetry(
        amp_endpoint=_amp_endpoint,
        start=request.time_window_start,
        end=request.time_window_end,
    )

    # Build profile with empty config snapshot (config collection is separate)
    profile = BehaviourProfile(
        id=str(uuid.uuid4()),
        name=request.name,
        label=request.label,
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        task_queue=request.task_queue,
        time_window_start=request.time_window_start,
        time_window_end=request.time_window_end,
        config_snapshot=ConfigSnapshot(
            dynamic_config=[],
            server_env_vars=[],
            worker_options=WorkerOptionsSnapshot(),
            dsql_plugin_config=DSQLPluginSnapshot(
                reservoir_enabled=False,
                reservoir_target_ready=0,
                reservoir_base_lifetime_min=0,
                reservoir_lifetime_jitter_min=0,
                reservoir_guard_window_sec=0,
                max_conns=0,
                max_idle_conns=0,
                max_conn_lifetime_min=0,
                distributed_rate_limiter_enabled=False,
                token_bucket_enabled=False,
                slot_block_enabled=False,
            ),
        ),
        telemetry=telemetry,
        created_at=Instant.now().format_iso(),
    )

    return await storage.save(profile)


@router.get("/")
async def list_profiles(
    cluster: str | None = None,
    label: str | None = None,
    namespace: str | None = None,
) -> list[ProfileMetadata]:
    """List profile metadata with optional filters."""
    storage = _get_storage()
    return await storage.list(cluster=cluster, label=label, namespace=namespace)


@router.get("/{profile_id}")
async def get_profile(profile_id: str) -> BehaviourProfile:
    """Retrieve full profile from S3."""
    storage = _get_storage()
    try:
        return await storage.get(profile_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found") from exc


@router.post("/{profile_id}/baseline")
async def set_baseline(profile_id: str) -> ProfileMetadata:
    """Designate a profile as the baseline for its cluster+namespace."""
    storage = _get_storage()
    try:
        return await storage.set_baseline(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/compare")
async def compare(request: CompareRequest) -> ProfileComparison:
    """Compare two profiles and return structured diffs."""
    if request.profile_a_id == request.profile_b_id:
        raise HTTPException(status_code=400, detail="Cannot compare a profile with itself")

    storage = _get_storage()
    try:
        profile_a = await storage.get(request.profile_a_id)
        profile_b = await storage.get(request.profile_b_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="One or both profiles not found") from exc

    return compare_profiles(profile_a, profile_b)
