"""Pytest configuration and fixtures for the SRE Copilot tests."""

import pytest


@pytest.fixture
def sample_metrics() -> dict:
    """Sample metrics for testing."""
    return {
        "reservoir_size": 50,
        "reservoir_target": 50,
        "reservoir_empty": 0,
        "checkout_p95_ms": 0.5,
        "service_error_rate": 0.0,
        "persistence_latency_p95": 50.0,
        "task_latency_p95": 100.0,
        "shard_churn": 0.0,
        "workflow_success_rate": 10.0,
        "workflow_failure_rate": 0.0,
        "occ_conflicts": 0.0,
        "schedule_to_start_p95": 20.0,
        "workflow_slots_available": 100,
        "activity_slots_available": 100,
    }
