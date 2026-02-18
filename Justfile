set dotenv-load

ARGS_TEST := env("_UV_RUN_ARGS_TEST", "")

@_default:
    just --list

# Run tests
[group('qa')]
test *args:
    uv run {{ ARGS_TEST }} -m pytest {{ args }}

_cov *args:
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
config *args:
    uv run temporal-dsql-config {{ args }}

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
