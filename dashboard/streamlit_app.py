"""Streamlit ops monitoring dashboard for AutoTriage.

Connects to PostgreSQL to display:
  - Real-time service health status
  - Recent alerts and diagnosis history
  - MTTR (mean time to resolution) over time
  - Remediation history
  - Agent leader status
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
import psycopg2.extras
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/autotriage"
)
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
REFRESH_INTERVAL = int(os.environ.get("DASHBOARD_REFRESH_SEC", "15"))


@st.cache_resource
def _get_connection():
    return psycopg2.connect(DATABASE_URL, connect_timeout=5)


def _query(sql: str, params: tuple = ()) -> pd.DataFrame:
    try:
        conn = _get_connection()
        return pd.read_sql_query(sql, conn, params=params)
    except Exception:
        st.cache_resource.clear()
        try:
            conn = _get_connection()
            return pd.read_sql_query(sql, conn, params=params)
        except Exception as exc:
            st.error(f"Database query failed: {exc}")
            return pd.DataFrame()


def _table_exists(table: str) -> bool:
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
            (table,),
        )
        return cur.fetchone()[0]
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="AutoTriage Dashboard", page_icon="🔍", layout="wide")
st.title("AutoTriage Ops Monitoring")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Settings")
    auto_refresh = st.checkbox("Auto-refresh", value=True)
    if auto_refresh:
        st.write(f"Refreshing every {REFRESH_INTERVAL}s")
    st.markdown("---")
    st.subheader("Database")
    st.code(DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL, language=None)

    if st.button("Refresh now"):
        st.cache_resource.clear()
        st.rerun()

# ---------------------------------------------------------------------------
# Service Health
# ---------------------------------------------------------------------------

st.header("Service Health")

try:
    import requests

    health_cols = st.columns(3)
    for idx, (svc, url) in enumerate([
        ("Gateway", os.environ.get("GATEWAY_URL", "http://gateway:8000")),
        ("Orders", os.environ.get("ORDERS_URL", "http://orders:8000")),
        ("Payments", os.environ.get("PAYMENTS_URL", "http://payments:8001")),
    ]):
        with health_cols[idx]:
            try:
                r = requests.get(f"{url}/health", timeout=3)
                data = r.json()
                status = data.get("status", "unknown")
                degraded = data.get("degraded", False)
                if status == "ok" and not degraded:
                    st.metric(svc, "Healthy", delta="OK")
                elif degraded:
                    st.metric(svc, "Degraded", delta="WARN", delta_color="inverse")
                else:
                    st.metric(svc, status.upper(), delta="ERR", delta_color="inverse")
            except Exception:
                st.metric(svc, "Unreachable", delta="DOWN", delta_color="inverse")
except ImportError:
    st.info("Install `requests` for live health checks.")


# ---------------------------------------------------------------------------
# Leader election status
# ---------------------------------------------------------------------------

st.header("Agent Leader Election")

if _table_exists("pg_locks"):
    leader_df = _query(
        """SELECT pid, granted, query_start
           FROM pg_stat_activity
           WHERE query LIKE '%%pg_try_advisory_lock%%'
             AND state = 'active'
           LIMIT 5"""
    )
    if leader_df.empty:
        st.info("No active leader-election queries detected (agent may use FORCE_LEADER).")
    else:
        st.dataframe(leader_df, use_container_width=True)
else:
    st.info("Cannot query pg_locks (connect to the database hosting advisory locks).")


# ---------------------------------------------------------------------------
# Recent Diagnoses
# ---------------------------------------------------------------------------

st.header("Recent Diagnoses")

if _table_exists("diagnosis_log"):
    diag_df = _query(
        "SELECT id, ts, service, severity, rule_result, ml_anomaly_score FROM diagnosis_log ORDER BY ts DESC LIMIT 50"
    )
    if not diag_df.empty:
        severity_map = {"high": "🔴", "medium": "🟠", "low": "🟡", "ok": "🟢"}
        diag_df["sev_icon"] = diag_df["severity"].map(lambda s: severity_map.get(s, "⚪"))
        st.dataframe(
            diag_df[["sev_icon", "ts", "service", "severity", "ml_anomaly_score", "rule_result"]],
            use_container_width=True,
            column_config={"sev_icon": "Status"},
        )

        if "ml_anomaly_score" in diag_df.columns:
            fig_ml = px.scatter(
                diag_df.dropna(subset=["ml_anomaly_score"]),
                x="ts",
                y="ml_anomaly_score",
                color="severity",
                title="ML Anomaly Score Over Time",
                labels={"ts": "Time", "ml_anomaly_score": "Anomaly Score"},
            )
            st.plotly_chart(fig_ml, use_container_width=True)
    else:
        st.info("No diagnoses recorded yet.")
else:
    st.warning("Table `diagnosis_log` does not exist. Run the agent to initialise the schema.")


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

st.header("Recent Alerts")

if _table_exists("alert_log"):
    alert_df = _query("SELECT ts, channel, severity, message FROM alert_log ORDER BY ts DESC LIMIT 30")
    if not alert_df.empty:
        st.dataframe(alert_df, use_container_width=True)

        alert_freq = alert_df.copy()
        alert_freq["hour"] = pd.to_datetime(alert_freq["ts"]).dt.floor("h")
        freq = alert_freq.groupby("hour").size().reset_index(name="count")
        fig_freq = px.bar(freq, x="hour", y="count", title="Alert Frequency (per hour)")
        st.plotly_chart(fig_freq, use_container_width=True)
    else:
        st.info("No alerts recorded yet.")
else:
    st.warning("Table `alert_log` does not exist.")


# ---------------------------------------------------------------------------
# MTTR
# ---------------------------------------------------------------------------

st.header("Mean Time to Resolution (MTTR)")

if _table_exists("remediation_log"):
    rem_df = _query("SELECT ts, service, action_taken, success, duration_ms FROM remediation_log ORDER BY ts DESC LIMIT 200")
    if not rem_df.empty:
        avg_mttr = rem_df["duration_ms"].mean()
        p50_mttr = rem_df["duration_ms"].median()
        p95_mttr = rem_df["duration_ms"].quantile(0.95)

        m1, m2, m3 = st.columns(3)
        m1.metric("Avg MTTR", f"{avg_mttr:.0f} ms")
        m2.metric("p50 MTTR", f"{p50_mttr:.0f} ms")
        m3.metric("p95 MTTR", f"{p95_mttr:.0f} ms")

        fig_mttr = px.line(
            rem_df.sort_values("ts"),
            x="ts",
            y="duration_ms",
            color="service",
            title="Remediation Duration Over Time",
            labels={"ts": "Time", "duration_ms": "Duration (ms)"},
            markers=True,
        )
        st.plotly_chart(fig_mttr, use_container_width=True)

        st.subheader("Remediation History")
        st.dataframe(rem_df, use_container_width=True)
    else:
        st.info("No remediations recorded yet.")
else:
    st.warning("Table `remediation_log` does not exist.")


# ---------------------------------------------------------------------------
# Error & latency from Prometheus (if reachable)
# ---------------------------------------------------------------------------

st.header("Prometheus Metrics (live)")

try:
    import requests as _req

    def _prom_query(q: str) -> list:
        try:
            r = _req.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": q}, timeout=5)
            r.raise_for_status()
            return r.json().get("data", {}).get("result", [])
        except Exception:
            return []

    def _prom_range(q: str, minutes: int = 30, step: str = "30s") -> pd.DataFrame:
        try:
            end = datetime.utcnow()
            start = end - timedelta(minutes=minutes)
            r = _req.get(
                f"{PROMETHEUS_URL}/api/v1/query_range",
                params={
                    "query": q,
                    "start": start.timestamp(),
                    "end": end.timestamp(),
                    "step": step,
                },
                timeout=10,
            )
            r.raise_for_status()
            results = r.json().get("data", {}).get("result", [])
            rows = []
            for res in results:
                job = res.get("metric", {}).get("job", "unknown")
                for ts, val in res.get("values", []):
                    rows.append({"time": pd.Timestamp(ts, unit="s"), "job": job, "value": float(val)})
            return pd.DataFrame(rows)
        except Exception:
            return pd.DataFrame()

    err_df = _prom_range('sum by (job) (rate(flask_http_request_total{status=~"5.."}[5m]))')
    if not err_df.empty:
        fig_err = px.line(err_df, x="time", y="value", color="job", title="Error Rate (5xx) Over Time")
        st.plotly_chart(fig_err, use_container_width=True)
    else:
        st.info("No error rate data from Prometheus.")

    lat_df = _prom_range(
        "histogram_quantile(0.99, sum by (job, le) (rate(flask_http_request_duration_seconds_bucket[5m])))"
    )
    if not lat_df.empty:
        fig_lat = px.line(lat_df, x="time", y="value", color="job", title="Latency p99 Over Time")
        st.plotly_chart(fig_lat, use_container_width=True)
    else:
        st.info("No latency data from Prometheus.")

except ImportError:
    st.info("Install `requests` for Prometheus metrics.")


# ---------------------------------------------------------------------------
# Auto-refresh
# ---------------------------------------------------------------------------

if auto_refresh:
    import time as _time

    _time.sleep(REFRESH_INTERVAL)
    st.rerun()
