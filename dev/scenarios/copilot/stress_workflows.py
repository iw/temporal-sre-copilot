"""Sustained WPS load for Copilot forward-progress signals.

Generates a steady stream of workflows at a configurable rate so the
Copilot's ObserveClusterWorkflow can observe healthy forward-progress
signals: state transitions/sec, completion rate, and processing rate.

Usage (from repo root):
    uv run python dev/scenarios/copilot/stress_workflows.py
    uv run python dev/scenarios/copilot/stress_workflows.py --rate 20 --duration 10
    uv run python dev/scenarios/copilot/stress_workflows.py --address copilot-temporal:7233
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker

# Allow running as a script — add parent to path for metrics import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from metrics import create_metrics_runtime

# ---------------------------------------------------------------------------
# Workflows & activities
# ---------------------------------------------------------------------------


@activity.defn
async def do_work(duration_ms: int) -> str:
    """Simulate work for a configurable duration."""
    await asyncio.sleep(duration_ms / 1000)
    return f"completed in {duration_ms}ms"


@activity.defn
async def do_io(item: str) -> str:
    """Simulate an I/O-bound activity (DB read, API call)."""
    await asyncio.sleep(0.05)
    return f"fetched {item}"


@workflow.defn
class StressWorkflow:
    """Multi-step workflow that exercises state transitions and activities."""

    @workflow.run
    async def run(self, work_ms: int = 100) -> str:
        r1 = await workflow.execute_activity(
            do_work, work_ms, start_to_close_timeout=timedelta(seconds=30)
        )
        r2 = await workflow.execute_activity(
            do_io, "record-1", start_to_close_timeout=timedelta(seconds=30)
        )
        await workflow.sleep(timedelta(milliseconds=200))
        return f"{r1} | {r2}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Sustained WPS load for Copilot signals")
    parser.add_argument("--address", default="localhost:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--rate", type=float, default=10.0, help="wf/s (default: 10)")
    parser.add_argument("--duration", type=int, default=5, help="minutes (default: 5)")
    parser.add_argument("--work-ms", type=int, default=100, help="activity ms (default: 100)")
    parser.add_argument("--concurrency", type=int, default=20, help="max concurrent (default: 20)")
    parser.add_argument(
        "--metrics-port", type=int, default=9091, help="Prometheus port (default: 9091)"
    )
    args = parser.parse_args()

    task_queue = "copilot-stress-queue"
    duration_sec = args.duration * 60
    runtime = create_metrics_runtime(args.metrics_port)

    print("=" * 60)
    print("📈 COPILOT STRESS TEST — Sustained Forward Progress")
    print("=" * 60)
    print(f"Address:     {args.address}")
    print(f"Rate:        {args.rate} wf/s")
    print(f"Duration:    {args.duration} min")
    print(f"Work/wf:     {args.work_ms}ms")
    print(f"Concurrency: {args.concurrency}")
    print(f"Metrics:     http://0.0.0.0:{args.metrics_port}/metrics")
    print("=" * 60)

    client = await Client.connect(args.address, namespace=args.namespace, runtime=runtime)
    semaphore = asyncio.Semaphore(args.concurrency)

    total_ok = 0
    total_err = 0
    durations: list[float] = []

    async def run_one(n: int) -> None:
        nonlocal total_ok, total_err
        async with semaphore:
            wf_id = f"stress-{uuid.uuid4().hex[:8]}-{n}"
            t0 = time.time()
            try:
                await client.execute_workflow(
                    StressWorkflow.run,
                    args.work_ms,
                    id=wf_id,
                    task_queue=task_queue,
                )
                durations.append(time.time() - t0)
                total_ok += 1
            except Exception as e:
                total_err += 1
                if total_err <= 3:
                    print(f"  ❌ {wf_id}: {e!s:.120}")

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[StressWorkflow],
        activities=[do_work, do_io],
        max_concurrent_activities=args.concurrency * 2,
        max_concurrent_workflow_tasks=args.concurrency * 2,
    ):
        t_start = time.time()
        t_report = t_start
        pending: set[asyncio.Task[None]] = set()
        n = 0
        delay = 1.0 / args.rate

        print(f"\n⏱️  Started at {time.strftime('%H:%M:%S')}\n")

        while time.time() - t_start < duration_sec:
            n += 1
            task = asyncio.create_task(run_one(n))
            pending.add(task)
            pending -= {t for t in pending if t.done()}

            now = time.time()
            if now - t_report >= 30:
                elapsed = now - t_start
                rate = total_ok / elapsed if elapsed > 0 else 0
                avg = sum(durations[-100:]) / len(durations[-100:]) if durations else 0
                print(
                    f"  [{_fmt(elapsed)}] "
                    f"✅ {total_ok} ok  ❌ {total_err} err  "
                    f"⚡ {rate:.1f}/s  📊 avg={avg:.2f}s"
                )
                t_report = now

            await asyncio.sleep(delay)

        if pending:
            print(f"\n⏳ Draining {len(pending)} in-flight workflows...")
            await asyncio.gather(*pending, return_exceptions=True)

    total_time = time.time() - t_start
    total = total_ok + total_err

    print("\n" + "=" * 60)
    print("📊 RESULTS")
    print("=" * 60)
    print(f"Duration:    {_fmt(total_time)}")
    print(f"Workflows:   {total} ({total_ok} ok, {total_err} err)")
    print(f"Throughput:  {total / total_time:.1f} wf/s")
    if durations:
        s = sorted(durations)
        print(f"Latency p50: {s[len(s) // 2]:.3f}s")
        print(f"Latency p99: {s[int(len(s) * 0.99)]:.3f}s")
        print(f"Latency max: {s[-1]:.3f}s")
    print("=" * 60)
    if total_err == 0:
        print("✅ All workflows completed successfully")
    else:
        print(f"⚠️  {total_err} errors during test")


if __name__ == "__main__":
    asyncio.run(main())
