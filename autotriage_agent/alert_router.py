"""Route diagnosis alerts to configured channels with deduplication.

Supported channels (enabled via environment variables):
  - Webhook:  ALERT_WEBHOOK_URL   (generic HTTP POST)
  - Slack:    ALERT_SLACK_URL     (Slack incoming-webhook URL)
  - Log file: ALERT_LOG_FILE      (append JSON lines)
  - Database: ALERT_DB_ENABLED=1  (store in PostgreSQL alert_log)

Deduplication: identical alerts within ALERT_COOLDOWN_SEC (default 120 s) are
suppressed so the same fault doesn't flood every channel.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

import models

logger = logging.getLogger(__name__)

_last_fired: dict[str, float] = {}


def _cooldown() -> int:
    return int(os.environ.get("ALERT_COOLDOWN_SEC", "120"))


def _dedup_key(alert: dict[str, Any]) -> str:
    raw = f"{alert.get('service','')}__{alert.get('severity','')}__{alert.get('summary','')}"
    return hashlib.md5(raw.encode()).hexdigest()


def _should_fire(key: str) -> bool:
    now = time.time()
    last = _last_fired.get(key, 0.0)
    if now - last < _cooldown():
        return False
    _last_fired[key] = now
    return True


def build_alert(diagnosis: dict[str, Any], ml_prediction: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a structured alert payload from a diagnosis dict."""
    service = "unknown"
    for svc in ("payments", "orders", "gateway"):
        if svc in diagnosis.get("summary", "").lower():
            service = svc
            break

    alert = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity": diagnosis.get("severity", "ok"),
        "service": service,
        "summary": diagnosis.get("summary", ""),
        "recommended_actions": [a.get("type", "") for a in diagnosis.get("actions", [])],
    }
    if ml_prediction and ml_prediction.get("available"):
        alert["ml_anomaly_score"] = ml_prediction.get("anomaly_score", 0.0)
        alert["ml_anomaly_type"] = ml_prediction.get("anomaly_type", "normal")
    return alert


# ---------------------------------------------------------------------------
# Channel senders
# ---------------------------------------------------------------------------

def _send_webhook(alert: dict[str, Any]) -> None:
    url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return
    try:
        r = requests.post(url, json=alert, timeout=10)
        logger.info("Webhook alert sent (%s)", r.status_code)
        models.insert_alert("webhook", alert["severity"], json.dumps(alert, default=str), _dedup_key(alert))
    except Exception as exc:
        logger.warning("Webhook alert failed: %s", exc)


def _send_slack(alert: dict[str, Any]) -> None:
    url = os.environ.get("ALERT_SLACK_URL", "").strip()
    if not url:
        return
    text = (
        f":rotating_light: *AutoTriage Alert* [{alert['severity'].upper()}]\n"
        f"*Service:* {alert['service']}\n"
        f"*Summary:* {alert['summary']}\n"
        f"*Actions:* {', '.join(alert.get('recommended_actions', []))}\n"
        f"*Time:* {alert['timestamp']}"
    )
    if alert.get("ml_anomaly_score") is not None:
        text += f"\n*ML Score:* {alert['ml_anomaly_score']:.3f} ({alert.get('ml_anomaly_type', 'n/a')})"
    try:
        r = requests.post(url, json={"text": text}, timeout=10)
        logger.info("Slack alert sent (%s)", r.status_code)
        models.insert_alert("slack", alert["severity"], text, _dedup_key(alert))
    except Exception as exc:
        logger.warning("Slack alert failed: %s", exc)


def _write_log_file(alert: dict[str, Any]) -> None:
    path = os.environ.get("ALERT_LOG_FILE", "").strip()
    if not path:
        return
    try:
        with open(path, "a") as f:
            f.write(json.dumps(alert, default=str) + "\n")
        logger.info("Alert written to %s", path)
        models.insert_alert("logfile", alert["severity"], json.dumps(alert, default=str), _dedup_key(alert))
    except Exception as exc:
        logger.warning("Log-file alert failed: %s", exc)


def _store_db(alert: dict[str, Any]) -> None:
    enabled = os.environ.get("ALERT_DB_ENABLED", "").lower() in ("1", "true", "yes")
    if not enabled:
        return
    models.insert_alert("db", alert["severity"], json.dumps(alert, default=str), _dedup_key(alert))
    logger.info("Alert stored in database")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route_alert(diagnosis: dict[str, Any], ml_prediction: dict[str, Any] | None = None) -> None:
    """Build an alert from the diagnosis and send to all configured channels.

    Alerts with severity 'ok' are silently dropped. Duplicate alerts within
    the cooldown window are suppressed.
    """
    if diagnosis.get("severity") == "ok":
        return

    alert = build_alert(diagnosis, ml_prediction)
    key = _dedup_key(alert)

    if not _should_fire(key):
        logger.debug("Alert suppressed (cooldown): %s", key)
        return

    logger.info("Routing alert [%s] for %s: %s", alert["severity"], alert["service"], alert["summary"])

    _send_webhook(alert)
    _send_slack(alert)
    _write_log_file(alert)
    _store_db(alert)
