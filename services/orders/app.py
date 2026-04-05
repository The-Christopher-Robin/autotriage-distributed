"""Orders service: create/query orders; checkout calls payments (VM2).

Persists orders in PostgreSQL when DATABASE_URL is configured, falling back to
in-memory storage otherwise.
"""
import os
import uuid
import logging

import requests
from flask import Flask, request, jsonify

from common.instrumentation import instrument_flask_app

logger = logging.getLogger(__name__)

app = Flask(__name__)
instrument_flask_app(app, "orders")

PAYMENTS_URL = os.environ.get("PAYMENTS_URL", "http://localhost:8001")
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", 10))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

_pg_conn = None


def _get_db():
    """Return a psycopg2 connection (lazy, reconnect on failure)."""
    global _pg_conn
    if not DATABASE_URL:
        return None
    try:
        if _pg_conn is None or _pg_conn.closed:
            import psycopg2
            _pg_conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
            _pg_conn.autocommit = True
        return _pg_conn
    except Exception as exc:
        logger.warning("DB connection failed: %s", exc)
        _pg_conn = None
        return None


def _init_orders_table():
    conn = _get_db()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id          SERIAL PRIMARY KEY,
                    order_id    TEXT UNIQUE NOT NULL,
                    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
                    customer    TEXT,
                    total_cents INTEGER DEFAULT 0,
                    status      TEXT DEFAULT 'created'
                )
            """)
        logger.info("Orders table ready")
    except Exception as exc:
        logger.warning("Could not create orders table: %s", exc)


def _insert_order(order_id: str, customer: str | None, total_cents: int) -> dict:
    conn = _get_db()
    row = {"order_id": order_id, "status": "created", "customer": customer, "total_cents": total_cents}
    if conn is None:
        return row
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO orders (order_id, customer, total_cents, status)
                   VALUES (%s, %s, %s, 'created')
                   ON CONFLICT (order_id) DO NOTHING
                   RETURNING id, ts""",
                (order_id, customer, total_cents),
            )
            res = cur.fetchone()
            if res:
                row["db_id"] = res[0]
                row["ts"] = str(res[1])
    except Exception as exc:
        logger.warning("insert_order error: %s", exc)
    return row


def _update_order_status(order_id: str, status: str):
    conn = _get_db()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE orders SET status = %s WHERE order_id = %s", (status, order_id))
    except Exception as exc:
        logger.warning("update_order_status error: %s", exc)


def _fetch_orders(limit: int = 50) -> list[dict]:
    conn = _get_db()
    if conn is None:
        return []
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT order_id, ts, customer, total_cents, status FROM orders ORDER BY ts DESC LIMIT %s", (limit,))
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("fetch_orders error: %s", exc)
        return []


with app.app_context():
    _init_orders_table()


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/checkout", methods=["POST"])
def checkout():
    """Create order in PostgreSQL and call payments; return combined result."""
    body = request.get_json(silent=True) or {}
    order_id = f"ord-{uuid.uuid4().hex[:8]}"
    customer = body.get("customer")
    total_cents = int(body.get("total_cents", 0))

    order = _insert_order(order_id, customer, total_cents)

    if not PAYMENTS_URL:
        return jsonify({"order": order, "payment": {"status": "error", "message": "PAYMENTS_URL not set"}}), 503

    try:
        r = requests.post(
            f"{PAYMENTS_URL.rstrip('/')}/pay",
            json=body,
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        payment = r.json() if r.content else {"status": "ok"}
        _update_order_status(order_id, "paid")
        order["status"] = "paid"
        return jsonify({"order": order, "payment": payment})
    except requests.exceptions.Timeout:
        _update_order_status(order_id, "payment_timeout")
        return jsonify({"order": order, "payment": {"status": "error", "message": "payments timeout"}}), 504
    except requests.exceptions.RequestException as e:
        _update_order_status(order_id, "payment_error")
        return jsonify({"order": order, "payment": {"status": "error", "message": str(e)}}), 502


@app.route("/orders", methods=["POST", "GET"])
def orders_endpoint():
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        order_id = f"ord-{uuid.uuid4().hex[:8]}"
        order = _insert_order(order_id, body.get("customer"), int(body.get("total_cents", 0)))
        return jsonify(order)
    return jsonify({"orders": _fetch_orders()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
