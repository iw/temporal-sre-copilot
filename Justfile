set dotenv-load

export COPILOT_REPO_ROOT := justfile_directory()

ARGS_TEST := env("_UV_RUN_ARGS_TEST", "")

# Shorthand for running a workspace package's CLI entry point
@_pkg pkg *args:
    uv run --package {{ pkg }} {{ args }}

@_default:
    just --list

# Run tests
[group('qa')]
test *args:
    uv run {{ ARGS_TEST }} -m pytest {{ args }}

@_cov *args:
    uv run -m coverage {{ args }}

# Run tests and measure coverage
[group('qa')]
@cov:
    just _cov erase
    just _cov run -m pytest tests
    just _cov combine
    just _cov report
    just _cov html

# Run linters
[group('qa')]
lint:
    uvx ruff check packages tests
    uvx ruff format --check packages tests

# Format code
[group('qa')]
fmt:
    uvx ruff check --fix packages tests
    uvx ruff format packages tests

# Check types
[group('qa')]
typing:
    uvx ty check --python .venv packages

# Perform all checks
[group('qa')]
check-all: lint test typing

# Run the config compiler CLI
[group('tools')]
@config *args:
    just _pkg dsql-config temporal-dsql-config {{ args }}

# Run the copilot CLI
[group('tools')]
@copilot *args:
    just _pkg temporal-sre-copilot copilot {{ args }}

# Update dependencies
[group('lifecycle')]
update:
    uv sync --upgrade

# Ensure project virtualenv is up to date
[group('lifecycle')]
install:
    uv sync

# Remove temporary files
[group('lifecycle')]
clean:
    rm -rf .venv .pytest_cache .hypothesis .ruff_cache .coverage htmlcov
    find . -type d -name "__pycache__" -exec rm -r {} +

# Recreate project virtualenv from nothing
[group('lifecycle')]
fresh: clean install

# Start dev environment
[group('dev')]
@dev-up:
    just copilot dev up

# Stop dev environment
[group('dev')]
@dev-down:
    just copilot dev down

# Build dev images
[group('dev')]
@dev-build:
    just copilot dev build

# Show dev service status
[group('dev')]
@dev-ps:
    just copilot dev ps

# Tail dev logs
[group('dev')]
@dev-logs *args:
    just copilot dev logs {{ args }}
