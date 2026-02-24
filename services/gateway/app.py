"""Gateway service: entry point, routes to orders only (orders calls payments on VM2)."""
import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
ORDERS_URL = os.environ.get("ORDERS_URL", "http://localhost:8000")
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", 10))


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/checkout", methods=["POST"])
def checkout():
    """Call orders (VM2); orders calls payments (VM2) internally. Return orders response."""
    if not ORDERS_URL:
        return jsonify({"status": "error", "message": "ORDERS_URL not configured"}), 503
    try:
        r = requests.post(
            f"{ORDERS_URL.rstrip('/')}/checkout",
            json=request.get_json(silent=True) or {},
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return jsonify(r.json() if r.content else {"status": "ok"})
    except requests.exceptions.Timeout:
        return jsonify({"status": "error", "message": "orders timeout"}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"status": "error", "message": str(e)}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
