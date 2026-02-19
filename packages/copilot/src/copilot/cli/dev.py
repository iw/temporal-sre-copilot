"""Dev environment CLI commands for the Temporal SRE Copilot.

Orchestrates the local Docker Compose stack, image builds, schema setup,
and ephemeral Terraform infrastructure. Image builds use Dagger for
reproducible, containerised compilation (no local Dockerfile needed for
temporal-dsql). Service lifecycle and schema commands shell out via subprocess.

All repo-level paths are resolved via explicit configuration:

- ``COPILOT_REPO_ROOT`` (or ``--repo-root``) — workspace root.
  Defaults to the current working directory, which is correct when invoked
  via the Justfile (``just copilot dev …``).
- ``TEMPORAL_DSQL_PATH`` (or positional arg on ``build``) — path to the
  temporal-dsql Go repository.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(no_args_is_help=True)
build_app = typer.Typer(no_args_is_help=True)
schema_app = typer.Typer(no_args_is_help=True)
infra_app = typer.Typer(no_args_is_help=True)

app.add_typer(build_app, name="build", help="Build Docker images")
app.add_typer(schema_app, name="schema", help="Schema management")
app.add_typer(infra_app, name="infra", help="Ephemeral AWS infrastructure")

console = Console()


# ---------------------------------------------------------------------------
# Path resolution — explicit config, no filesystem walking
# ---------------------------------------------------------------------------

_REPO_ROOT_ENV = "COPILOT_REPO_ROOT"
_DSQL_PATH_ENV = "TEMPORAL_DSQL_PATH"


def _repo_root() -> Path:
    """Return the workspace root from env or cwd.

    Resolution order:
    1. ``COPILOT_REPO_ROOT`` env var (explicit, always wins)
    2. Current working directory (correct when run via Justfile)
    """
    return Path(os.environ.get(_REPO_ROOT_ENV, ".")).resolve()


def _dev_dir() -> Path:
    return _repo_root() / "dev"


def _compose_file() -> Path:
    return _dev_dir() / "docker-compose.yml"


def _compose_cmd(*args: str) -> list[str]:
    return ["docker", "compose", "-f", str(_compose_file()), *args]


def _terraform_dir() -> Path:
    return _repo_root() / "terraform" / "dev"


def _temporal_dsql_path(override: str = "") -> Path:
    """Resolve the temporal-dsql repo path.

    Resolution order:
    1. Explicit ``override`` (CLI argument)
    2. ``TEMPORAL_DSQL_PATH`` env var
    3. ``../temporal-dsql`` relative to repo root
    """
    if override:
        return Path(override).resolve()
    env = os.environ.get(_DSQL_PATH_ENV)
    if env:
        return Path(env).resolve()
    return (_repo_root().parent / "temporal-dsql").resolve()


def _run(cmd: list[str], *, check: bool = True) -> None:
    """Run a subprocess with inherited I/O, translating errors to Rich output."""
    try:
        subprocess.run(cmd, check=check)  # noqa: S603
    except FileNotFoundError:
        console.print(f"[red]Error:[/red] [bold]{cmd[0]}[/bold] not found. Is it installed?")
        raise typer.Exit(1) from None
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Error:[/red] Command failed with exit code {exc.returncode}")
        raise typer.Exit(exc.returncode) from None


# ---------------------------------------------------------------------------
# Service lifecycle
# ---------------------------------------------------------------------------


@app.command()
def up(
    detach: Annotated[bool, typer.Option("--detach", "-d", help="Run in detached mode")] = True,
) -> None:
    """Start all Docker Compose services."""
    console.print(Panel.fit("Starting Dev Environment", style="bold blue"))
    cmd = _compose_cmd("up")
    if detach:
        cmd.append("-d")
    _run(cmd)
    console.print("[green]✓[/green] Dev environment started")


@app.command()
def down(
    volumes: Annotated[bool, typer.Option("--volumes", "-v", help="Remove volumes")] = False,
) -> None:
    """Stop all Docker Compose services."""
    console.print(Panel.fit("Stopping Dev Environment", style="bold blue"))
    cmd = _compose_cmd("down")
    if volumes:
        cmd.append("-v")
    _run(cmd)
    console.print("[green]✓[/green] Dev environment stopped")


@app.command()
def ps() -> None:
    """Show status of all Docker Compose services."""
    _run(_compose_cmd("ps"))


@app.command()
def logs(
    service: Annotated[str, typer.Argument(help="Service name (all if omitted)")] = "",
) -> None:
    """Tail logs from Docker Compose services."""
    cmd = _compose_cmd("logs", "-f")
    if service:
        cmd.append(service)
    _run(cmd)


# ---------------------------------------------------------------------------
# Build — Dagger-based image construction
# ---------------------------------------------------------------------------


def _go_version_from_mod(go_mod: Path) -> str:
    """Extract the Go version from a go.mod file (e.g. '1.26' from 'go 1.26.0')."""
    for line in go_mod.read_text().splitlines():
        if line.startswith("go "):
            # "go 1.26.0" → "1.26"  (Docker tags use major.minor)
            parts = line.split()[1].split(".")
            return ".".join(parts[:2])
    msg = f"Could not find 'go' directive in {go_mod}"
    raise RuntimeError(msg)


async def _build_temporal_async(
    source_path: Path, dev_dir: Path, arch: str, no_cache: bool = False
) -> None:
    """Build temporal-dsql base image and runtime image using Dagger.

    Stage 1: Compile Go binaries (temporal-server, temporal-dsql-tool) in a
             golang container matching the go.mod version.
    Stage 2: Assemble temporal-dsql:latest from alpine:3.22 with the binaries.
    Stage 3: Layer persistence templates and entrypoint to create
             temporal-dsql-runtime:test.
    """
    import dagger
    from dagger import dag

    # Read Go version from go.mod so we never drift
    go_version = _go_version_from_mod(source_path / "go.mod")
    go_image = f"golang:{go_version}-alpine"

    config = dagger.Config(log_output=sys.stderr)

    async with dagger.connection(config):
        # --- Stage 1: Build Go binaries ---
        console.print(f"[bold]Stage 1/3:[/bold] Compiling Go binaries ({go_image}) …")

        source_dir = dag.host().directory(
            str(source_path),
            exclude=[".git", ".venv", "**/__pycache__"],
        )

        platform = dagger.Platform(f"linux/{arch}")
        go_builder = (
            dag.container(platform=platform)
            .from_(go_image)
            .with_exec(["apk", "add", "--no-cache", "make", "git", "gcc", "musl-dev"])
            .with_directory("/src", source_dir)
            .with_workdir("/src")
            .with_env_variable("CGO_ENABLED", "0")
            .with_env_variable("GOOS", "linux")
            .with_env_variable("GOARCH", arch)
            # Cache-bust so we always pick up source changes
            .with_env_variable("CACHEBUSTER", str(datetime.now()))
        )

        go_builder = go_builder.with_exec(
            [
                "go",
                "build",
                "-tags",
                "disable_grpc_modules",
                "-o",
                "temporal-server",
                "./cmd/server",
            ]
        )
        go_builder = go_builder.with_exec(
            [
                "go",
                "build",
                "-tags",
                "disable_grpc_modules",
                "-o",
                "temporal-dsql-tool",
                "./cmd/tools/dsql",
            ]
        )

        temporal_server = go_builder.file("/src/temporal-server")
        dsql_tool = go_builder.file("/src/temporal-dsql-tool")

        # --- Stage 2: Assemble temporal-dsql:latest ---
        console.print("[bold]Stage 2/3:[/bold] Building temporal-dsql:latest …")

        base = (
            dag.container(platform=platform)
            .from_("alpine:3.22")
            .with_exec(
                [
                    "sh",
                    "-c",
                    "apk add --no-cache ca-certificates tzdata curl python3 bash aws-cli"
                    " && addgroup -g 1000 temporal"
                    " && adduser -u 1000 -G temporal -D temporal",
                ]
            )
            .with_workdir("/etc/temporal")
            .with_env_variable("TEMPORAL_HOME", "/etc/temporal")
            .with_exec(["mkdir", "-p", "/etc/temporal/config/dynamicconfig"])
            .with_exec(["chown", "-R", "temporal:temporal", "/etc/temporal"])
            .with_file("/usr/local/bin/temporal-server", temporal_server, permissions=0o755)
            .with_file("/usr/local/bin/temporal-dsql-tool", dsql_tool, permissions=0o755)
            .with_new_file(
                "/etc/temporal/entrypoint.sh",
                '#!/bin/sh\nset -eu\nexec /usr/local/bin/temporal-server "$@"\n',
                permissions=0o755,
            )
            .with_user("temporal")
            .with_entrypoint(["/etc/temporal/entrypoint.sh"])
            .with_default_args(
                [
                    "--config-file",
                    "/etc/temporal/config/development-dsql.yaml",
                    "--allow-no-auth",
                    "start",
                ]
            )
        )

        await base.export_image.__wrapped__(base, "temporal-dsql:latest")

        # --- Stage 3: Layer runtime config → temporal-dsql-runtime:test ---
        console.print("[bold]Stage 3/3:[/bold] Building temporal-dsql-runtime:test …")

        docker_dir = dag.host().directory(
            str(dev_dir / "docker"),
            include=[
                "persistence-dsql-elasticsearch.template.yaml",
                "render-and-start.sh",
            ],
        )

        runtime = (
            base.with_user("root")
            .with_file(
                "/etc/temporal/config/persistence-dsql-elasticsearch.template.yaml",
                docker_dir.file("persistence-dsql-elasticsearch.template.yaml"),
            )
            .with_file(
                "/usr/local/bin/render-and-start.sh",
                docker_dir.file("render-and-start.sh"),
                permissions=0o755,
            )
            .with_user("temporal")
            .with_entrypoint(["/usr/local/bin/render-and-start.sh"])
            .with_default_args([])
        )

        await runtime.export_image.__wrapped__(runtime, "temporal-dsql-runtime:test")

    console.print()
    console.print("[green]✓[/green] Temporal images built:")
    console.print(f"  temporal-dsql:latest         (linux/{arch})")
    console.print(f"  temporal-dsql-runtime:test    (linux/{arch})")


async def _build_copilot_async(repo_root: Path, *, no_cache: bool = False) -> None:
    """Build the Copilot Docker image from the repo-root Dockerfile."""
    import dagger
    from dagger import dag

    config = dagger.Config(log_output=sys.stderr)

    async with dagger.connection(config):
        source_dir = dag.host().directory(
            str(repo_root),
            exclude=[".git", ".venv", "**/__pycache__", ".mypy_cache", ".hypothesis"],
        )
        builder = source_dir.docker_build()
        if no_cache:
            # Force a fresh build by injecting a unique build arg
            builder = source_dir.docker_build(
                build_args=[dagger.BuildArg(name="CACHEBUSTER", value=str(datetime.now()))]
            )
        await builder.export_image.__wrapped__(builder, "temporal-sre-copilot:dev")

    console.print()
    console.print("[green]✓[/green] Image built: temporal-sre-copilot:dev")


def _build_copilot_docker(repo_root: Path, *, no_cache: bool = False) -> None:
    """Build the Copilot Docker image using plain docker build (no Dagger)."""
    cmd = ["docker", "build", "-t", "temporal-sre-copilot:dev"]
    if no_cache:
        cmd.append("--no-cache")
    cmd.append(str(repo_root))
    _run(cmd)
    console.print("[green]✓[/green] Image built: temporal-sre-copilot:dev")


@build_app.command()
def temporal(
    temporal_dsql: Annotated[
        str,
        typer.Argument(help="Path to temporal-dsql repo (default: TEMPORAL_DSQL_PATH)"),
    ] = "",
    arch: Annotated[str, typer.Option("--arch", "-a", help="Target architecture")] = "arm64",
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Force rebuild without cache")
    ] = False,
) -> None:
    """Build temporal-dsql and temporal-dsql-runtime images via Dagger."""
    import anyio

    console.print(Panel.fit("Building Temporal Images", style="bold blue"))

    dsql_path = _temporal_dsql_path(temporal_dsql)
    if not dsql_path.is_dir():
        console.print(
            f"[red]Error:[/red] temporal-dsql repository not found at"
            f" [bold]{dsql_path}[/bold]\n"
            f"  Set [cyan]{_DSQL_PATH_ENV}[/cyan] to the correct location."
        )
        raise typer.Exit(1)

    console.print(f"  temporal-dsql: [cyan]{dsql_path}[/cyan]")
    console.print(f"  arch:          [cyan]{arch}[/cyan]")
    if no_cache:
        console.print("  cache:         [yellow]disabled[/yellow]")
    console.print()

    anyio.run(_build_temporal_async, dsql_path, _dev_dir(), arch, no_cache)


@build_app.command()
def copilot(
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Force rebuild without cache")
    ] = False,
) -> None:
    """Build the temporal-sre-copilot:dev image from the repo Dockerfile."""
    console.print(Panel.fit("Building Copilot Image", style="bold blue"))
    if no_cache:
        console.print("  cache: [yellow]disabled[/yellow]")
    _build_copilot_docker(_repo_root(), no_cache=no_cache)


@build_app.command()
def all(
    temporal_dsql: Annotated[
        str,
        typer.Argument(help="Path to temporal-dsql repo (default: TEMPORAL_DSQL_PATH)"),
    ] = "",
    arch: Annotated[str, typer.Option("--arch", "-a", help="Target architecture")] = "arm64",
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Force rebuild without cache")
    ] = False,
) -> None:
    """Build all Docker images (temporal-dsql + copilot)."""
    import anyio

    console.print(Panel.fit("Building All Docker Images", style="bold blue"))

    dsql_path = _temporal_dsql_path(temporal_dsql)
    if not dsql_path.is_dir():
        console.print(
            f"[red]Error:[/red] temporal-dsql repository not found at"
            f" [bold]{dsql_path}[/bold]\n"
            f"  Set [cyan]{_DSQL_PATH_ENV}[/cyan] to the correct location."
        )
        raise typer.Exit(1)

    console.print(f"  temporal-dsql: [cyan]{dsql_path}[/cyan]")
    console.print(f"  arch:          [cyan]{arch}[/cyan]")
    if no_cache:
        console.print("  cache:         [yellow]disabled[/yellow]")
    console.print()

    # 1. Temporal base + runtime images (Dagger)
    console.print("[bold]Building Temporal images …[/bold]")
    anyio.run(_build_temporal_async, dsql_path, _dev_dir(), arch, no_cache)

    # 2. Copilot image (docker build)
    console.print("[bold]Building Copilot image …[/bold]")
    _build_copilot_docker(_repo_root(), no_cache=no_cache)

    console.print()
    console.print("[green]✓[/green] All images built")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@schema_app.command()
def setup(
    only: Annotated[
        str | None,
        typer.Option(
            help="Run a single schema step: temporal-monitored, temporal-copilot, "
            "copilot-app, es-monitored, es-copilot",
        ),
    ] = None,
) -> None:
    """Apply schemas to DSQL clusters and Elasticsearch.

    By default runs all steps. Use --only to run a single step.
    """
    console.print(Panel.fit("Setting Up Schemas", style="bold blue"))

    steps: dict[str, tuple[str, list[str]]] = {
        "temporal-monitored": (
            "Temporal schema → monitored DSQL cluster",
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{Path.home() / '.aws'}:/root/.aws:ro",
                "-e",
                "AWS_REGION",
                "-e",
                "TEMPORAL_SQL_HOST",
                "temporal-dsql-runtime:test",
                "temporal-dsql-tool",
                "setup-schema",
            ],
        ),
        "temporal-copilot": (
            "Temporal schema → copilot DSQL cluster",
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{Path.home() / '.aws'}:/root/.aws:ro",
                "-e",
                "AWS_REGION",
                "-e",
                "COPILOT_DSQL_HOST",
                "temporal-dsql-runtime:test",
                "temporal-dsql-tool",
                "setup-schema",
                "--endpoint",
                "${COPILOT_DSQL_HOST}",
            ],
        ),
        "copilot-app": (
            "Copilot app schema → copilot DSQL cluster",
            _compose_cmd("exec", "copilot-api", "copilot", "db", "setup-schema"),
        ),
        "es-monitored": (
            "Elasticsearch indices → monitored cluster",
            _compose_cmd(
                "exec",
                "elasticsearch",
                "curl",
                "-s",
                "-X",
                "PUT",
                "http://localhost:9200/temporal_visibility_v1",
            ),
        ),
        "es-copilot": (
            "Elasticsearch indices → copilot cluster",
            _compose_cmd(
                "exec",
                "elasticsearch",
                "curl",
                "-s",
                "-X",
                "PUT",
                "http://localhost:9200/copilot_temporal_visibility_v1",
            ),
        ),
    }

    if only:
        if only not in steps:
            valid = ", ".join(steps)
            console.print(f"[red]Unknown schema step:[/red] {only}")
            console.print(f"Valid options: {valid}")
            raise typer.Exit(code=1)
        selected = {only: steps[only]}
    else:
        selected = steps

    successes = 0
    failures = 0

    for _key, (description, cmd) in selected.items():
        console.print(f"  [bold]→[/bold] {description}")
        try:
            subprocess.run(cmd, check=True)  # noqa: S603
            console.print("    [green]✓[/green] Done")
            successes += 1
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            console.print(f"    [red]✗[/red] Failed: {exc}")
            failures += 1

    console.print()
    if failures:
        console.print(
            f"[yellow]⚠[/yellow] {successes} succeeded, {failures} failed — see errors above"
        )
    else:
        console.print(f"[green]✓[/green] All {successes} schema steps completed")


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


@infra_app.command()
def apply() -> None:
    """Provision ephemeral AWS infrastructure (DSQL clusters, Bedrock KB)."""
    console.print(Panel.fit("Provisioning Ephemeral Infrastructure", style="bold blue"))

    tf_dir = str(_terraform_dir())
    _run(["terraform", f"-chdir={tf_dir}", "init"])
    _run(["terraform", f"-chdir={tf_dir}", "apply", "-auto-approve"])

    console.print()
    console.print("[green]✓[/green] Infrastructure provisioned — outputs above")


@infra_app.command()
def destroy() -> None:
    """Destroy ephemeral AWS infrastructure."""
    console.print(Panel.fit("Destroying Ephemeral Infrastructure", style="bold red"))

    tf_dir = str(_terraform_dir())
    _run(["terraform", f"-chdir={tf_dir}", "destroy", "-auto-approve"])

    console.print("[green]✓[/green] Infrastructure destroyed")
