#!/usr/bin/env python3
"""
Load comparison: Hostinger (coral, MariaDB) vs Hetzner (PG).

Tests 4 endpoints under increasing concurrency and reports throughput +
percentile latency. Designed for fair side-by-side comparison: same
endpoint, same auth, run sequentially within the same script invocation
so server-side state is comparable.

Usage:
    pip install httpx
    export COMPARE_TOKEN='44|...your bearer token...'
    python3 tests/performance/load_compare_servers.py

Environment:
    COMPARE_TOKEN          Bearer token (required)
    COMPARE_DURATION_S     Duration per concurrency level (default 8)
    COMPARE_CONCURRENCIES  Comma-separated list (default 1,5,10,25,50)

Output: text table on stdout; results also saved to /tmp/load_compare_<ts>.txt

This is NOT a phpunit test — it makes real HTTP calls against production
servers. Run manually before/after infrastructure changes (e.g. deploys,
DB migrations) to verify performance regression/improvement.

Reference: docs/proposal/MULTI_SHARD_ARCHITECTURE_R2_SHARED_STORAGE_PROPOSAL_2026-04-15.md
section "Misurazioni di carico empiriche".
"""
import asyncio
import os
import sys
import time
from typing import List, Tuple

try:
    import httpx
except ImportError:
    print("ERROR: pip install httpx", file=sys.stderr)
    sys.exit(1)

TOKEN = os.environ.get("COMPARE_TOKEN", "").strip()
if not TOKEN:
    print("ERROR: set COMPARE_TOKEN env var", file=sys.stderr)
    sys.exit(1)

DURATION = int(os.environ.get("COMPARE_DURATION_S", "8"))
CONCURRENCY_LEVELS = [int(c.strip()) for c in os.environ.get(
    "COMPARE_CONCURRENCIES", "1,5,10,25,50").split(",")]

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

SERVERS = {
    "coral":   "https://coral-shark-984693.hostingersite.com",
    "hetzner": "https://new.caliwebapp.com",
}

ENDPOINTS = [
    ("LIGHT  health         ", "GET",  "/api/discovery/health"),
    ("MED    auth/validate  ", "POST", "/api/auth/validate"),
    ("HEAVY  library-hash   ", "GET",  "/api/sync/v5/library-hash?library_id=2"),
    ("HEAVY  merkle-root    ", "GET",  "/api/sync/v5/merkle-root?library_id=2"),
]


async def worker(client, method, url, results, end_time):
    while time.monotonic() < end_time:
        t0 = time.monotonic()
        try:
            r = await client.request(method, url, timeout=30.0)
            dt = (time.monotonic() - t0) * 1000  # ms
            results.append((dt, r.status_code))
        except Exception:
            dt = (time.monotonic() - t0) * 1000
            results.append((dt, -1))


async def run_load(base_url, method, path, concurrency, duration) -> List[Tuple[float, int]]:
    results: List[Tuple[float, int]] = []
    end_time = time.monotonic() + duration
    limits = httpx.Limits(max_connections=concurrency * 2,
                          max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base_url, headers=HEADERS,
                                  limits=limits, verify=True) as client:
        # Warmup: 1 sequential request to establish connection + cache
        try:
            await client.request(method, path, timeout=10.0)
        except Exception:
            pass
        tasks = [asyncio.create_task(worker(client, method, path, results, end_time))
                 for _ in range(concurrency)]
        await asyncio.gather(*tasks, return_exceptions=True)
    return results


def percentile(data, p):
    if not data:
        return 0
    s = sorted(data)
    k = int(len(s) * p / 100)
    return s[min(k, len(s) - 1)]


def fmt(results, duration):
    if not results:
        return "no data"
    times_ok = [t for t, c in results if 200 <= c < 300]
    n = len(results)
    n_ok = len(times_ok)
    n_4xx = sum(1 for _, c in results if 400 <= c < 500)
    n_5xx = sum(1 for _, c in results if c >= 500)
    n_net = sum(1 for _, c in results if c < 0)
    rps = n / duration
    if not times_ok:
        return f"n={n:5d} ALL FAILED 5xx={n_5xx} net_err={n_net}"
    p50 = percentile(times_ok, 50)
    p95 = percentile(times_ok, 95)
    p99 = percentile(times_ok, 99)
    return (f"n={n:5d} rps={rps:5.1f} p50={p50:6.0f}ms p95={p95:6.0f}ms "
            f"p99={p99:6.0f}ms ok={n_ok} 4xx={n_4xx} 5xx={n_5xx} net_err={n_net}")


async def main():
    print(f"\n{'='*100}")
    print(f"LOAD COMPARISON: coral (Hostinger MariaDB) vs hetzner (PG)")
    print(f"Duration per level: {DURATION}s | Concurrency: {CONCURRENCY_LEVELS}")
    print(f"{'='*100}\n")

    for label, method, path in ENDPOINTS:
        print(f"\n### {label} | {method} {path}")
        print(f"{'concurrency':<12} {'server':<10} metrics")
        print(f"{'-'*100}")
        for c in CONCURRENCY_LEVELS:
            for srv_name, srv_url in SERVERS.items():
                results = await run_load(srv_url, method, path, c, DURATION)
                line = fmt(results, DURATION)
                print(f"  c={c:<8} {srv_name:<10} {line}")
                # Brief cooldown so coral and hetzner don't interfere
                await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
