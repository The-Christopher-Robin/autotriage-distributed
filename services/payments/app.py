"""Payments service: process payments."""
import os
from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/pay", methods=["POST"])
def pay():
    return jsonify({"payment_id": "pay-1", "status": "completed"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8002))
    app.run(host="0.0.0.0", port=port)
