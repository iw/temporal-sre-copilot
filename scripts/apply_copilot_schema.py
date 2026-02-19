#!/usr/bin/env python3
"""Apply the Copilot DSQL schema from the host machine.

Usage:
    uv run python scripts/apply_copilot_schema.py

Reads COPILOT_DSQL_HOST and AWS_REGION from dev/.env.
Each DDL statement runs in its own transaction (DSQL requirement).
Idempotent — safe to run multiple times.
"""

import asyncio
import sys
from pathlib import Path

import asyncpg
import boto3


def load_env(env_path: Path) -> dict[str, str]:
    """Parse a .env file into a dict, ignoring comments and blank lines."""
    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


async def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    env = load_env(repo_root / "dev" / ".env")

    endpoint = env.get("COPILOT_DSQL_HOST", "")
    region = env.get("AWS_REGION", "eu-west-1")
    database = env.get("COPILOT_DSQL_DATABASE", "postgres")

    if not endpoint:
        print("ERROR: COPILOT_DSQL_HOST not set in dev/.env")
        sys.exit(1)

    print(f"Endpoint: {endpoint}")
    print(f"Database: {database}")
    print(f"Region:   {region}")

    # Generate IAM auth token
    client = boto3.client("dsql", region_name=region)
    token = client.generate_db_connect_admin_auth_token(Hostname=endpoint, Region=region)

    # Load schema SQL
    schema_path = repo_root / "packages" / "copilot" / "src" / "copilot" / "db" / "schema.sql"
    schema_sql = schema_path.read_text()

    # Connect
    conn = await asyncpg.connect(
        host=endpoint,
        port=5432,
        user="admin",
        password=token,
        database=database,
        ssl="require",
    )

    try:
        # Split on semicolons, execute each statement individually
        statements = []
        for stmt in schema_sql.split(";"):
            # Strip leading comment lines so we don't discard real DDL
            lines = stmt.strip().splitlines()
            while lines and lines[0].strip().startswith("--"):
                lines.pop(0)
            cleaned = "\n".join(lines).strip()
            if cleaned:
                statements.append(cleaned)

        for i, stmt in enumerate(statements, 1):
            # Extract first line for display
            first_line = stmt.split("\n")[0][:80]
            try:
                await conn.execute(stmt)
                print(f"  [{i}/{len(statements)}] ✓ {first_line}")
            except asyncpg.DuplicateTableError:
                print(f"  [{i}/{len(statements)}] ○ already exists: {first_line}")
            except asyncpg.DuplicateObjectError:
                print(f"  [{i}/{len(statements)}] ○ already exists: {first_line}")
            except Exception as e:
                print(f"  [{i}/{len(statements)}] ✗ FAILED: {first_line}")
                print(f"    {e}")

        print("\n✓ Schema setup complete!")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
