"""Auto-triage agent: leader election, Prometheus/Jaeger diagnosis, optional remediation."""
from __future__ import annotations

import json
import logging
import os
import sys
import time

from alert_router import route_alert
from diagnose import run_diagnosis
from leader import LeaderSession
from models import init_db, insert_diagnosis, insert_remediation
from remediate import maybe_remediate

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("autotriage_agent")


def _record_diagnosis(diagnosis: dict) -> None:
    """Persist a diagnosis to PostgreSQL (best-effort)."""
    ml = diagnosis.get("ml_predictions", {}).get("payments", {})
    insert_diagnosis(
        service=_primary_service(diagnosis),
        diagnosis=diagnosis,
        ml_anomaly_score=ml.get("anomaly_score"),
        rule_result=diagnosis.get("summary", ""),
        severity=diagnosis.get("severity", "ok"),
    )


def _primary_service(diagnosis: dict) -> str:
    for svc in ("payments", "orders", "gateway"):
        if svc in diagnosis.get("summary", "").lower():
            return svc
    return "unknown"


def _timed_remediate(diagnosis: dict) -> None:
    """Run remediation and record duration for MTTR tracking."""
    if diagnosis.get("severity") in ("ok", "low"):
        return

    start = time.monotonic()
    maybe_remediate(diagnosis)
    elapsed_ms = (time.monotonic() - start) * 1000.0

    for action in diagnosis.get("actions", []):
        insert_remediation(
            service=_primary_service(diagnosis),
            action_taken=action.get("type", "unknown"),
            success=True,
            duration_ms=round(elapsed_ms, 2),
        )
    logger.info("Remediation completed in %.1f ms", elapsed_ms)


def main() -> None:
    interval = int(os.environ.get("AGENT_INTERVAL_SEC", "30"))
    logger.info("autotriage_agent starting (interval=%ss)", interval)

    init_db()

    while True:
        session = LeaderSession()
        if session.acquire():
            try:
                diagnosis = run_diagnosis()
                logger.info("diagnosis: %s", json.dumps(diagnosis, default=str)[:2000])

                _record_diagnosis(diagnosis)

                ml_pred = diagnosis.get("ml_predictions", {}).get("payments")
                route_alert(diagnosis, ml_prediction=ml_pred)

                _timed_remediate(diagnosis)
            finally:
                session.release()
        else:
            logger.debug("Not leader this cycle; sleeping")

        time.sleep(interval)


if __name__ == "__main__":
    main()
