"""Error injection for Copilot error-rate and completion-rate signals.

Generates a mix of succeeding and failing workflows so the Copilot can
observe degraded completion rates, rising error rates, and activity
failure patterns. Configurable failure percentage and failure modes.

Usage (from repo root):
    uv run python dev/scenarios/copilot/error_injection.py
    uv run python dev/scenarios/copilot/error_injection.py --failure-pct 30 --rate 15
    uv run python dev/scenarios/copilot/error_injection.py --mode timeout --failure-pct 50
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from metrics import create_metrics_runtime

# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


@activity.defn
async def reliable_work(item: str) -> str:
    """Always succeeds."""
    await asyncio.sleep(0.05)
    return f"processed {item}"


@activity.defn
async def flaky_work(params: dict) -> str:  # noqa: UP006
    """Fails based on injected parameters.

    params:
        should_fail: bool
        failure_mode: "exception" | "timeout"
        work_ms: int
    """
    work_ms = params.get("work_ms", 100)

    if params.get("should_fail"):
        mode = params.get("failure_mode", "exception")
        if mode == "timeout":
            await asyncio.sleep(120)
            return "unreachable"
        raise ApplicationError(
            f"Injected failure for testing (mode={mode})",
            non_retryable=True,
        )

    await asyncio.sleep(work_ms / 1000)
    return f"ok in {work_ms}ms"


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


@workflow.defn
class ErrorInjectionWorkflow:
    """Workflow that may fail depending on injected parameters."""

    @workflow.run
    async def run(self, params: dict) -> str:  # noqa: UP006
        r1 = await workflow.execute_activity(
            reliable_work,
            f"item-{workflow.info().workflow_id[-8:]}",
            start_to_close_timeout=timedelta(seconds=30),
        )

        timeout = (
            timedelta(seconds=5)
            if params.get("failure_mode") == "timeout"
            else timedelta(seconds=30)
        )
        r2 = await workflow.execute_activity(
            flaky_work,
            params,
            start_to_close_timeout=timeout,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        return f"{r1} | {r2}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Error injection for Copilot error-rate signals")
    parser.add_argument("--address", default="localhost:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--rate", type=float, default=10.0, help="wf/s (default: 10)")
    parser.add_argument("--duration", type=int, default=5, help="minutes (default: 5)")
    parser.add_argument("--failure-pct", type=int, default=20, help="failure %% (default: 20)")
    parser.add_argument(
        "--mode",
        choices=["exception", "timeout", "mixed"],
        default="exception",
        help="Failure mode (default: exception)",
    )
    parser.add_argument("--work-ms", type=int, default=100, help="activity ms (default: 100)")
    parser.add_argument("--concurrency", type=int, default=20, help="max concurrent (default: 20)")
    parser.add_argument(
        "--metrics-port", type=int, default=9091, help="Prometheus port (default: 9091)"
    )
    args = parser.parse_args()

    task_queue = "copilot-error-queue"
    duration_sec = args.duration * 60
    runtime = create_metrics_runtime(args.metrics_port)

    print("=" * 60)
    print("💥 COPILOT ERROR INJECTION — Completion Rate Degradation")
    print("=" * 60)
    print(f"Address:     {args.address}")
    print(f"Rate:        {args.rate} wf/s")
    print(f"Duration:    {args.duration} min")
    print(f"Failure %:   {args.failure_pct}%")
    print(f"Mode:        {args.mode}")
    print(f"Work/wf:     {args.work_ms}ms")
    print(f"Metrics:     http://0.0.0.0:{args.metrics_port}/metrics")
    print("=" * 60)
    print()
    print(f"Expected: ~{int(args.rate * duration_sec)} workflows,")
    print(f"          ~{int(args.rate * duration_sec * args.failure_pct / 100)} failures")
    print()

    client = await Client.connect(args.address, namespace=args.namespace, runtime=runtime)
    semaphore = asyncio.Semaphore(args.concurrency)

    stats = {"ok": 0, "failed_expected": 0, "failed_unexpected": 0}

    async def run_one(n: int) -> None:
        async with semaphore:
            should_fail = random.randint(1, 100) <= args.failure_pct  # noqa: S311

            if args.mode == "mixed":
                failure_mode = random.choice(["exception", "timeout"])  # noqa: S311
            else:
                failure_mode = args.mode

            params = {
                "should_fail": should_fail,
                "failure_mode": failure_mode,
                "work_ms": args.work_ms,
            }

            wf_id = f"errinj-{uuid.uuid4().hex[:8]}-{n}"
            try:
                await client.execute_workflow(
                    ErrorInjectionWorkflow.run,
                    params,
                    id=wf_id,
                    task_queue=task_queue,
                )
                stats["ok"] += 1
            except Exception:
                if should_fail:
                    stats["failed_expected"] += 1
                else:
                    stats["failed_unexpected"] += 1

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[ErrorInjectionWorkflow],
        activities=[reliable_work, flaky_work],
        max_concurrent_activities=args.concurrency * 2,
        max_concurrent_workflow_tasks=args.concurrency * 2,
    ):
        t_start = time.time()
        t_report = t_start
        pending: set[asyncio.Task[None]] = set()
        n = 0
        delay = 1.0 / args.rate

        print(f"⏱️  Started at {time.strftime('%H:%M:%S')}\n")

        while time.time() - t_start < duration_sec:
            n += 1
            task = asyncio.create_task(run_one(n))
            pending.add(task)
            pending -= {t for t in pending if t.done()}

            now = time.time()
            if now - t_report >= 30:
                elapsed = now - t_start
                total = stats["ok"] + stats["failed_expected"] + stats["failed_unexpected"]
                fail_rate = (
                    (stats["failed_expected"] + stats["failed_unexpected"]) / total * 100
                    if total > 0
                    else 0
                )
                print(
                    f"  [{_fmt(elapsed)}] "
                    f"✅ {stats['ok']}  💥 {stats['failed_expected']} (injected)  "
                    f"❌ {stats['failed_unexpected']} (unexpected)  "
                    f"fail={fail_rate:.0f}%"
                )
                t_report = now

            await asyncio.sleep(delay)

        if pending:
            print(f"\n⏳ Draining {len(pending)} in-flight workflows...")
            await asyncio.gather(*pending, return_exceptions=True)

    total_time = time.time() - t_start
    total = stats["ok"] + stats["failed_expected"] + stats["failed_unexpected"]
    actual_fail_pct = (
        (stats["failed_expected"] + stats["failed_unexpected"]) / total * 100 if total > 0 else 0
    )

    print("\n" + "=" * 60)
    print("📊 ERROR INJECTION RESULTS")
    print("=" * 60)
    print(f"Duration:           {_fmt(total_time)}")
    print(f"Total workflows:    {total}")
    print(f"Succeeded:          {stats['ok']}")
    print(f"Failed (injected):  {stats['failed_expected']}")
    print(f"Failed (unexpected):{stats['failed_unexpected']}")
    print(f"Actual failure %:   {actual_fail_pct:.1f}% (target: {args.failure_pct}%)")
    print(f"Throughput:         {total / total_time:.1f} wf/s")
    print("=" * 60)

    if stats["failed_unexpected"] == 0:
        print("✅ Only injected failures — check Copilot for error-rate signals")
    else:
        print(f"⚠️  {stats['failed_unexpected']} unexpected failures detected")

    completion_rate = stats["ok"] / total * 100 if total > 0 else 0
    if completion_rate < 80:
        print(f"🔴 Completion rate {completion_rate:.0f}% — Copilot should detect CRITICAL")
    elif completion_rate < 95:
        print(f"🟡 Completion rate {completion_rate:.0f}% — Copilot should detect STRESSED")
    else:
        print(f"🟢 Completion rate {completion_rate:.0f}% — may not trigger state change")


if __name__ == "__main__":
    asyncio.run(main())
