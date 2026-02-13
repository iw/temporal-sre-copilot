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

# Install dependencies first (layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable --no-install-project

# Copy source and install the project itself
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim AS runtime

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

# Default to worker, override in ECS task definition
CMD ["python", "-m", "copilot.worker"]
