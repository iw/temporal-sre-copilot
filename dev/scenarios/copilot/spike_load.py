"""Sudden load spikes to trigger Copilot Stressed state.

Alternates between calm and spike phases. During spikes, workflow rate
jumps 5-10× to create backlog pressure, rising latency, and queue depth
— the amplifier signals that push the Copilot from Happy → Stressed.

Usage (from repo root):
    uv run python dev/scenarios/copilot/spike_load.py
    uv run python dev/scenarios/copilot/spike_load.py --base-rate 5 --spike-rate 50
    uv run python dev/scenarios/copilot/spike_load.py --spike-duration 60 --calm-duration 120
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from datetime import timedelta
from enum import StrEnum
from pathlib import Path

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from metrics import create_metrics_runtime

# ---------------------------------------------------------------------------
# Workflows & activities
# ---------------------------------------------------------------------------


@activity.defn
async def heavy_work(duration_ms: int) -> str:
    """Simulate CPU-bound work that takes longer under contention."""
    await asyncio.sleep(duration_ms / 1000)
    return f"done in {duration_ms}ms"


@activity.defn
async def db_operation(key: str) -> str:
    """Simulate a persistence operation."""
    await asyncio.sleep(0.08)
    return f"persisted {key}"


@workflow.defn
class SpikeWorkflow:
    """Workflow with multiple state transitions to amplify backlog signals."""

    @workflow.run
    async def run(self, work_ms: int = 150) -> str:
        r1 = await workflow.execute_activity(
            heavy_work, work_ms, start_to_close_timeout=timedelta(seconds=60)
        )
        r2 = await workflow.execute_activity(
            db_operation,
            f"rec-{workflow.info().workflow_id[-8:]}",
            start_to_close_timeout=timedelta(seconds=60),
        )
        r3 = await workflow.execute_activity(
            heavy_work, work_ms // 2, start_to_close_timeout=timedelta(seconds=60)
        )
        return f"{r1} | {r2} | {r3}"


# ---------------------------------------------------------------------------
# Phase management
# ---------------------------------------------------------------------------


class Phase(StrEnum):
    CALM = "calm"
    SPIKE = "spike"


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description="Load spikes for Copilot Stressed detection")
    parser.add_argument("--address", default="localhost:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--base-rate", type=float, default=5.0, help="calm wf/s (default: 5)")
    parser.add_argument("--spike-rate", type=float, default=40.0, help="spike wf/s (default: 40)")
    parser.add_argument("--spike-duration", type=int, default=60, help="spike sec (default: 60)")
    parser.add_argument("--calm-duration", type=int, default=90, help="calm seconds (default: 90)")
    parser.add_argument("--cycles", type=int, default=3, help="spike cycles (default: 3)")
    parser.add_argument("--work-ms", type=int, default=150, help="activity ms (default: 150)")
    parser.add_argument("--concurrency", type=int, default=30, help="max concurrent (default: 30)")
    parser.add_argument(
        "--metrics-port", type=int, default=9091, help="Prometheus port (default: 9091)"
    )
    args = parser.parse_args()

    task_queue = "copilot-spike-queue"
    total_duration = args.cycles * (args.spike_duration + args.calm_duration)
    runtime = create_metrics_runtime(args.metrics_port)

    print("=" * 60)
    print("⚡ COPILOT SPIKE TEST — Happy → Stressed Transitions")
    print("=" * 60)
    print(f"Address:        {args.address}")
    print(f"Base rate:      {args.base_rate} wf/s (calm)")
    print(f"Spike rate:     {args.spike_rate} wf/s (spike)")
    print(f"Spike duration: {args.spike_duration}s")
    print(f"Calm duration:  {args.calm_duration}s")
    print(f"Cycles:         {args.cycles}")
    print(f"Total duration: ~{_fmt(total_duration)}")
    print(f"Metrics:        http://0.0.0.0:{args.metrics_port}/metrics")
    print("=" * 60)

    client = await Client.connect(args.address, namespace=args.namespace, runtime=runtime)
    semaphore = asyncio.Semaphore(args.concurrency)

    stats: dict[str, int] = {"ok": 0, "err": 0}

    async def run_one(n: int) -> None:
        async with semaphore:
            wf_id = f"spike-{uuid.uuid4().hex[:8]}-{n}"
            try:
                await client.execute_workflow(
                    SpikeWorkflow.run, args.work_ms, id=wf_id, task_queue=task_queue
                )
                stats["ok"] += 1
            except Exception:
                stats["err"] += 1

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[SpikeWorkflow],
        activities=[heavy_work, db_operation],
        max_concurrent_activities=args.concurrency * 2,
        max_concurrent_workflow_tasks=args.concurrency * 2,
    ):
        t_start = time.time()
        pending: set[asyncio.Task[None]] = set()
        n = 0

        print(f"\n⏱️  Started at {time.strftime('%H:%M:%S')}\n")

        for cycle in range(1, args.cycles + 1):
            # --- CALM PHASE ---
            phase_start = time.time()
            rate = args.base_rate
            delay = 1.0 / rate
            print(f"  🟢 Cycle {cycle}/{args.cycles} — CALM ({args.calm_duration}s at {rate} wf/s)")

            while time.time() - phase_start < args.calm_duration:
                n += 1
                task = asyncio.create_task(run_one(n))
                pending.add(task)
                pending -= {t for t in pending if t.done()}
                await asyncio.sleep(delay)

            elapsed = time.time() - t_start
            print(f"    [{_fmt(elapsed)}] ✅ {stats['ok']} ok  ❌ {stats['err']} err")

            # --- SPIKE PHASE ---
            phase_start = time.time()
            rate = args.spike_rate
            delay = 1.0 / rate
            print(
                f"  🔴 Cycle {cycle}/{args.cycles} — SPIKE ({args.spike_duration}s at {rate} wf/s)"
            )

            while time.time() - phase_start < args.spike_duration:
                n += 1
                task = asyncio.create_task(run_one(n))
                pending.add(task)
                pending -= {t for t in pending if t.done()}
                await asyncio.sleep(delay)

            elapsed = time.time() - t_start
            print(f"    [{_fmt(elapsed)}] ✅ {stats['ok']} ok  ❌ {stats['err']} err")

        if pending:
            print(f"\n⏳ Draining {len(pending)} in-flight workflows...")
            await asyncio.gather(*pending, return_exceptions=True)

    total_time = time.time() - t_start
    total = stats["ok"] + stats["err"]

    print("\n" + "=" * 60)
    print("📊 SPIKE TEST RESULTS")
    print("=" * 60)
    print(f"Duration:    {_fmt(total_time)}")
    print(f"Workflows:   {total} ({stats['ok']} ok, {stats['err']} err)")
    print(f"Throughput:  {total / total_time:.1f} wf/s (avg)")
    print("=" * 60)
    if stats["err"] == 0:
        print("✅ All workflows completed — check Copilot for Stressed transitions")
    else:
        print(f"⚠️  {stats['err']} errors — Copilot should detect error-rate signals")


if __name__ == "__main__":
    asyncio.run(main())
