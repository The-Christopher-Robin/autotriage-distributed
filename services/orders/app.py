"""Orders service: create/query orders; checkout calls payments (VM2)."""
import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
PAYMENTS_URL = os.environ.get("PAYMENTS_URL", "http://localhost:8001")
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", 10))


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/checkout", methods=["POST"])
def checkout():
    """Create order and call payments; return combined result."""
    order = {"order_id": "ord-1", "status": "created"}
    if not PAYMENTS_URL:
        return jsonify({"order": order, "payment": {"status": "error", "message": "PAYMENTS_URL not set"}}), 503
    try:
        r = requests.post(
            f"{PAYMENTS_URL.rstrip('/')}/pay",
            json=request.get_json(silent=True) or {},
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        payment = r.json() if r.content else {"status": "ok"}
        return jsonify({"order": order, "payment": payment})
    except requests.exceptions.Timeout:
        return jsonify({"order": order, "payment": {"status": "error", "message": "payments timeout"}}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"order": order, "payment": {"status": "error", "message": str(e)}}), 502


@app.route("/orders", methods=["POST", "GET"])
def orders():
    if request.method == "POST":
        return jsonify({"order_id": "ord-1", "status": "created"})
    return jsonify({"orders": []})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    app.run(host="0.0.0.0", port=port)
