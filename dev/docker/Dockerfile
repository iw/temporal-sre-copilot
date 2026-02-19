ARG TEMPORAL_BASE_IMAGE=temporal-dsql:latest
FROM ${TEMPORAL_BASE_IMAGE}

# --- DSQL connection defaults ---
ARG DSQL_ENDPOINT=aurora-dsql.cluster.local
ARG DSQL_PORT=5432
ARG DSQL_USERNAME=temporal_admin
ARG DSQL_DATABASE=temporal
ARG SQL_PLUGIN_NAME=dsql

ENV TEMPORAL_SQL_HOST=${DSQL_ENDPOINT}
ENV TEMPORAL_SQL_PORT=${DSQL_PORT}
ENV TEMPORAL_SQL_USER=${DSQL_USERNAME}
ENV TEMPORAL_SQL_DATABASE=${DSQL_DATABASE}
ENV TEMPORAL_SQL_PLUGIN_NAME=${SQL_PLUGIN_NAME}
ENV TEMPORAL_SQL_PASSWORD_FILE=/run/secrets/dsql-password
ENV TEMPORAL_SQL_MAX_CONNS=50
ENV TEMPORAL_SQL_MAX_IDLE_CONNS=50
ENV TEMPORAL_SQL_TLS_ENABLED=true
ENV TEMPORAL_SQL_CA_FILE=/etc/ssl/certs/ca-certificates.crt
ENV TEMPORAL_SQL_SERVER_NAME=
ENV TEMPORAL_HISTORY_SHARDS=512

# --- Persistence template paths ---
ENV TEMPORAL_PERSISTENCE_TEMPLATE=/etc/temporal/config/persistence-dsql-elasticsearch.template.yaml
ENV TEMPORAL_PERSISTENCE_CONFIG=/etc/temporal/config/persistence-dsql.yaml
ENV TEMPORAL_BASE_ENTRYPOINT=/etc/temporal/entrypoint.sh

# --- DSQL-specific settings ---
ENV TEMPORAL_DSQL_ENABLED=true
ENV TEMPORAL_SQL_REGION=eu-west-1
ENV TEMPORAL_DSQL_CLUSTER_ARN=
ENV TEMPORAL_SQL_IAM_AUTH=true
ENV TEMPORAL_SQL_AUTH_METHOD=iam
ENV TEMPORAL_SQL_TOKEN_REFRESH_INTERVAL=15m
ENV TEMPORAL_SQL_TLS_SKIP_VERIFY=false
ENV TEMPORAL_SQL_TLS_ENABLE_HOST_VERIFICATION=true

# --- ID generation ---
ENV TEMPORAL_SQL_NODE_ID=1
ENV TEMPORAL_SQL_ID_GENERATOR=snowflake
ENV TEMPORAL_SQL_SSL_MODE=require

# --- Elasticsearch visibility defaults ---
ENV TEMPORAL_ELASTICSEARCH_VERSION=v7
ENV TEMPORAL_ELASTICSEARCH_SCHEME=http
ENV TEMPORAL_ELASTICSEARCH_HOST=elasticsearch
ENV TEMPORAL_ELASTICSEARCH_PORT=9200
ENV TEMPORAL_ELASTICSEARCH_INDEX=temporal_visibility_v1

# --- Validate base image structure ---
RUN test -f /etc/temporal/entrypoint.sh || (echo "ERROR: Base image missing /etc/temporal/entrypoint.sh" && exit 1)
RUN test -d /etc/temporal/config || mkdir -p /etc/temporal/config
RUN python3 --version || (echo "ERROR: Base image missing python3" && exit 1)

# --- Copy persistence template and entrypoint ---
COPY persistence-dsql-elasticsearch.template.yaml /etc/temporal/config/persistence-dsql-elasticsearch.template.yaml
COPY render-and-start.sh /usr/local/bin/render-and-start.sh

ENTRYPOINT ["/usr/local/bin/render-and-start.sh"]
CMD []
