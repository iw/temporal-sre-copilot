"""Temporal activities for the SRE Copilot.

Activities perform I/O operations:
- AMP: Fetch signals from Amazon Managed Prometheus
- Loki: Query logs for narrative patterns
- RAG: Retrieve context from Bedrock Knowledge Base
- State Store: Persist assessments to DSQL
"""

from .amp import fetch_signals_from_amp, fetch_worker_signals_from_amp
from .loki import fetch_recent_log_patterns, query_loki_errors
from .rag import fetch_rag_context
from .state_store import (
    check_recent_assessment,
    fetch_signal_history,
    get_assessments_in_range,
    get_latest_assessment,
    store_health_assessment,
    store_signals_snapshot,
)

__all__ = [
    # AMP
    "fetch_signals_from_amp",
    "fetch_worker_signals_from_amp",
    # Loki
    "query_loki_errors",
    "fetch_recent_log_patterns",
    # RAG
    "fetch_rag_context",
    # State Store
    "store_health_assessment",
    "store_signals_snapshot",
    "get_latest_assessment",
    "get_assessments_in_range",
    "check_recent_assessment",
    "fetch_signal_history",
]
