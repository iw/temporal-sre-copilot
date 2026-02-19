"""Serialization round-trip tests for all Copilot Pydantic models.

Validates that every model survives the Temporal data converter round-trip:
    model → pydantic_core.to_json() → TypeAdapter.validate_json() → model

This is exactly what PydanticPayloadConverter does under the hood.
We also test that whenever.TimeDelta serializes correctly,
and that nested models don't need manual model_dump() calls.

All timestamp fields are ISO 8601 strings (no whenever.Instant in models).
"""

from pydantic import TypeAdapter
from pydantic_core import to_json
from whenever import Instant, TimeDelta

from copilot.models import (
    # Assessment
    ActionType,
    # Signals
    AmplifierSignals,
    # Workflow inputs
    AssessHealthInput,
    CacheAmplifiers,
    # Activity inputs
    CheckRecentAssessmentInput,
    ConnectionPoolAmplifiers,
    DeployAmplifiers,
    FetchLogPatternsInput,
    FetchRagContextInput,
    FetchSignalHistoryInput,
    FetchSignalsInput,
    FetchWorkerSignalsInput,
    FrontendSignals,
    GetAssessmentsInRangeInput,
    GetLatestAssessmentInput,
    GrpcAmplifiers,
    HealthAssessment,
    HealthState,
    HistorySignals,
    HostAmplifiers,
    Issue,
    # API responses
    IssueResponse,
    LogPattern,
    LogWatcherInput,
    MatchingSignals,
    ObserveClusterInput,
    PersistenceAmplifiers,
    PersistenceSignals,
    PollerSignals,
    PrimarySignals,
    QueryLokiInput,
    QueueAmplifiers,
    RuntimeAmplifiers,
    ScheduledAssessmentInput,
    Severity,
    ShardAmplifiers,
    Signals,
    StateTransitionSignals,
    StatusResponse,
    StoreAssessmentInput,
    StoreSignalsInput,
    SuggestedAction,
    SummaryResponse,
    ThrottlingAmplifiers,
    TimelineEntry,
    TimelineResponse,
    WorkerAmplifiers,
    WorkflowCompletionSignals,
)


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return Instant.now().format_iso()


# =============================================================================
# FIXTURES — reusable model instances
# =============================================================================


def _make_primary_signals() -> PrimarySignals:
    return PrimarySignals(
        state_transitions=StateTransitionSignals(
            throughput_per_sec=42.5, latency_p95_ms=15.0, latency_p99_ms=25.0
        ),
        workflow_completion=WorkflowCompletionSignals(
            completion_rate=0.98, success_per_sec=40.0, failed_per_sec=0.5
        ),
        history=HistorySignals(
            backlog_age_sec=2.3, task_processing_rate_per_sec=100.0, shard_churn_rate_per_sec=0.1
        ),
        frontend=FrontendSignals(
            error_rate_per_sec=0.01, latency_p95_ms=50.0, latency_p99_ms=120.0
        ),
        matching=MatchingSignals(workflow_backlog_age_sec=0.5, activity_backlog_age_sec=1.2),
        poller=PollerSignals(
            poll_success_rate=0.95, poll_timeout_rate=0.05, long_poll_latency_ms=200.0
        ),
        persistence=PersistenceSignals(
            latency_p95_ms=8.0, latency_p99_ms=15.0, error_rate_per_sec=0.0, retry_rate_per_sec=0.1
        ),
    )


def _make_amplifier_signals() -> AmplifierSignals:
    return AmplifierSignals(
        persistence=PersistenceAmplifiers(
            occ_conflicts_per_sec=1.2, cas_failures_per_sec=0.0, serialization_failures_per_sec=0.0
        ),
        connection_pool=ConnectionPoolAmplifiers(
            utilization_pct=60.0,
            wait_count=0,
            wait_duration_ms=0.0,
            churn_rate_per_sec=0.5,
            opens_per_sec=0.5,
            closes_per_sec=0.5,
        ),
        queue=QueueAmplifiers(task_backlog_depth=10, retry_time_spent_sec=0.5),
        worker=WorkerAmplifiers(poller_concurrency=8, task_slots_available=92, task_slots_used=8),
        cache=CacheAmplifiers(hit_rate=0.95, evictions_per_sec=2.0, size_bytes=1048576),
        shard=ShardAmplifiers(hot_shard_ratio=5.0, max_shard_load_pct=30.0),
        grpc=GrpcAmplifiers(in_flight_requests=15, server_queue_depth=0),
        runtime=RuntimeAmplifiers(goroutines=500, blocked_goroutines=2),
        host=HostAmplifiers(cpu_throttle_pct=0.0, memory_rss_bytes=536870912, gc_pause_ms=1.5),
        throttling=ThrottlingAmplifiers(
            rate_limit_events_per_sec=0.0, admission_rejects_per_sec=0.0
        ),
        deploy=DeployAmplifiers(
            task_restarts=0, membership_changes_per_min=0.0, leader_changes_per_min=0.0
        ),
    )


def _make_signals() -> Signals:
    return Signals(
        primary=_make_primary_signals(),
        amplifiers=_make_amplifier_signals(),
        timestamp=_now_iso(),
    )


def _make_issue() -> Issue:
    return Issue(
        severity=Severity.WARNING,
        title="Elevated OCC conflicts",
        description="OCC conflict rate is above normal threshold",
        likely_cause="High write contention on hot shards",
        suggested_actions=[
            SuggestedAction(
                action_type=ActionType.SCALE,
                target_service="history",
                description="Scale history service to reduce shard contention",
                confidence=0.8,
                risk_level="low",
            ),
        ],
        related_signals=["persistence.occ_conflicts_per_sec"],
    )


def _make_health_assessment() -> HealthAssessment:
    return HealthAssessment(
        timestamp=_now_iso(),
        trigger="state_change",
        health_state=HealthState.STRESSED,
        primary_signals=_make_primary_signals().model_dump(),
        amplifiers=_make_amplifier_signals().model_dump(),
        log_patterns=[
            LogPattern(service="history", pattern="SQLSTATE 40001", count=5),
        ],
        issues=[_make_issue()],
        recommended_actions=[
            SuggestedAction(
                action_type=ActionType.CONFIGURE,
                target_service="persistence",
                description="Increase retry backoff",
                confidence=0.7,
                risk_level="low",
            ),
        ],
        natural_language_summary="Cluster is stressed due to elevated OCC conflicts.",
    )


# =============================================================================
# HELPER — the actual round-trip that PydanticPayloadConverter performs
# =============================================================================


def _temporal_round_trip(model_instance, model_type=None):
    """Simulate the exact Temporal PydanticPayloadConverter round-trip.

    Serialization:  pydantic_core.to_json(value)
    Deserialization: TypeAdapter(type_hint).validate_json(data)

    This is what happens when a model crosses the workflow → activity boundary.
    """
    if model_type is None:
        model_type = type(model_instance)

    # Serialize (what PydanticJSONPlainPayloadConverter.to_payload does)
    json_bytes = to_json(model_instance)

    # Deserialize (what PydanticJSONPlainPayloadConverter.from_payload does)
    restored = TypeAdapter(model_type).validate_json(json_bytes)

    return restored, json_bytes


# =============================================================================
# 1. TIMESTAMP AND TIMEDELTA — ISO strings and TimeDelta round-trip
# =============================================================================


class TestTimestampSerialization:
    """Test that ISO 8601 timestamp strings and TimeDelta survive the Temporal data converter."""

    def test_iso_timestamp_in_model(self):
        """ISO 8601 timestamp string in a Pydantic model must round-trip."""
        signals = _make_signals()
        restored, _ = _temporal_round_trip(signals)
        assert restored.timestamp == signals.timestamp

    def test_timedelta_round_trip(self):
        """TimeDelta must serialize and deserialize correctly.

        Like Instant, bare TimeDelta needs TypeAdapter for schema context.
        """
        original = TimeDelta(hours=1, minutes=30)
        adapter = TypeAdapter(TimeDelta)
        json_bytes = adapter.dump_json(original)
        restored = adapter.validate_json(json_bytes)
        assert restored == original

    def test_timedelta_in_model(self):
        """TimeDelta field in CheckRecentAssessmentInput must round-trip."""
        original = CheckRecentAssessmentInput(
            window=TimeDelta(minutes=4),
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.window == original.window

    def test_timestamp_default_factory(self):
        """Default factory produces a valid ISO 8601 string that round-trips."""
        signals = Signals(
            primary=_make_primary_signals(),
            amplifiers=_make_amplifier_signals(),
            # timestamp defaults to _now_iso()
        )
        assert isinstance(signals.timestamp, str)
        assert "T" in signals.timestamp  # ISO 8601 contains 'T'
        restored, _ = _temporal_round_trip(signals)
        assert restored.timestamp == signals.timestamp

    def test_iso_string_accepted_for_timestamp(self):
        """Pydantic must accept ISO 8601 string for timestamp fields."""
        iso_str = "2026-02-13T10:30:00Z"
        assessment = HealthAssessment(
            timestamp=iso_str,
            trigger="test",
            health_state=HealthState.HAPPY,
            primary_signals={},
            amplifiers={},
            natural_language_summary="test",
        )
        assert assessment.timestamp == iso_str


# =============================================================================
# 2. SIGNAL MODELS — all 12 primary + 14 amplifiers
# =============================================================================


class TestSignalSerialization:
    """Test that signal models survive the Temporal round-trip."""

    def test_primary_signals_round_trip(self):
        original = _make_primary_signals()
        restored, _ = _temporal_round_trip(original)
        assert restored == original

    def test_amplifier_signals_round_trip(self):
        original = _make_amplifier_signals()
        restored, _ = _temporal_round_trip(original)
        assert restored == original

    def test_signals_round_trip(self):
        """Full Signals model with ISO timestamp."""
        original = _make_signals()
        restored, _ = _temporal_round_trip(original)
        assert restored.primary == original.primary
        assert restored.amplifiers == original.amplifiers
        assert restored.timestamp == original.timestamp

    def test_log_pattern_round_trip(self):
        original = LogPattern(service="history", pattern="SQLSTATE 40001", count=5)
        restored, _ = _temporal_round_trip(original)
        assert restored == original


# =============================================================================
# 3. ASSESSMENT MODELS
# =============================================================================


class TestAssessmentSerialization:
    """Test HealthAssessment and nested Issue/SuggestedAction models."""

    def test_health_assessment_round_trip(self):
        original = _make_health_assessment()
        restored, _ = _temporal_round_trip(original)
        assert restored.health_state == original.health_state
        assert restored.trigger == original.trigger
        assert restored.timestamp == original.timestamp
        assert restored.natural_language_summary == original.natural_language_summary
        assert len(restored.issues) == 1
        assert restored.issues[0].title == "Elevated OCC conflicts"
        assert len(restored.recommended_actions) == 1

    def test_issue_round_trip(self):
        original = _make_issue()
        restored, _ = _temporal_round_trip(original)
        assert restored.severity == Severity.WARNING
        assert restored.title == original.title
        assert len(restored.suggested_actions) == 1
        assert restored.suggested_actions[0].confidence == 0.8

    def test_suggested_action_round_trip(self):
        original = SuggestedAction(
            action_type=ActionType.RESTART,
            target_service="matching",
            description="Restart matching to clear stale state",
            confidence=0.6,
            parameters={"grace_period_sec": 30},
            risk_level="medium",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored == original
        assert restored.parameters == {"grace_period_sec": 30}

    def test_health_assessment_minimal(self):
        """Minimal assessment with empty lists."""
        original = HealthAssessment(
            trigger="scheduled",
            health_state=HealthState.HAPPY,
            primary_signals={},
            amplifiers={},
            natural_language_summary="All clear.",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.issues == []
        assert restored.recommended_actions == []
        assert restored.log_patterns == []


# =============================================================================
# 4. ACTIVITY INPUT MODELS
# =============================================================================


class TestActivityInputSerialization:
    """Test all activity input models survive the Temporal round-trip."""

    def test_fetch_signals_input(self):
        original = FetchSignalsInput(prometheus_endpoint="http://mimir:9009/prometheus")
        restored, _ = _temporal_round_trip(original)
        assert restored == original

    def test_fetch_worker_signals_input(self):
        original = FetchWorkerSignalsInput(prometheus_endpoint="http://mimir:9009/prometheus")
        restored, _ = _temporal_round_trip(original)
        assert restored == original

    def test_query_loki_input(self):
        original = QueryLokiInput(loki_url="http://loki:3100", lookback_seconds=120)
        restored, _ = _temporal_round_trip(original)
        assert restored == original

    def test_fetch_log_patterns_input(self):
        original = FetchLogPatternsInput(loki_url="http://loki:3100", lookback_seconds=60)
        restored, _ = _temporal_round_trip(original)
        assert restored == original

    def test_fetch_rag_context_input(self):
        original = FetchRagContextInput(
            knowledge_base_id="AEIQPURDHQ",
            contributing_factors=["occ_conflicts", "connection_pool"],
            region="eu-west-1",
            max_results=5,
        )
        restored, _ = _temporal_round_trip(original)
        assert restored == original

    def test_store_assessment_input_with_nested_model(self):
        """StoreAssessmentInput contains a nested HealthAssessment.

        CRITICAL: This tests that passing the HealthAssessment directly
        (not model_dump()) works through the Temporal data converter.
        PydanticPayloadConverter uses pydantic_core.to_json() which handles
        nested Pydantic models natively — no manual model_dump() needed.
        """
        assessment = _make_health_assessment()
        original = StoreAssessmentInput(
            assessment=assessment,
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.assessment.health_state == HealthState.STRESSED
        assert restored.assessment.timestamp == assessment.timestamp
        assert restored.assessment.natural_language_summary == assessment.natural_language_summary
        assert len(restored.assessment.issues) == 1

    def test_store_assessment_input_from_dict(self):
        """StoreAssessmentInput also accepts a dict (Pydantic coercion)."""
        assessment = _make_health_assessment()
        original = StoreAssessmentInput(
            assessment=assessment.model_dump(mode="json"),
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.assessment.health_state == HealthState.STRESSED

    def test_store_signals_input_with_nested_model(self):
        """StoreSignalsInput contains a nested Signals model."""
        signals = _make_signals()
        original = StoreSignalsInput(
            signals=signals,
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.signals.primary == signals.primary
        assert restored.signals.timestamp == signals.timestamp

    def test_store_signals_input_from_dict(self):
        """StoreSignalsInput also accepts a dict (current workflow pattern)."""
        signals = _make_signals()
        original = StoreSignalsInput(
            signals=signals.model_dump(mode="json"),
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.signals.primary == signals.primary

    def test_get_latest_assessment_input(self):
        original = GetLatestAssessmentInput(dsql_endpoint="test.dsql.eu-west-1.on.aws")
        restored, _ = _temporal_round_trip(original)
        assert restored == original

    def test_get_assessments_in_range_input(self):
        """Contains two ISO 8601 string fields."""
        now = Instant.now()
        original = GetAssessmentsInRangeInput(
            start=(now - TimeDelta(hours=1)).format_iso(),
            end=now.format_iso(),
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.start == original.start
        assert restored.end == original.end

    def test_check_recent_assessment_input(self):
        """Contains a TimeDelta field."""
        original = CheckRecentAssessmentInput(
            window=TimeDelta(minutes=4),
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.window == original.window

    def test_fetch_signal_history_input(self):
        original = FetchSignalHistoryInput(
            lookback_minutes=10,
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored == original


# =============================================================================
# 5. WORKFLOW INPUT MODELS
# =============================================================================


class TestWorkflowInputSerialization:
    """Test all workflow input models survive the Temporal round-trip."""

    def test_observe_cluster_input(self):
        original = ObserveClusterInput(
            prometheus_endpoint="http://mimir:9009/prometheus",
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored == original

    def test_log_watcher_input(self):
        original = LogWatcherInput(loki_url="http://loki:3100")
        restored, _ = _temporal_round_trip(original)
        assert restored == original

    def test_assess_health_input_with_nested_signals(self):
        """AssessHealthInput contains a nested Signals model.

        CRITICAL: This tests that passing Signals directly works.
        The workflow should NOT need signals.model_dump(mode="json").
        """
        signals = _make_signals()
        original = AssessHealthInput(
            health_state=HealthState.STRESSED,
            signals=signals,
            trigger="state_change",
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
            kb_id="AEIQPURDHQ",
            loki_url="http://loki:3100",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.health_state == HealthState.STRESSED
        assert restored.signals.primary == signals.primary
        assert restored.signals.timestamp == signals.timestamp
        assert restored.trigger == "state_change"
        assert restored.kb_id == "AEIQPURDHQ"

    def test_assess_health_input_from_dict(self):
        """AssessHealthInput also accepts a dict for signals (current pattern)."""
        signals = _make_signals()
        original = AssessHealthInput(
            health_state=HealthState.STRESSED,
            signals=signals.model_dump(mode="json"),
            trigger="state_change",
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.signals.primary == signals.primary

    def test_assess_health_input_optional_fields(self):
        """Optional fields default to None."""
        signals = _make_signals()
        original = AssessHealthInput(
            health_state=HealthState.HAPPY,
            signals=signals,
            trigger="scheduled",
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.kb_id is None
        assert restored.loki_url is None

    def test_scheduled_assessment_input(self):
        original = ScheduledAssessmentInput(
            prometheus_endpoint="http://mimir:9009/prometheus",
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
            kb_id="AEIQPURDHQ",
            loki_url="http://loki:3100",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored == original


# =============================================================================
# 6. API RESPONSE MODELS
# =============================================================================


class TestApiResponseSerialization:
    """Test API response models serialize correctly for Grafana."""

    def test_status_response(self):
        original = StatusResponse(
            health_state=HealthState.STRESSED,
            timestamp=_now_iso(),
            primary_signals={"history": {"backlog_age_sec": 45.0}},
            amplifiers={"persistence": {"occ_conflicts_per_sec": 3.0}},
            issue_count=2,
        )
        restored, json_bytes = _temporal_round_trip(original)
        assert restored.health_state == HealthState.STRESSED
        assert restored.timestamp == original.timestamp
        # Verify JSON contains ISO 8601 timestamp string
        assert b"T" in json_bytes  # ISO 8601 contains 'T'

    def test_summary_response(self):
        original = SummaryResponse(
            summary="Cluster is stressed due to OCC conflicts.",
            timestamp=_now_iso(),
            health_state=HealthState.STRESSED,
        )
        restored, _ = _temporal_round_trip(original)
        assert restored == original

    def test_timeline_entry(self):
        original = TimelineEntry(
            id="abc-123",
            timestamp=_now_iso(),
            trigger="state_change",
            health_state=HealthState.CRITICAL,
            primary_signals={"history": {"backlog_age_sec": 120.0}},
            issue_count=3,
        )
        restored, _ = _temporal_round_trip(original)
        assert restored == original

    def test_timeline_response(self):
        now = Instant.now()
        original = TimelineResponse(
            timeline=[
                TimelineEntry(
                    id="1",
                    timestamp=(now - TimeDelta(minutes=10)).format_iso(),
                    trigger="state_change",
                    health_state=HealthState.STRESSED,
                    issue_count=1,
                ),
                TimelineEntry(
                    id="2",
                    timestamp=now.format_iso(),
                    trigger="scheduled",
                    health_state=HealthState.HAPPY,
                    issue_count=0,
                ),
            ]
        )
        restored, _ = _temporal_round_trip(original)
        assert len(restored.timeline) == 2
        assert restored.timeline[0].health_state == HealthState.STRESSED
        assert restored.timeline[1].health_state == HealthState.HAPPY

    def test_issue_response(self):
        original = IssueResponse(
            id="issue-1",
            severity="critical",
            title="Forward progress stalled",
            description="No state transitions in 60 seconds",
            likely_cause="DSQL persistence failure",
            suggested_actions=[
                SuggestedAction(
                    action_type=ActionType.RESTART,
                    target_service="history",
                    description="Restart history service",
                    confidence=0.9,
                    risk_level="medium",
                ),
            ],
            related_signals=["persistence.error_rate_per_sec"],
            created_at=_now_iso(),
            resolved_at=None,
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.id == "issue-1"
        assert restored.resolved_at is None
        assert len(restored.suggested_actions) == 1


# =============================================================================
# 7. MODEL_DUMP REDUNDANCY — prove it's unnecessary
# =============================================================================


class TestModelDumpRedundancy:
    """Prove that manual model_dump(mode="json") is unnecessary.

    The PydanticPayloadConverter uses pydantic_core.to_json() for serialization
    and TypeAdapter.validate_json() for deserialization. Both handle nested
    Pydantic models natively. Calling model_dump() before passing to an
    activity input is redundant and loses type information.

    These tests show that passing the model directly produces identical
    JSON to passing model_dump(mode="json"), and both round-trip correctly.
    """

    def test_store_assessment_direct_vs_model_dump(self):
        """Passing HealthAssessment directly vs model_dump produces same result."""
        assessment = _make_health_assessment()

        # Direct: pass model instance (correct way)
        direct = StoreAssessmentInput(
            assessment=assessment,
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )

        # model_dump: pass dict (current workflow pattern — unnecessary)
        via_dump = StoreAssessmentInput(
            assessment=assessment.model_dump(mode="json"),
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )

        # Both should produce identical JSON through the converter
        direct_json = to_json(direct)
        dump_json = to_json(via_dump)
        assert direct_json == dump_json

        # Both should deserialize identically
        direct_restored = TypeAdapter(StoreAssessmentInput).validate_json(direct_json)
        dump_restored = TypeAdapter(StoreAssessmentInput).validate_json(dump_json)
        assert direct_restored.assessment.health_state == dump_restored.assessment.health_state
        assert direct_restored.assessment.timestamp == dump_restored.assessment.timestamp

    def test_store_signals_direct_vs_model_dump(self):
        """Passing Signals directly vs model_dump produces same result."""
        signals = _make_signals()

        direct = StoreSignalsInput(signals=signals, dsql_endpoint="test.dsql.eu-west-1.on.aws")
        via_dump = StoreSignalsInput(
            signals=signals.model_dump(mode="json"),
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )

        direct_json = to_json(direct)
        dump_json = to_json(via_dump)
        assert direct_json == dump_json

    def test_assess_health_input_direct_vs_model_dump(self):
        """Passing Signals directly to AssessHealthInput vs model_dump."""
        signals = _make_signals()

        direct = AssessHealthInput(
            health_state=HealthState.STRESSED,
            signals=signals,
            trigger="state_change",
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )
        via_dump = AssessHealthInput(
            health_state=HealthState.STRESSED,
            signals=signals.model_dump(mode="json"),
            trigger="state_change",
            dsql_endpoint="test.dsql.eu-west-1.on.aws",
        )

        direct_json = to_json(direct)
        dump_json = to_json(via_dump)
        assert direct_json == dump_json


# =============================================================================
# 8. EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Edge cases for serialization correctness."""

    def test_health_state_enum_serializes_as_string(self):
        """HealthState enum must serialize as its string value, not the enum object."""
        assessment = HealthAssessment(
            trigger="test",
            health_state=HealthState.CRITICAL,
            primary_signals={},
            amplifiers={},
            natural_language_summary="test",
        )
        json_bytes = to_json(assessment)
        assert b'"critical"' in json_bytes

    def test_severity_enum_serializes_as_string(self):
        """Severity enum must serialize as its string value."""
        issue = _make_issue()
        json_bytes = to_json(issue)
        assert b'"warning"' in json_bytes

    def test_action_type_enum_serializes_as_string(self):
        """ActionType enum must serialize as its string value."""
        action = SuggestedAction(
            action_type=ActionType.SCALE,
            target_service="history",
            description="Scale up",
            confidence=0.9,
        )
        json_bytes = to_json(action)
        assert b'"scale"' in json_bytes

    def test_empty_signals_dict_in_assessment(self):
        """Assessment with empty primary_signals/amplifiers dicts."""
        original = HealthAssessment(
            trigger="scheduled",
            health_state=HealthState.HAPPY,
            primary_signals={},
            amplifiers={},
            natural_language_summary="All clear.",
        )
        restored, _ = _temporal_round_trip(original)
        assert restored.primary_signals == {}
        assert restored.amplifiers == {}

    def test_none_optional_fields(self):
        """Optional fields serialize as null and deserialize as None."""
        original = SuggestedAction(
            action_type=ActionType.ALERT,
            target_service="frontend",
            description="Alert on-call",
            confidence=0.5,
            parameters=None,
        )
        restored, json_bytes = _temporal_round_trip(original)
        assert restored.parameters is None
        assert b"null" in json_bytes

    def test_large_issue_list(self):
        """Assessment with many issues round-trips correctly."""
        issues = [
            Issue(
                severity=Severity.CRITICAL if i % 2 == 0 else Severity.WARNING,
                title=f"Issue {i}",
                description=f"Description for issue {i}",
                likely_cause=f"Cause {i}",
                suggested_actions=[],
                related_signals=[f"signal_{i}"],
            )
            for i in range(20)
        ]
        original = HealthAssessment(
            trigger="state_change",
            health_state=HealthState.CRITICAL,
            primary_signals={},
            amplifiers={},
            issues=issues,
            natural_language_summary="Multiple issues detected.",
        )
        restored, _ = _temporal_round_trip(original)
        assert len(restored.issues) == 20
        assert restored.issues[0].severity == Severity.CRITICAL
        assert restored.issues[1].severity == Severity.WARNING
