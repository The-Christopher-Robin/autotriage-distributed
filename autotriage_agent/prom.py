"""Prometheus instant queries for autotriage (error rate, latency)."""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return os.environ.get("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")


def query_instant(promql: str) -> list[dict[str, Any]]:
    """Run a PromQL instant query; returns Prometheus `result` vector elements."""
    url = f"{_base_url()}/api/v1/query"
    r = requests.get(url, params={"query": promql}, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")
    return payload.get("data", {}).get("result", [])


def fetch_service_signals() -> dict[str, Any]:
    """Aggregate HTTP error rate and rough latency per scrape `job` label."""
    out: dict[str, Any] = {"errors": {}, "p99_seconds": {}}

    err_q = 'sum by (job) (rate(flask_http_request_total{status=~"5.."}[5m]))'
    try:
        for row in query_instant(err_q):
            job = row.get("metric", {}).get("job", "unknown")
            val = float(row.get("value", [None, "0"])[1])
            out["errors"][job] = val
    except Exception as e:
        logger.warning("Prometheus error-rate query failed: %s", e)

    lat_q = (
        "histogram_quantile(0.99, "
        "sum by (job, le) (rate(flask_http_request_duration_seconds_bucket[5m])))"
    )
    try:
        for row in query_instant(lat_q):
            job = row.get("metric", {}).get("job", "unknown")
            val = float(row.get("value", [None, "0"])[1])
            out["p99_seconds"][job] = val
    except Exception as e:
        logger.warning("Prometheus latency query failed: %s", e)

    return out
