"""Rule-based + ML-augmented diagnosis from Prometheus (+ optional Jaeger hints)."""
from __future__ import annotations

import logging
import os
from typing import Any

from jaeger_callgraph import recent_trace_errors
from ml_model import predict_anomaly
from prom import fetch_service_signals

logger = logging.getLogger(__name__)


def _thresholds() -> tuple[float, float]:
    err = float(os.environ.get("TRIAGE_ERROR_RATE_THRESHOLD", "0.05"))
    p99 = float(os.environ.get("TRIAGE_P99_LATENCY_SEC", "2.0"))
    return err, p99


def run_diagnosis() -> dict[str, Any]:
    """
    Returns a structured finding the remediation layer can act on.

    Combines two signals:
      1. ML transformer model → anomaly probability + anomaly type
      2. Deterministic rules  → specific remediation recommendation

    The ML model detects *that* something is anomalous; the rules determine
    *what* to do about it.
    """
    err_thr, lat_thr = _thresholds()
    signals = fetch_service_signals()
    finding: dict[str, Any] = {
        "severity": "ok",
        "summary": "No SLO breach detected in sampled metrics.",
        "signals": signals,
        "actions": [],
    }

    # --- ML anomaly detection (per monitored service) -----------------------
    ml_predictions: dict[str, dict[str, Any]] = {}
    for svc in ("payments", "orders", "gateway"):
        ml_predictions[svc] = predict_anomaly(signals, svc)

    finding["ml_predictions"] = ml_predictions

    primary_ml = ml_predictions.get("payments", {})
    if primary_ml.get("available"):
        logger.info(
            "ML prediction (payments): score=%.4f type=%s",
            primary_ml.get("anomaly_score", 0),
            primary_ml.get("anomaly_type", "n/a"),
        )

    # --- Rule-based logic (unchanged semantics) -----------------------------
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

    # ML can elevate severity if rules say "ok" but model sees anomaly
    ml_score = primary_ml.get("anomaly_score", 0.0)
    ml_threshold = float(os.environ.get("ML_ANOMALY_THRESHOLD", "0.7"))
    if finding["severity"] == "ok" and primary_ml.get("available") and ml_score >= ml_threshold:
        finding["severity"] = "medium"
        finding["summary"] = (
            f"ML model detects anomaly (score={ml_score:.3f}, "
            f"type={primary_ml.get('anomaly_type', 'unknown')}); rules show no SLO breach yet."
        )
        finding["actions"].append({"type": "ml_anomaly_detected", "reason": "ml_high_score"})

    # --- Jaeger trace errors ------------------------------------------------
    jaeger_hint = recent_trace_errors("orders")
    finding["jaeger"] = jaeger_hint
    if finding["severity"] == "ok" and jaeger_hint.get("ok") and jaeger_hint.get("error_spans", 0) > 0:
        finding["severity"] = "low"
        finding["summary"] = "Metrics quiet but Jaeger shows error spans; continue sampling."
        finding["actions"].append({"type": "collect_more_traces", "reason": "jaeger_errors"})

    logger.info("Diagnosis: %s", finding["summary"])
    return finding
