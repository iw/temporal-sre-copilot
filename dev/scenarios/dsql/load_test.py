"""Extended load test for Temporal with Aurora DSQL persistence.

Runs for a configurable duration (default 45 min) to validate connection
pool stability and refresher behavior. With DSQL_CONN_REFRESH_INTERVAL=8m,
expect ~5 refresh cycles during the default run.

Key things to observe:
- Connection pool stability (dsql_pool_open should stay at max)
- Refresh cycles in logs ("DSQL connection refresh triggered")
- No workflow failures during refresh windows
- dsql_db_closed_max_idle_time_total should stay at 0

Usage (from repo root):
    uv run python dev/scenarios/dsql/load_test.py
    uv run python dev/scenarios/dsql/load_test.py --duration 10 --rate 5
"""

from __future__ import annotations

import argparse
import asyncio
import time
import uuid
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker


@activity.defn
async def say_hello(name: str) -> str:
    await asyncio.sleep(0.1)
    return f"Hello, {name}!"


@workflow.defn
class GreetingWorkflow:
    @workflow.run
    async def run(self, name: str) -> str:
        return await workflow.execute_activity(
            say_hello, name, start_to_close_timeout=timedelta(seconds=30)
        )


def _fmt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


async def main() -> None:
    parser = argparse.ArgumentParser(description="DSQL connection pool soak test")
    parser.add_argument("--address", default="localhost:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--duration", type=int, default=45, help="minutes (default: 45)")
    parser.add_argument("--rate", type=float, default=2.0, help="wf/s (default: 2.0)")
    parser.add_argument("--concurrency", type=int, default=10, help="max concurrent (default: 10)")
    parser.add_argument(
        "--report-interval", type=int, default=60, help="progress report sec (default: 60)"
    )
    args = parser.parse_args()

    duration_sec = args.duration * 60

    print("=" * 70)
    print("🚀 DSQL CONNECTION POOL SOAK TEST")
    print("=" * 70)
    print(f"Address:         {args.address}")
    print(f"Duration:        {args.duration} minutes")
    print(f"Target rate:     {args.rate} wf/s")
    print(f"Concurrency:     {args.concurrency}")
    print(f"Report interval: {args.report_interval}s")
    print()
    print(f"Expected refresh cycles (8m interval): ~{args.duration // 8}")
    print("Watch for: 'DSQL connection refresh triggered' in service logs")
    print("=" * 70)

    client = await Client.connect(args.address, namespace=args.namespace)

    total_success = 0
    total_errors = 0
    interval_success = 0
    interval_errors = 0
    interval_durations: list[float] = []
    all_durations: list[float] = []
    error_samples: list[str] = []

    semaphore = asyncio.Semaphore(args.concurrency)

    async def run_one(n: int) -> tuple[bool, float, str | None]:
        async with semaphore:
            wf_id = f"load-{uuid.uuid4().hex[:8]}-{n}"
            try:
                t0 = time.time()
                await client.execute_workflow(
                    GreetingWorkflow.run,
                    f"User-{n}",
                    id=wf_id,
                    task_queue="load-test-queue",
                )
                return True, time.time() - t0, None
            except Exception as e:
                return False, 0.0, str(e)[:200]

    async with Worker(
        client,
        task_queue="load-test-queue",
        workflows=[GreetingWorkflow],
        activities=[say_hello],
        max_concurrent_activities=args.concurrency * 2,
        max_concurrent_workflow_tasks=args.concurrency * 2,
    ):
        t_start = time.time()
        last_report = t_start
        n = 0
        pending: set[asyncio.Task[tuple[bool, float, str | None]]] = set()
        delay = 1.0 / args.rate

        print(f"\n⏱️  Started at {time.strftime('%H:%M:%S')}")
        print("-" * 70)

        while time.time() - t_start < duration_sec:
            n += 1
            task = asyncio.create_task(run_one(n))
            pending.add(task)

            done = {t for t in pending if t.done()}
            for t in done:
                pending.discard(t)
                try:
                    success, dur, error = t.result()
                    if success:
                        total_success += 1
                        interval_success += 1
                        interval_durations.append(dur)
                        all_durations.append(dur)
                    else:
                        total_errors += 1
                        interval_errors += 1
                        if error and len(error_samples) < 10:
                            error_samples.append(error)
                except Exception as e:
                    total_errors += 1
                    interval_errors += 1
                    if len(error_samples) < 10:
                        error_samples.append(str(e)[:200])

            now = time.time()
            if now - last_report >= args.report_interval:
                elapsed = now - t_start
                remaining = duration_sec - elapsed
                rate = interval_success / args.report_interval if args.report_interval > 0 else 0
                avg = sum(interval_durations) / len(interval_durations) if interval_durations else 0
                mx = max(interval_durations) if interval_durations else 0
                print(
                    f"[{_fmt(elapsed)}] ✅ {interval_success:4d} ok | "
                    f"❌ {interval_errors:2d} err | "
                    f"⚡ {rate:.1f}/s | 📊 avg={avg:.2f}s max={mx:.2f}s | "
                    f"⏳ {_fmt(remaining)} left"
                )
                interval_success = 0
                interval_errors = 0
                interval_durations = []
                last_report = now

            await asyncio.sleep(delay)

        if pending:
            print(f"\n⏳ Waiting for {len(pending)} remaining workflows...")
            results = await asyncio.gather(*pending, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    total_errors += 1
                else:
                    success, dur, _ = r
                    if success:
                        total_success += 1
                        all_durations.append(dur)
                    else:
                        total_errors += 1

        total_time = time.time() - t_start

    total = total_success + total_errors

    print("\n" + "=" * 70)
    print("📊 SOAK TEST RESULTS")
    print("=" * 70)
    print(f"Duration:        {_fmt(total_time)} ({total_time:.1f}s)")
    print(f"Total workflows: {total}")
    print(f"Successful:      {total_success}")
    print(f"Failed:          {total_errors}")
    print(f"Success rate:    {100 * total_success / total:.2f}%" if total > 0 else "N/A")
    print(f"Throughput:      {total / total_time:.2f} wf/s")

    if all_durations:
        s = sorted(all_durations)
        print("\nLatency:")
        print(f"  p50: {s[len(s) // 2]:.3f}s")
        print(f"  p95: {s[int(len(s) * 0.95)]:.3f}s")
        print(f"  p99: {s[int(len(s) * 0.99)]:.3f}s")
        print(f"  max: {s[-1]:.3f}s")
        print(f"  avg: {sum(s) / len(s):.3f}s")

    if error_samples:
        print(f"\n❌ Error samples ({len(error_samples)} shown, {total_errors} total):")
        for i, err in enumerate(error_samples[:5]):
            print(f"  {i + 1}. {err[:100]}")

    print("\n" + "=" * 70)
    if total_errors == 0:
        print("✅ SOAK TEST PASSED — No errors during connection refresh cycles")
    else:
        print(f"⚠️  SOAK TEST COMPLETED WITH {total_errors} ERRORS")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
