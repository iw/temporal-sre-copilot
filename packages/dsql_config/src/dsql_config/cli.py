"""Typer CLI for temporal-dsql-config.

Commands:
  compile          Compile a preset into configuration artifacts
  list-presets     List available scale presets
  describe-preset  Describe a preset's resolved parameters
  explain          Explain configuration at three levels (key, preset, profile)
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — Typer evaluates type hints at runtime
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from copilot_core.types import ParameterOverrides
from dsql_config.compiler import CompilationError, ConfigCompiler
from dsql_config.models import ConfigProfile  # noqa: TC001 — used in function signature
from dsql_config.registry import build_default_registry

app = typer.Typer(
    name="temporal-dsql-config",
    help="Configuration compiler for Temporal DSQL deployments",
    no_args_is_help=True,
)
console = Console()

CONFIG_BASE_DIR = Path(".temporal-dsql")
LATEST_FILE = ".latest"


def _build_compiler() -> ConfigCompiler:
    return ConfigCompiler(build_default_registry())


def _parse_overrides(overrides: list[str]) -> ParameterOverrides:
    """Parse key=value override strings into ParameterOverrides."""
    values: dict[str, int | float | str | bool] = {}
    for item in overrides:
        if "=" not in item:
            console.print(f"[red]Invalid override format: '{item}'. Use key=value[/red]")
            raise typer.Exit(1)
        key, raw = item.split("=", 1)
        lower = raw.strip().lower()
        if lower in ("true", "yes"):
            values[key.strip()] = True
        elif lower in ("false", "no"):
            values[key.strip()] = False
        else:
            try:
                values[key.strip()] = int(raw)
            except ValueError:
                try:
                    values[key.strip()] = float(raw)
                except ValueError:
                    values[key.strip()] = raw
    return ParameterOverrides(values=values)


def _resolve_output_dir(
    *, name: str | None, output: Path | None, preset: str, modifier: str | None
) -> Path:
    """Resolve the output directory for compiled artifacts.

    Priority: --output (explicit path) > --name (under .temporal-dsql/) > auto-generated name.
    """
    if output:
        return output

    if not name:
        parts = [preset]
        if modifier:
            parts.append(modifier)
        name = "-".join(parts)

    return CONFIG_BASE_DIR / name


def _write_latest(config_name: str) -> None:
    """Write the .latest file pointing to the given config name."""
    CONFIG_BASE_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_BASE_DIR / LATEST_FILE).write_text(config_name + "\n")


def _read_latest() -> str | None:
    """Read the latest config name from .temporal-dsql/.latest, or None."""
    latest_path = CONFIG_BASE_DIR / LATEST_FILE
    if not latest_path.exists():
        return None
    content = latest_path.read_text().strip()
    return content if content else None


def _resolve_profile_path(profile_json: Path | None) -> Path:
    """Resolve a profile.json path, falling back to .latest if no path given."""
    if profile_json:
        return profile_json

    latest = _read_latest()
    if not latest:
        console.print("[red]No --profile given and no .temporal-dsql/.latest found.[/red]")
        console.print("Run [cyan]compile[/cyan] first, or pass --profile explicitly.")
        raise typer.Exit(1)

    path = CONFIG_BASE_DIR / latest / "profile.json"
    if not path.exists():
        console.print(f"[red]Profile not found: {path}[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]Using latest config: {latest}[/dim]")
    return path


@app.command()
def compile(
    preset: Annotated[
        str, typer.Argument(help="Scale preset name (starter, mid-scale, high-throughput)")
    ],
    modifier: Annotated[
        str | None, typer.Option("--modifier", "-m", help="Workload modifier")
    ] = None,
    override: Annotated[
        list[str] | None, typer.Option("--override", "-o", help="Parameter override (key=value)")
    ] = None,
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="Config name (stored under .temporal-dsql/<name>/)"),
    ] = None,
    output_dir: Annotated[
        Path | None, typer.Option("--output", help="Explicit output directory (overrides --name)")
    ] = None,
    format: Annotated[
        str, typer.Option("--format", "-f", help="Output format: text or json")
    ] = "text",
    deployment: Annotated[
        str | None,
        typer.Option("--deployment", "-d", help="Deployment platform (compose, ecs)"),
    ] = None,
    from_path: Annotated[
        Path | None,
        typer.Option(
            "--from",
            help="Existing platform config (docker-compose.yml or ECS task def). "
            "Resolved via `docker compose config` for compose.",
        ),
    ] = None,
    annotation: Annotated[
        list[str] | None,
        typer.Option("--annotation", "-a", help="Deployment adapter annotation (key=value)"),
    ] = None,
) -> None:
    """Compile a scale preset into configuration artifacts."""
    compiler = _build_compiler()
    overrides = _parse_overrides(override or [])

    try:
        result = compiler.compile(preset, modifier=modifier, overrides=overrides)
    except CompilationError as e:
        console.print("[red]Compilation failed:[/red]")
        for err in e.errors:
            console.print(f"  [red]✗[/red] {err}")
        raise typer.Exit(1) from None
    except (ValueError, TypeError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None

    # Determine whether to write artifacts or print to stdout
    should_write = name is not None or output_dir is not None

    if should_write:
        target = _resolve_output_dir(name=name, output=output_dir, preset=preset, modifier=modifier)
        target.mkdir(parents=True, exist_ok=True)

        (target / "profile.json").write_text(result.profile.model_dump_json(indent=2))
        (target / "dynamic_config.yaml").write_text(result.dynamic_config_yaml)
        (target / "dsql_plugin.json").write_text(
            result.dsql_plugin_config.model_dump_json(indent=2)
        )
        for snippet in result.sdk_snippets + result.platform_snippets:
            (target / snippet.filename).write_text(snippet.content)

        # Update .latest when writing to the convention directory (not --output)
        if not output_dir:
            config_name = name if name else f"{preset}-{modifier}" if modifier else preset
            _write_latest(config_name)

        console.print(f"[green]Artifacts written to {target}[/green]")
        if result.guard_rail_results:
            for gr in result.guard_rail_results:
                color = "yellow" if gr.severity == "warning" else "red"
                console.print(f"  [{color}]{gr.severity}[/{color}]: {gr.message}")
    else:
        if format == "json":
            console.print(result.model_dump_json(indent=2))
        else:
            console.print(f"[bold]Preset:[/bold] {result.profile.preset_name}")
            if result.profile.modifier:
                console.print(f"[bold]Modifier:[/bold] {result.profile.modifier}")
            console.print()
            console.print(result.why_section)
            if result.guard_rail_results:
                console.print()
                for gr in result.guard_rail_results:
                    color = "yellow" if gr.severity == "warning" else "red"
                    console.print(f"  [{color}]{gr.severity}[/{color}]: {gr.message}")

    # Emit deployment profile if --deployment is specified
    if deployment:
        _emit_deployment_profile(
            result.profile,
            deployment=deployment,
            from_path=from_path,
            annotations=annotation or [],
            output_dir=target if should_write else None,
        )


def _emit_deployment_profile(
    profile: ConfigProfile,
    *,
    deployment: str,
    from_path: Path | None,
    annotations: list[str],
    output_dir: Path | None,
) -> None:
    """Generate a DeploymentProfile and write it alongside other artifacts.

    For compose: resolves the compose file via ``docker compose config``
    to extract DSQL endpoint and resource limits. If ``--from`` is omitted,
    generates a prototypical compose deployment with defaults.

    For ecs: uses annotations for cluster ARN, DSQL endpoint, etc.
    """
    import subprocess

    from dsql_config.adapters import discover_deployment_adapters

    # Parse annotations
    ann: dict[str, str] = {}
    for item in annotations:
        if "=" not in item:
            console.print(f"[red]Invalid annotation: '{item}'. Use key=value[/red]")
            raise typer.Exit(1)
        k, v = item.split("=", 1)
        ann[k.strip()] = v.strip()

    # Resolve compose config from --from path
    if deployment == "compose" and from_path:
        try:
            result = subprocess.run(  # noqa: S603
                ["docker", "compose", "-f", str(from_path), "config"],
                capture_output=True,
                text=True,
                check=True,
            )
            ann["compose_config"] = result.stdout
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            console.print(f"[red]Failed to resolve compose config: {exc}[/red]")
            raise typer.Exit(1) from None

    # Find the adapter
    adapters = discover_deployment_adapters()
    matched = [a for a in adapters if a.platform == deployment]
    if not matched:
        available = [a.platform for a in adapters]
        console.print(f"[red]Unknown deployment '{deployment}'. Available: {available}[/red]")
        raise typer.Exit(1)

    deployment_profile = matched[0].render_deployment(profile, ann)

    # Validate round-trip
    from copilot_core.deployment import DeploymentProfile

    json_str = deployment_profile.model_dump_json(indent=2)
    DeploymentProfile.model_validate_json(json_str)

    # Write output
    if output_dir:
        output_path = output_dir / "deployment-profile.json"
        output_path.write_text(json_str + "\n")
        console.print(f"[green]Deployment profile written to {output_path}[/green]")
    else:
        console.print(json_str)


@app.command("list-presets")
def list_presets() -> None:
    """List available scale presets."""
    compiler = _build_compiler()
    summaries = compiler.list_presets()

    table = Table(title="Available Scale Presets")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Throughput Range", style="green")

    for s in summaries:
        table.add_row(s.name, s.description, s.throughput_range.description)

    console.print(table)


@app.command("describe-preset")
def describe_preset(
    preset: Annotated[str, typer.Argument(help="Scale preset name")],
    modifier: Annotated[
        str | None, typer.Option("--modifier", "-m", help="Workload modifier")
    ] = None,
    format: Annotated[
        str, typer.Option("--format", "-f", help="Output format: text or json")
    ] = "text",
) -> None:
    """Describe a preset's resolved parameters grouped by classification."""
    compiler = _build_compiler()

    try:
        desc = compiler.describe_preset(preset, modifier=modifier)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None

    if format == "json":
        console.print(desc.model_dump_json(indent=2))
        return

    console.print(f"[bold]{desc.name}[/bold] — {desc.description}")
    console.print(f"Throughput: {desc.throughput_range.description}")
    console.print()

    for label, params in [
        ("SLO Parameters", desc.slo_params),
        ("Topology Parameters", desc.topology_params),
        ("Safety Parameters", desc.safety_params),
        ("Tuning Parameters", desc.tuning_params),
    ]:
        table = Table(title=label)
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="green")
        table.add_column("Source")
        for p in params:
            table.add_row(p.key, str(p.value), p.source)
        console.print(table)
        console.print()


@app.command()
def explain(
    key: Annotated[
        str | None, typer.Option("--key", "-k", help="Explain a specific parameter key")
    ] = None,
    preset: Annotated[
        str | None, typer.Option("--preset", "-p", help="Explain a preset's reasoning")
    ] = None,
    modifier: Annotated[
        str | None, typer.Option("--modifier", "-m", help="Workload modifier (with --preset)")
    ] = None,
    profile_json: Annotated[
        Path | None,
        typer.Option("--profile", help="Profile JSON file (omit to use latest compiled config)"),
    ] = None,
    format: Annotated[
        str, typer.Option("--format", "-f", help="Output format: text or json")
    ] = "text",
) -> None:
    """Explain configuration at three levels.

    --key: explain a single parameter (uses starter profile as context)
    --preset: explain a preset's reasoning chain
    --profile: explain a compiled profile (falls back to .temporal-dsql/.latest)
    """
    compiler = _build_compiler()

    if key:
        # Level 1: need a profile to show the resolved value
        result = compiler.compile("starter")
        try:
            explanation = compiler.explain_key(key, result.profile)
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1) from None
        console.print(explanation.to_json() if format == "json" else explanation.to_text())

    elif preset:
        # Level 2: explain preset reasoning
        try:
            explanation = compiler.explain_preset(preset, modifier=modifier)
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1) from None
        console.print(explanation.to_json() if format == "json" else explanation.to_text())

    else:
        # Level 3: explain compiled profile — resolve from .latest if no path given
        from dsql_config.models import ConfigProfile

        path = _resolve_profile_path(profile_json)
        try:
            profile = ConfigProfile.model_validate_json(path.read_text())
        except Exception as e:
            console.print(f"[red]Error reading profile: {e}[/red]")
            raise typer.Exit(1) from None
        explanation = compiler.explain_profile(profile)
        console.print(explanation.to_json() if format == "json" else explanation.to_text())
