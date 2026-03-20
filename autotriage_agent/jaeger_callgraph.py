"""Lightweight Jaeger trace sampling to correlate errors with downstream services."""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _jaeger_base() -> str:
    return os.environ.get("JAEGER_URL", "http://localhost:16686").rstrip("/")


def recent_trace_errors(service: str = "orders", limit: int = 15) -> dict[str, Any]:
    """
    Pull recent traces for a service and count spans tagged with error=true.
    This is a heuristic signal, not a full service graph.
    """
    url = f"{_jaeger_base()}/api/traces"
    try:
        r = requests.get(
            url,
            params={"service": service, "limit": str(limit)},
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        logger.warning("Jaeger trace query failed: %s", e)
        return {"ok": False, "error": str(e), "error_spans": 0, "traces": 0}

    data = payload.get("data") or []
    err_spans = 0
    for tr in data:
        for span in _walk_spans(tr):
            for t in span.get("tags", []) or []:
                if t.get("key") != "error":
                    continue
                v = t.get("value")
                if v is True or str(v).lower() in ("true", "1"):
                    err_spans += 1
                    break
    return {"ok": True, "error_spans": err_spans, "traces": len(data)}


def _walk_spans(trace: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for span in trace.get("spans", []) or []:
        out.append(span)
    return out
