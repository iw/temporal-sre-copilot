"""Shared Prometheus metrics setup for dev scenario scripts.

Configures the Temporal Python SDK to expose a Prometheus endpoint
so Alloy (running in Docker) can scrape SDK metrics like
state_transition_count, workflow completions, and activity latencies.

The endpoint binds to 0.0.0.0:9091 by default. Alloy reaches it
via host.docker.internal:9091 (Docker Desktop).
"""

from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig

DEFAULT_METRICS_PORT = 9091


def create_metrics_runtime(port: int = DEFAULT_METRICS_PORT) -> Runtime:
    """Create a Temporal Runtime with Prometheus metrics enabled.

    The SDK's Core emits metrics (workflow/activity counts, latencies,
    task queue depth, etc.) on the given port in Prometheus format.
    """
    return Runtime(
        telemetry=TelemetryConfig(metrics=PrometheusConfig(bind_address=f"0.0.0.0:{port}"))
    )
