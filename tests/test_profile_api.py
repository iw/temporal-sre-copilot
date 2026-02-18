"""Unit tests for profile API edge cases.

Validates: Requirements 9.6, 12.1
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from behaviour_profiles.api import router


@pytest.fixture
def client():
    """Create a test client with the profile router mounted (no storage configured)."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestTimeRangeValidation:
    """Req 9.6: Time range must not exceed 24 hours."""

    def test_exceeds_24_hours_rejected(self, client: TestClient):
        response = client.post(
            "/profiles/",
            json={
                "name": "test",
                "cluster_id": "cluster-001",
                "time_window_start": "2026-01-15T00:00:00Z",
                "time_window_end": "2026-01-17T00:00:00Z",  # 48 hours
            },
        )
        assert response.status_code == 400
        assert "24 hours" in response.json()["detail"]

    def test_end_before_start_rejected(self, client: TestClient):
        response = client.post(
            "/profiles/",
            json={
                "name": "test",
                "cluster_id": "cluster-001",
                "time_window_start": "2026-01-15T12:00:00Z",
                "time_window_end": "2026-01-15T10:00:00Z",
            },
        )
        assert response.status_code == 400
        assert "after" in response.json()["detail"]


class TestComparisonValidation:
    """Req 12.1: Cannot compare a profile with itself."""

    def test_same_profile_id_rejected(self, client: TestClient):
        response = client.post(
            "/profiles/compare",
            json={
                "profile_a_id": "abc-123",
                "profile_b_id": "abc-123",
            },
        )
        assert response.status_code == 400
        assert "itself" in response.json()["detail"]

    def test_different_profile_ids_accepted_shape(self, client: TestClient):
        # This will fail with 503 (storage not configured) or 404, not 400
        response = client.post(
            "/profiles/compare",
            json={
                "profile_a_id": "abc-123",
                "profile_b_id": "def-456",
            },
        )
        # Should not be a 400 validation error
        assert response.status_code != 400
