"""Database CLI commands for the Temporal SRE Copilot."""

import asyncio
from pathlib import Path
from typing import Annotated

import asyncpg
import boto3
import typer
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(no_args_is_help=True)
console = Console()


def get_dsql_token(endpoint: str, region: str) -> str:
    """Generate IAM auth token for DSQL connection."""
    client = boto3.client("dsql", region_name=region)
    return client.generate_db_connect_admin_auth_token(hostname=endpoint, region=region)


async def execute_schema(endpoint: str, database: str, region: str, schema_sql: str) -> None:
    """Execute schema SQL against DSQL."""
    token = get_dsql_token(endpoint, region)

    conn = await asyncpg.connect(
        host=endpoint,
        port=5432,
        user="admin",
        password=token,
        database=database,
        ssl="require",
    )

    try:
        await conn.execute(schema_sql)
    finally:
        await conn.close()


@app.command()
def setup_schema(
    endpoint: Annotated[str, typer.Option("--endpoint", "-e", help="DSQL cluster endpoint")],
    database: Annotated[str, typer.Option("--database", "-d", help="Database name")] = "copilot",
    region: Annotated[str, typer.Option("--region", "-r", help="AWS region")] = "eu-west-1",
) -> None:
    """Apply the Copilot schema to Aurora DSQL.

    Creates the health_assessments, issues, and metrics_snapshots tables
    with appropriate indexes for the Copilot state store.
    """
    console.print(Panel.fit("Setting up Copilot DSQL Schema", style="bold blue"))

    console.print(f"  Endpoint: [cyan]{endpoint}[/cyan]")
    console.print(f"  Database: [cyan]{database}[/cyan]")
    console.print(f"  Region:   [cyan]{region}[/cyan]")
    console.print()

    # Load schema from package
    schema_path = Path(__file__).parent.parent / "db" / "schema.sql"
    if not schema_path.exists():
        console.print(f"[red]Error:[/red] Schema file not found: {schema_path}")
        raise typer.Exit(1)

    schema_sql = schema_path.read_text()

    with console.status("[bold green]Applying schema..."):
        try:
            asyncio.run(execute_schema(endpoint, database, region, schema_sql))
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None

    console.print("[green]✓[/green] Schema setup complete!")


@app.command()
def check_connection(
    endpoint: Annotated[str, typer.Option("--endpoint", "-e", help="DSQL cluster endpoint")],
    database: Annotated[str, typer.Option("--database", "-d", help="Database name")] = "copilot",
    region: Annotated[str, typer.Option("--region", "-r", help="AWS region")] = "eu-west-1",
) -> None:
    """Test connection to Aurora DSQL."""
    console.print(Panel.fit("Testing DSQL Connection", style="bold blue"))

    async def test_connection() -> str:
        token = get_dsql_token(endpoint, region)
        conn = await asyncpg.connect(
            host=endpoint,
            port=5432,
            user="admin",
            password=token,
            database=database,
            ssl="require",
        )
        try:
            version = await conn.fetchval("SELECT version()")
            return version
        finally:
            await conn.close()

    with console.status("[bold green]Connecting..."):
        try:
            version = asyncio.run(test_connection())
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None

    console.print("[green]✓[/green] Connected successfully!")
    console.print(f"  Version: [dim]{version}[/dim]")


@app.command()
def list_tables(
    endpoint: Annotated[str, typer.Option("--endpoint", "-e", help="DSQL cluster endpoint")],
    database: Annotated[str, typer.Option("--database", "-d", help="Database name")] = "copilot",
    region: Annotated[str, typer.Option("--region", "-r", help="AWS region")] = "eu-west-1",
) -> None:
    """List tables in the Copilot database."""
    console.print(Panel.fit("Copilot Database Tables", style="bold blue"))

    async def get_tables() -> list[tuple[str, int]]:
        token = get_dsql_token(endpoint, region)
        conn = await asyncpg.connect(
            host=endpoint,
            port=5432,
            user="admin",
            password=token,
            database=database,
            ssl="require",
        )
        try:
            rows = await conn.fetch("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)
            tables = []
            for row in rows:
                count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {row['table_name']}"  # noqa: S608
                )
                tables.append((row["table_name"], count))
            return tables
        finally:
            await conn.close()

    with console.status("[bold green]Fetching tables..."):
        try:
            tables = asyncio.run(get_tables())
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None

    if not tables:
        console.print("[yellow]No tables found.[/yellow] Run 'copilot db setup-schema' first.")
        return

    for table_name, count in tables:
        console.print(f"  [cyan]{table_name}[/cyan]: {count} rows")
