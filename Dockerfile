# syntax=docker/dockerfile:1
# Multi-stage build for the Temporal SRE Copilot.
#
# Entry points:
#   Worker: python -m copilot.worker
#   API:    uvicorn copilot.api:app --host 0.0.0.0 --port 8080
#   Start:  python -m copilot.starter

FROM python:3.14-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy workspace root and all package pyproject.toml files first (layer caching)
COPY pyproject.toml uv.lock ./
COPY packages/copilot_core/pyproject.toml packages/copilot_core/pyproject.toml
COPY packages/dsql_config/pyproject.toml packages/dsql_config/pyproject.toml
COPY packages/behaviour_profiles/pyproject.toml packages/behaviour_profiles/pyproject.toml
COPY packages/copilot/pyproject.toml packages/copilot/pyproject.toml

# Install dependencies (needs package stubs for workspace resolution)
RUN mkdir -p packages/copilot_core/src/copilot_core \
    && touch packages/copilot_core/src/copilot_core/__init__.py \
    && mkdir -p packages/dsql_config/src/dsql_config \
    && touch packages/dsql_config/src/dsql_config/__init__.py \
    && mkdir -p packages/behaviour_profiles/src/behaviour_profiles \
    && touch packages/behaviour_profiles/src/behaviour_profiles/__init__.py \
    && mkdir -p packages/copilot/src/copilot \
    && touch packages/copilot/src/copilot/__init__.py
RUN uv sync --frozen --no-dev --no-editable --no-install-workspace

# Copy all package source and install workspace packages
COPY packages/ packages/
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim AS runtime

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Default to worker, override in ECS task definition
CMD ["python", "-m", "copilot.worker"]
