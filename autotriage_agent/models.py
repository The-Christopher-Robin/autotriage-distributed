"""PostgreSQL schema and helpers for diagnosis, remediation, and alert logs.

Uses raw psycopg2 (consistent with the existing leader-election code) rather
than an ORM, so there are no extra runtime dependencies beyond psycopg2-binary.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS diagnosis_log (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    service         TEXT,
    diagnosis_json  JSONB,
    ml_anomaly_score FLOAT,
    rule_result     TEXT,
    severity        TEXT
);

CREATE TABLE IF NOT EXISTS remediation_log (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    service         TEXT,
    action_taken    TEXT,
    success         BOOLEAN,
    duration_ms     FLOAT
);

CREATE TABLE IF NOT EXISTS alert_log (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel         TEXT,
    severity        TEXT,
    message         TEXT,
    dedup_key       TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    customer        TEXT,
    total_cents     INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'created'
);
"""


def _dsn() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _connect():
    dsn = _dsn()
    if not dsn:
        return None
    try:
        return psycopg2.connect(dsn, connect_timeout=5)
    except Exception as exc:
        logger.warning("DB connect failed: %s", exc)
        return None


def init_db() -> bool:
    """Create tables if they don't exist. Returns True on success."""
    conn = _connect()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
        logger.info("Database schema initialised")
        return True
    except Exception as exc:
        logger.warning("init_db error: %s", exc)
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Diagnosis log
# ---------------------------------------------------------------------------

def insert_diagnosis(
    service: str,
    diagnosis: dict[str, Any],
    ml_anomaly_score: float | None,
    rule_result: str,
    severity: str,
) -> int | None:
    conn = _connect()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO diagnosis_log
                       (service, diagnosis_json, ml_anomaly_score, rule_result, severity)
                       VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                    (service, json.dumps(diagnosis, default=str), ml_anomaly_score, rule_result, severity),
                )
                return cur.fetchone()[0]
    except Exception as exc:
        logger.warning("insert_diagnosis error: %s", exc)
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Remediation log
# ---------------------------------------------------------------------------

def insert_remediation(
    service: str,
    action_taken: str,
    success: bool,
    duration_ms: float,
) -> int | None:
    conn = _connect()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO remediation_log
                       (service, action_taken, success, duration_ms)
                       VALUES (%s, %s, %s, %s) RETURNING id""",
                    (service, action_taken, success, duration_ms),
                )
                return cur.fetchone()[0]
    except Exception as exc:
        logger.warning("insert_remediation error: %s", exc)
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Alert log
# ---------------------------------------------------------------------------

def insert_alert(channel: str, severity: str, message: str, dedup_key: str) -> int | None:
    conn = _connect()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO alert_log (channel, severity, message, dedup_key)
                       VALUES (%s, %s, %s, %s) RETURNING id""",
                    (channel, severity, message, dedup_key),
                )
                return cur.fetchone()[0]
    except Exception as exc:
        logger.warning("insert_alert error: %s", exc)
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Queries (used by Streamlit dashboard)
# ---------------------------------------------------------------------------

def fetch_recent_diagnoses(limit: int = 50) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM diagnosis_log ORDER BY ts DESC LIMIT %s", (limit,)
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("fetch_recent_diagnoses error: %s", exc)
        return []
    finally:
        conn.close()


def fetch_recent_remediations(limit: int = 50) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM remediation_log ORDER BY ts DESC LIMIT %s", (limit,)
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("fetch_recent_remediations error: %s", exc)
        return []
    finally:
        conn.close()


def fetch_recent_alerts(limit: int = 50) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM alert_log ORDER BY ts DESC LIMIT %s", (limit,)
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("fetch_recent_alerts error: %s", exc)
        return []
    finally:
        conn.close()


def fetch_mttr_stats() -> list[dict[str, Any]]:
    """Return remediation durations for MTTR charting."""
    conn = _connect()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT ts, service, action_taken, success, duration_ms
                   FROM remediation_log
                   ORDER BY ts DESC LIMIT 200"""
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("fetch_mttr_stats error: %s", exc)
        return []
    finally:
        conn.close()
