#!/bin/bash
set -euo pipefail

# render-and-start.sh — Renders persistence YAML template by substituting
# environment variables, validates the result, then delegates to the base
# Temporal entrypoint.

TEMPLATE="${TEMPORAL_PERSISTENCE_TEMPLATE:-/etc/temporal/config/persistence-dsql-elasticsearch.template.yaml}"
OUTPUT="${TEMPORAL_PERSISTENCE_CONFIG:-/etc/temporal/config/persistence-dsql.yaml}"
BASE_ENTRYPOINT="${TEMPORAL_BASE_ENTRYPOINT:-/etc/temporal/entrypoint.sh}"

# --- Validate required environment variables ---
REQUIRED_VARS=(
    TEMPORAL_SQL_HOST
    TEMPORAL_SQL_PORT
    TEMPORAL_SQL_USER
    TEMPORAL_SQL_DATABASE
    TEMPORAL_SQL_PLUGIN_NAME
    TEMPORAL_SQL_MAX_CONNS
    TEMPORAL_SQL_MAX_IDLE_CONNS
    TEMPORAL_SQL_TLS_ENABLED
    TEMPORAL_HISTORY_SHARDS
    TEMPORAL_ELASTICSEARCH_VERSION
    TEMPORAL_ELASTICSEARCH_SCHEME
    TEMPORAL_ELASTICSEARCH_HOST
    TEMPORAL_ELASTICSEARCH_PORT
    TEMPORAL_ELASTICSEARCH_INDEX
)

missing=()
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var:-}" ]; then
        missing+=("$var")
    fi
done

if [ ${#missing[@]} -gt 0 ]; then
    echo "ERROR: Missing required environment variables:"
    for var in "${missing[@]}"; do
        echo "  - $var"
    done
    exit 1
fi

# --- Validate template file exists ---
if [ ! -f "$TEMPLATE" ]; then
    echo "ERROR: Persistence template not found: $TEMPLATE"
    exit 1
fi

# --- Render template using Python's string.Template ---
# This substitutes $VAR and ${VAR} patterns with environment variable values.
python3 -c "
import os, sys
from string import Template

with open('$TEMPLATE', 'r') as f:
    tmpl = Template(f.read())

# Substitute with environment variables, leaving unknown vars as-is initially
# so we can detect them in the validation step
result = tmpl.safe_substitute(os.environ)

with open('$OUTPUT', 'w') as f:
    f.write(result)
"

# --- Check for unsubstituted variables ---
# Look for $VAR or ${VAR} patterns that were not replaced
unsubstituted=$(grep -oE '\$\{?[A-Z_][A-Z0-9_]*\}?' "$OUTPUT" 2>/dev/null || true)
if [ -n "$unsubstituted" ]; then
    echo "ERROR: Unsubstituted variables found in rendered config:"
    echo "$unsubstituted" | sort -u | while read -r var; do
        echo "  - $var"
    done
    exit 1
fi

echo "Persistence config rendered: $OUTPUT"

# --- Validate base entrypoint exists ---
if [ ! -f "$BASE_ENTRYPOINT" ]; then
    echo "ERROR: Base entrypoint not found: $BASE_ENTRYPOINT"
    exit 1
fi

# --- Delegate to base Temporal entrypoint ---
exec "$BASE_ENTRYPOINT" "$@"
