-- Temporal SRE Copilot — DSQL State Store Schema
--
-- Aurora DSQL compatibility:
--   UUID primary keys with gen_random_uuid()
--   TEXT for structured data (JSON serialized in application layer)
--   No JSONB/JSON column types (DSQL runtime-only)
--   No foreign keys (application-layer referential integrity)
--   INDEX ASYNC only (one DDL per transaction)
--   No index sort order specifiers

CREATE TABLE IF NOT EXISTS health_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trigger VARCHAR(50) NOT NULL,
    overall_status VARCHAR(20) NOT NULL,
    services TEXT NOT NULL,
    issues TEXT NOT NULL,
    natural_language_summary TEXT NOT NULL,
    metrics_snapshot TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX ASYNC idx_assessments_timestamp ON health_assessments(timestamp);

CREATE INDEX ASYNC idx_assessments_status ON health_assessments(overall_status);

CREATE TABLE IF NOT EXISTS issues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id UUID NOT NULL,
    severity VARCHAR(20) NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT NOT NULL,
    likely_cause TEXT,
    suggested_actions TEXT,
    related_metrics TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX ASYNC idx_issues_assessment ON issues(assessment_id);

CREATE INDEX ASYNC idx_issues_severity ON issues(severity);

CREATE INDEX ASYNC idx_issues_created ON issues(created_at);

CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metrics TEXT NOT NULL
);

CREATE INDEX ASYNC idx_snapshots_timestamp ON metrics_snapshots(timestamp);

-- ---------------------------------------------------------------------------
-- Behaviour Profiles — metadata index (full JSON stored in S3)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS behaviour_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    label VARCHAR(255),
    cluster_id VARCHAR(255) NOT NULL,
    namespace VARCHAR(255),
    task_queue VARCHAR(255),
    time_window_start TIMESTAMPTZ NOT NULL,
    time_window_end TIMESTAMPTZ NOT NULL,
    s3_key VARCHAR(1024) NOT NULL,
    is_baseline BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ASYNC idx_profiles_cluster ON behaviour_profiles(cluster_id);

CREATE INDEX ASYNC idx_profiles_label ON behaviour_profiles(label);

CREATE INDEX ASYNC idx_profiles_created ON behaviour_profiles(created_at);

CREATE INDEX ASYNC idx_profiles_baseline ON behaviour_profiles(cluster_id, namespace, is_baseline);
