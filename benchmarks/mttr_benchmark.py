#!/usr/bin/env python3
"""MTTR (Mean Time to Resolution) benchmark.

Workflow per iteration:
  1. Start a background load generator.
  2. Inject a fault on payments via /admin/degrade.
  3. Wait for the autotriage agent to detect and remediate (poll /admin/status).
  4. Measure elapsed time from injection to resolution.
  5. Reset and repeat.

Results are written to stdout as JSON.

Usage:
    python mttr_benchmark.py --gateway http://VM1:8000 \\
                             --payments-admin http://VM2:8001 \\
                             --admin-token change-me-class-demo \\
                             --iterations 5
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone

import requests


def _inject_fault(admin_url: str, token: str, delay_ms: int = 800, error_rate: float = 0.35) -> bool:
    try:
        r = requests.post(
            f"{admin_url}/admin/degrade",
            json={"delay_ms": delay_ms, "error_rate": error_rate},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        return r.ok
    except Exception as exc:
        print(f"[ERROR] inject_fault: {exc}", file=sys.stderr)
        return False


def _check_healthy(admin_url: str, token: str) -> bool:
    try:
        r = requests.get(
            f"{admin_url}/admin/status",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if not r.ok:
            return False
        state = r.json()
        return state.get("delay_ms", 0) == 0 and state.get("error_rate", 0) == 0
    except Exception:
        return False


def _reset(admin_url: str, token: str) -> None:
    try:
        requests.post(
            f"{admin_url}/admin/reset",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
    except Exception:
        pass


def _send_traffic(gateway_url: str, duration_sec: int = 5) -> None:
    """Send a burst of checkout requests to keep metrics flowing."""
    end = time.time() + duration_sec
    while time.time() < end:
        try:
            requests.post(f"{gateway_url}/checkout", json={}, timeout=5)
        except Exception:
            pass
        time.sleep(0.1)


def run_iteration(
    gateway_url: str,
    admin_url: str,
    token: str,
    max_wait_sec: int = 180,
    poll_interval: float = 2.0,
) -> dict:
    """Run one inject → detect → remediate cycle and return timing data."""
    _reset(admin_url, token)
    time.sleep(2)

    inject_time = time.monotonic()
    inject_ts = datetime.now(timezone.utc).isoformat()

    if not _inject_fault(admin_url, token):
        return {"success": False, "error": "injection_failed", "inject_ts": inject_ts}

    _send_traffic(gateway_url, duration_sec=5)

    waited = 0.0
    while waited < max_wait_sec:
        if _check_healthy(admin_url, token):
            resolve_time = time.monotonic()
            tttr_ms = (resolve_time - inject_time) * 1000
            return {
                "success": True,
                "inject_ts": inject_ts,
                "resolve_ts": datetime.now(timezone.utc).isoformat(),
                "tttr_ms": round(tttr_ms, 1),
            }
        _send_traffic(gateway_url, duration_sec=int(poll_interval))
        waited += poll_interval

    return {"success": False, "error": "timeout", "inject_ts": inject_ts, "waited_sec": max_wait_sec}


def main() -> None:
    parser = argparse.ArgumentParser(description="MTTR benchmark for AutoTriage")
    parser.add_argument("--gateway", default="http://localhost:8000", help="Gateway URL")
    parser.add_argument("--payments-admin", default="http://localhost:8001", help="Payments admin URL")
    parser.add_argument("--admin-token", default="change-me-class-demo", help="Admin bearer token")
    parser.add_argument("--iterations", type=int, default=5, help="Number of inject/resolve cycles")
    parser.add_argument("--max-wait", type=int, default=180, help="Max seconds to wait for resolution per iteration")
    parser.add_argument("--output", default="", help="Output JSON file (default: stdout)")
    args = parser.parse_args()

    results = []
    for i in range(1, args.iterations + 1):
        print(f"[{i}/{args.iterations}] Running iteration ...", file=sys.stderr)
        result = run_iteration(args.gateway, args.payments_admin, args.admin_token, args.max_wait)
        result["iteration"] = i
        results.append(result)
        print(f"  -> {'OK' if result['success'] else 'FAIL'}: {result}", file=sys.stderr)
        time.sleep(5)

    success_times = [r["tttr_ms"] for r in results if r.get("success")]
    summary = {
        "iterations": len(results),
        "successful": len(success_times),
        "failed": len(results) - len(success_times),
        "results": results,
    }
    if success_times:
        summary["mttr_mean_ms"] = round(statistics.mean(success_times), 1)
        summary["mttr_median_ms"] = round(statistics.median(success_times), 1)
        summary["mttr_stdev_ms"] = round(statistics.stdev(success_times), 1) if len(success_times) > 1 else 0.0
        summary["mttr_min_ms"] = round(min(success_times), 1)
        summary["mttr_max_ms"] = round(max(success_times), 1)

    output = json.dumps(summary, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output + "\n")
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
