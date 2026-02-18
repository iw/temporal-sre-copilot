"""Profile storage — S3 for full JSON documents, DSQL for metadata index."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from whenever import Instant

from behaviour_profiles.models import BehaviourProfile, ProfileMetadata

if TYPE_CHECKING:
    from types import SimpleNamespace

    import asyncpg

logger = logging.getLogger("behaviour_profiles.storage")


class ProfileStorage:
    """Stores full profile JSON in S3 and metadata in DSQL."""

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        s3_client: SimpleNamespace,
        bucket: str,
    ) -> None:
        self._pool = pool
        self._s3 = s3_client
        self._bucket = bucket

    def _s3_key(self, profile_id: str) -> str:
        return f"profiles/{profile_id}.json"

    async def save(self, profile: BehaviourProfile) -> ProfileMetadata:
        """Persist profile JSON to S3 and metadata to DSQL."""
        s3_key = self._s3_key(profile.id)

        # S3: store full document
        await self._s3.put_object(
            Bucket=self._bucket,
            Key=s3_key,
            Body=profile.model_dump_json().encode(),
            ContentType="application/json",
        )

        # DSQL: store metadata index row
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO behaviour_profiles
                    (id, name, label, cluster_id, namespace, task_queue,
                     time_window_start, time_window_end, s3_key, is_baseline, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                profile.id,
                profile.name,
                profile.label,
                profile.cluster_id,
                profile.namespace,
                profile.task_queue,
                Instant.parse_iso(profile.time_window_start).py_datetime(),
                Instant.parse_iso(profile.time_window_end).py_datetime(),
                s3_key,
                profile.is_baseline,
                Instant.parse_iso(profile.created_at).py_datetime(),
            )

        return _metadata_from_profile(profile)

    async def get(self, profile_id: str) -> BehaviourProfile:
        """Retrieve full profile from S3."""
        s3_key = self._s3_key(profile_id)
        resp = await self._s3.get_object(Bucket=self._bucket, Key=s3_key)
        body = await resp["Body"].read()
        return BehaviourProfile.model_validate_json(body)

    async def list(
        self,
        *,
        cluster: str | None = None,
        label: str | None = None,
        namespace: str | None = None,
    ) -> list[ProfileMetadata]:
        """List profile metadata with optional filters."""
        clauses: list[str] = []
        params: list[str] = []
        idx = 1

        if cluster:
            clauses.append(f"cluster_id = ${idx}")
            params.append(cluster)
            idx += 1
        if label:
            clauses.append(f"label = ${idx}")
            params.append(label)
            idx += 1
        if namespace:
            clauses.append(f"namespace = ${idx}")
            params.append(namespace)
            idx += 1

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT id, name, label, cluster_id, namespace,
                   time_window_start, time_window_end, is_baseline, created_at
            FROM behaviour_profiles
            {where}
            ORDER BY created_at DESC
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            ProfileMetadata(
                id=str(row["id"]),
                name=row["name"],
                label=row["label"],
                cluster_id=row["cluster_id"],
                namespace=row["namespace"],
                time_window_start=Instant.from_py_datetime(row["time_window_start"]).format_iso(),
                time_window_end=Instant.from_py_datetime(row["time_window_end"]).format_iso(),
                is_baseline=row["is_baseline"],
                created_at=Instant.from_py_datetime(row["created_at"]).format_iso(),
            )
            for row in rows
        ]

    async def set_baseline(self, profile_id: str) -> ProfileMetadata:
        """Designate a profile as baseline.

        Clears previous baseline for same cluster+namespace.
        """
        async with self._pool.acquire() as conn:
            # Get the profile's cluster and namespace
            row = await conn.fetchrow(
                """
                SELECT cluster_id, namespace
                FROM behaviour_profiles
                WHERE id = $1
                """,
                profile_id,
            )
            if not row:
                msg = f"Profile {profile_id} not found"
                raise ValueError(msg)

            # Clear previous baseline for this cluster+namespace
            if row["namespace"]:
                await conn.execute(
                    """
                    UPDATE behaviour_profiles
                    SET is_baseline = FALSE
                    WHERE cluster_id = $1 AND namespace = $2 AND is_baseline = TRUE
                    """,
                    row["cluster_id"],
                    row["namespace"],
                )
            else:
                await conn.execute(
                    """
                    UPDATE behaviour_profiles
                    SET is_baseline = FALSE
                    WHERE cluster_id = $1 AND namespace IS NULL AND is_baseline = TRUE
                    """,
                    row["cluster_id"],
                )

            # Set new baseline
            updated = await conn.fetchrow(
                """
                UPDATE behaviour_profiles
                SET is_baseline = TRUE
                WHERE id = $1
                RETURNING id, name, label, cluster_id, namespace,
                          time_window_start, time_window_end, is_baseline, created_at
                """,
                profile_id,
            )

        return ProfileMetadata(
            id=str(updated["id"]),
            name=updated["name"],
            label=updated["label"],
            cluster_id=updated["cluster_id"],
            namespace=updated["namespace"],
            time_window_start=Instant.from_py_datetime(updated["time_window_start"]).format_iso(),
            time_window_end=Instant.from_py_datetime(updated["time_window_end"]).format_iso(),
            is_baseline=updated["is_baseline"],
            created_at=Instant.from_py_datetime(updated["created_at"]).format_iso(),
        )


def _metadata_from_profile(profile: BehaviourProfile) -> ProfileMetadata:
    return ProfileMetadata(
        id=profile.id,
        name=profile.name,
        label=profile.label,
        cluster_id=profile.cluster_id,
        namespace=profile.namespace,
        time_window_start=profile.time_window_start,
        time_window_end=profile.time_window_end,
        is_baseline=profile.is_baseline,
        created_at=profile.created_at,
    )
