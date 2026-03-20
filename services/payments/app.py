"""Payments service: process payments with optional simulated degradation (for autotriage demos)."""
import os
import random
import time
from flask import Flask, request, jsonify

from common.instrumentation import instrument_flask_app

app = Flask(__name__)
instrument_flask_app(app, "payments")

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

# Simulated incident knobs (adjusted via /admin/* for autotriage experiments)
_state = {
    "delay_ms": int(os.environ.get("PAYMENTS_DELAY_MS", "0")),
    "error_rate": float(os.environ.get("PAYMENTS_ERROR_RATE", "0")),
}


def _auth_ok() -> bool:
    if not ADMIN_TOKEN:
        return False
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {ADMIN_TOKEN}"


@app.route("/health")
def health():
    return jsonify({"status": "ok", "degraded": _state["delay_ms"] > 0 or _state["error_rate"] > 0})


@app.route("/pay", methods=["POST"])
def pay():
    if _state["delay_ms"] > 0:
        time.sleep(_state["delay_ms"] / 1000.0)
    if _state["error_rate"] > 0 and random.random() < _state["error_rate"]:
        return jsonify({"payment_id": "pay-fail", "status": "error", "message": "simulated payment failure"}), 503
    return jsonify({"payment_id": "pay-1", "status": "completed"})


@app.route("/admin/status", methods=["GET"])
def admin_status():
    if not _auth_ok():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(_state)


@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    """Clear artificial latency and error injection (autotriage remediation)."""
    if not _auth_ok():
        return jsonify({"error": "unauthorized"}), 401
    _state["delay_ms"] = 0
    _state["error_rate"] = 0.0
    return jsonify({"ok": True, "state": _state})


@app.route("/admin/degrade", methods=["POST"])
def admin_degrade():
    """Inject latency and/or stochastic errors (chaos / professor demo)."""
    if not _auth_ok():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    if "delay_ms" in body:
        _state["delay_ms"] = max(0, int(body["delay_ms"]))
    if "error_rate" in body:
        _state["error_rate"] = min(1.0, max(0.0, float(body["error_rate"])))
    return jsonify({"ok": True, "state": _state})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    app.run(host="0.0.0.0", port=port)
