"""Rule-based diagnosis from Prometheus (+ optional Jaeger hints)."""
from __future__ import annotations

import logging
import os
from typing import Any

from jaeger_callgraph import recent_trace_errors
from prom import fetch_service_signals

logger = logging.getLogger(__name__)


def _thresholds() -> tuple[float, float]:
    err = float(os.environ.get("TRIAGE_ERROR_RATE_THRESHOLD", "0.05"))
    p99 = float(os.environ.get("TRIAGE_P99_LATENCY_SEC", "2.0"))
    return err, p99


def run_diagnosis() -> dict[str, Any]:
    """
    Returns a structured finding the remediation layer can act on.
    Designed as a policy engine; an LLM could consume the same JSON later.
    """
    err_thr, lat_thr = _thresholds()
    signals = fetch_service_signals()
    finding: dict[str, Any] = {
        "severity": "ok",
        "summary": "No SLO breach detected in sampled metrics.",
        "signals": signals,
        "actions": [],
    }

    payments_err = signals.get("errors", {}).get("payments", 0.0)
    orders_err = signals.get("errors", {}).get("orders", 0.0)
    gateway_err = signals.get("errors", {}).get("gateway", 0.0)

    payments_p99 = signals.get("p99_seconds", {}).get("payments")
    orders_p99 = signals.get("p99_seconds", {}).get("orders")

    if payments_err >= err_thr or (payments_p99 is not None and payments_p99 >= lat_thr):
        finding["severity"] = "high"
        finding["summary"] = (
            "Payments tier shows elevated 5xx rate or high p99 latency; "
            "likely bottleneck or injected fault."
        )
        finding["actions"].append(
            {"type": "reset_payments_simulation", "reason": "payments_slo_breach"}
        )

    elif orders_err >= err_thr or (orders_p99 is not None and orders_p99 >= lat_thr):
        finding["severity"] = "medium"
        finding["summary"] = (
            "Orders tier degraded before payments; inspect cross-service timeouts."
        )
        finding["actions"].append({"type": "inspect_network", "reason": "orders_slo_breach"})

    elif gateway_err >= err_thr:
        finding["severity"] = "medium"
        finding["summary"] = "Gateway errors elevated; client-facing failures or upstream outage."
        finding["actions"].append({"type": "inspect_gateway_upstream", "reason": "gateway_errors"})

    jaeger_hint = recent_trace_errors("orders")
    finding["jaeger"] = jaeger_hint
    if finding["severity"] == "ok" and jaeger_hint.get("ok") and jaeger_hint.get("error_spans", 0) > 0:
        finding["severity"] = "low"
        finding["summary"] = "Metrics quiet but Jaeger shows error spans; continue sampling."
        finding["actions"].append({"type": "collect_more_traces", "reason": "jaeger_errors"})

    logger.info("Diagnosis: %s", finding["summary"])
    return finding
