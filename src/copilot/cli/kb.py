"""Knowledge Base CLI commands for the Temporal SRE Copilot."""

from pathlib import Path  # noqa: TC003 — typer needs runtime Path
from typing import Annotated

import boto3
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command()
def sync(
    bucket: Annotated[str, typer.Option("--bucket", "-b", help="S3 bucket for KB source docs")],
    source_dir: Annotated[
        Path, typer.Option("--source", "-s", help="Local directory with source documents")
    ],
    region: Annotated[str, typer.Option("--region", "-r", help="AWS region")] = "eu-west-1",
) -> None:
    """Sync documentation to S3 for Knowledge Base ingestion.

    Uploads markdown files from the source directory to S3.
    """
    console.print(Panel.fit("Syncing Knowledge Base Documents", style="bold blue"))

    if not source_dir.exists():
        console.print(f"[red]Error:[/red] Source directory not found: {source_dir}")
        raise typer.Exit(1)

    s3 = boto3.client("s3", region_name=region)

    # Find all markdown files
    md_files = list(source_dir.rglob("*.md"))
    if not md_files:
        console.print(f"[yellow]No markdown files found in {source_dir}[/yellow]")
        return

    console.print(f"  Bucket: [cyan]{bucket}[/cyan]")
    console.print(f"  Source: [cyan]{source_dir}[/cyan]")
    console.print(f"  Files:  [cyan]{len(md_files)}[/cyan]")
    console.print()

    uploaded = 0
    with console.status("[bold green]Uploading..."):
        for md_file in md_files:
            relative_path = md_file.relative_to(source_dir)
            s3_key = str(relative_path)

            try:
                s3.upload_file(str(md_file), bucket, s3_key)
                uploaded += 1
                console.print(f"  [green]✓[/green] {s3_key}")
            except Exception as e:
                console.print(f"  [red]✗[/red] {s3_key}: {e}")

    console.print()
    console.print(f"[green]✓[/green] Uploaded {uploaded}/{len(md_files)} files")


@app.command()
def start_ingestion(
    knowledge_base_id: Annotated[
        str, typer.Option("--kb-id", "-k", help="Bedrock Knowledge Base ID")
    ],
    data_source_id: Annotated[str, typer.Option("--ds-id", "-d", help="Data Source ID")],
    region: Annotated[str, typer.Option("--region", "-r", help="AWS region")] = "eu-west-1",
) -> None:
    """Start a Knowledge Base ingestion job.

    Triggers Bedrock to re-index documents from the S3 data source.
    """
    console.print(Panel.fit("Starting Knowledge Base Ingestion", style="bold blue"))

    console.print(f"  Knowledge Base: [cyan]{knowledge_base_id}[/cyan]")
    console.print(f"  Data Source:    [cyan]{data_source_id}[/cyan]")
    console.print()

    bedrock_agent = boto3.client("bedrock-agent", region_name=region)

    with console.status("[bold green]Starting ingestion job..."):
        try:
            response = bedrock_agent.start_ingestion_job(
                knowledgeBaseId=knowledge_base_id,
                dataSourceId=data_source_id,
            )
            job_id = response["ingestionJob"]["ingestionJobId"]
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None

    console.print(f"[green]✓[/green] Ingestion job started: [cyan]{job_id}[/cyan]")
    console.print()
    console.print("Check status with:")
    console.print(f"  copilot kb status --kb-id {knowledge_base_id} --job-id {job_id}")


@app.command()
def status(
    knowledge_base_id: Annotated[
        str, typer.Option("--kb-id", "-k", help="Bedrock Knowledge Base ID")
    ],
    job_id: Annotated[str, typer.Option("--job-id", "-j", help="Ingestion Job ID")] = "",
    region: Annotated[str, typer.Option("--region", "-r", help="AWS region")] = "eu-west-1",
) -> None:
    """Check Knowledge Base or ingestion job status."""
    console.print(Panel.fit("Knowledge Base Status", style="bold blue"))

    bedrock_agent = boto3.client("bedrock-agent", region_name=region)

    if job_id:
        # Get specific job status
        try:
            response = bedrock_agent.get_ingestion_job(
                knowledgeBaseId=knowledge_base_id,
                dataSourceId="",  # Not needed for get
                ingestionJobId=job_id,
            )
            job = response["ingestionJob"]
            console.print(f"  Job ID:     [cyan]{job['ingestionJobId']}[/cyan]")
            console.print(f"  Status:     [cyan]{job['status']}[/cyan]")
            if "statistics" in job:
                stats = job["statistics"]
                console.print(f"  Documents:  {stats.get('numberOfDocumentsScanned', 0)} scanned")
                console.print(f"              {stats.get('numberOfDocumentsIndexed', 0)} indexed")
                console.print(f"              {stats.get('numberOfDocumentsFailed', 0)} failed")
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None
    else:
        # Get KB status
        try:
            response = bedrock_agent.get_knowledge_base(knowledgeBaseId=knowledge_base_id)
            kb = response["knowledgeBase"]
            console.print(f"  Name:       [cyan]{kb['name']}[/cyan]")
            console.print(f"  Status:     [cyan]{kb['status']}[/cyan]")
            console.print(f"  Created:    {kb['createdAt']}")
            console.print(f"  Updated:    {kb['updatedAt']}")
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None


@app.command()
def list_jobs(
    knowledge_base_id: Annotated[
        str, typer.Option("--kb-id", "-k", help="Bedrock Knowledge Base ID")
    ],
    data_source_id: Annotated[str, typer.Option("--ds-id", "-d", help="Data Source ID")],
    region: Annotated[str, typer.Option("--region", "-r", help="AWS region")] = "eu-west-1",
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max jobs to show")] = 10,
) -> None:
    """List recent ingestion jobs."""
    console.print(Panel.fit("Recent Ingestion Jobs", style="bold blue"))

    bedrock_agent = boto3.client("bedrock-agent", region_name=region)

    try:
        response = bedrock_agent.list_ingestion_jobs(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id,
            maxResults=limit,
        )
        jobs = response.get("ingestionJobSummaries", [])
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    if not jobs:
        console.print("[yellow]No ingestion jobs found.[/yellow]")
        return

    table = Table()
    table.add_column("Job ID", style="cyan")
    table.add_column("Status")
    table.add_column("Started")

    for job in jobs:
        status_style = {
            "COMPLETE": "green",
            "IN_PROGRESS": "yellow",
            "FAILED": "red",
        }.get(job["status"], "white")

        table.add_row(
            job["ingestionJobId"],
            f"[{status_style}]{job['status']}[/{status_style}]",
            str(job.get("startedAt", "")),
        )

    console.print(table)
