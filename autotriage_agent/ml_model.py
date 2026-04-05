"""PyTorch transformer-based anomaly classifier for metric time series.

Processes sliding windows of [error_rate, latency_p99, request_rate] and
outputs an anomaly probability plus an anomaly-type classification.
"""
from __future__ import annotations

import logging
import os
from collections import deque
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

WINDOW_SIZE = 30
NUM_FEATURES = 3  # error_rate, latency_p99, request_rate
ANOMALY_TYPES = ["normal", "latency_spike", "error_burst", "throughput_drop"]

_model_instance = None
_feature_buffer: dict[str, deque] = {}

try:
    import torch
    import torch.nn as nn

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not installed; ML anomaly detection disabled (rule-based only)")


def _get_or_create_buffer(service: str) -> deque:
    if service not in _feature_buffer:
        _feature_buffer[service] = deque(maxlen=WINDOW_SIZE)
    return _feature_buffer[service]


# ---------------------------------------------------------------------------
# Model definition
# ---------------------------------------------------------------------------
if TORCH_AVAILABLE:

    class TimeSeriesTransformer(nn.Module):
        """Lightweight transformer encoder for metric anomaly detection."""

        def __init__(
            self,
            d_model: int = 64,
            nhead: int = 4,
            num_layers: int = 2,
            dim_feedforward: int = 128,
        ):
            super().__init__()
            self.input_proj = nn.Linear(NUM_FEATURES, d_model)
            self.pos_encoding = nn.Parameter(torch.randn(1, WINDOW_SIZE, d_model) * 0.02)

            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=nhead,
                dim_feedforward=dim_feedforward,
                batch_first=True,
                dropout=0.1,
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)

            self.anomaly_head = nn.Sequential(
                nn.Linear(d_model, 32),
                nn.ReLU(),
                nn.Linear(32, 1),
            )
            self.type_head = nn.Sequential(
                nn.Linear(d_model, 32),
                nn.ReLU(),
                nn.Linear(32, len(ANOMALY_TYPES)),
            )

        def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
            """
            Args:
                x: (batch, WINDOW_SIZE, NUM_FEATURES)
            Returns:
                anomaly_score: (batch, 1) in [0, 1]
                anomaly_type_logits: (batch, len(ANOMALY_TYPES))
            """
            x = self.input_proj(x) + self.pos_encoding
            x = self.encoder(x)
            pooled = x.mean(dim=1)
            anomaly_score = torch.sigmoid(self.anomaly_head(pooled))
            anomaly_type_logits = self.type_head(pooled)
            return anomaly_score, anomaly_type_logits


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _load_model():
    """Load or initialise the transformer model (singleton)."""
    global _model_instance
    if not TORCH_AVAILABLE:
        return None
    if _model_instance is not None:
        return _model_instance

    model = TimeSeriesTransformer()
    weights_path = os.environ.get("ML_MODEL_WEIGHTS", "")
    if weights_path and os.path.isfile(weights_path):
        try:
            model.load_state_dict(torch.load(weights_path, map_location="cpu"))
            logger.info("Loaded ML model weights from %s", weights_path)
        except Exception as exc:
            logger.warning("Could not load model weights (%s); using untrained model", exc)
    else:
        logger.info("No pre-trained weights found; using randomly initialised model (demo mode)")

    model.eval()
    _model_instance = model
    return model


def prepare_features(signals: dict[str, Any], service: str = "payments") -> np.ndarray | None:
    """Extract features from Prometheus signals and append to the rolling buffer.

    Returns the current window as a numpy array of shape (window_len, 3), or
    None if there are not enough observations yet.
    """
    error_rate = signals.get("errors", {}).get(service, 0.0)
    latency_p99 = signals.get("p99_seconds", {}).get(service, 0.0)
    total_rate = sum(signals.get("errors", {}).values()) if signals.get("errors") else 0.0

    buf = _get_or_create_buffer(service)
    buf.append([error_rate, latency_p99 if latency_p99 else 0.0, total_rate])

    if len(buf) < 5:
        return None

    arr = np.array(list(buf), dtype=np.float32)
    if arr.shape[0] < WINDOW_SIZE:
        pad = np.zeros((WINDOW_SIZE - arr.shape[0], NUM_FEATURES), dtype=np.float32)
        arr = np.concatenate([pad, arr], axis=0)
    return arr


def predict_anomaly(signals: dict[str, Any], service: str = "payments") -> dict[str, Any]:
    """Run the transformer on the current feature window and return predictions.

    Returns a dict with keys: anomaly_score, anomaly_type, raw_logits, available.
    If the model is unavailable or there is insufficient data the score defaults
    to 0.0 with available=False.
    """
    result: dict[str, Any] = {
        "anomaly_score": 0.0,
        "anomaly_type": "normal",
        "raw_logits": [],
        "available": False,
    }

    if not TORCH_AVAILABLE:
        return result

    model = _load_model()
    if model is None:
        return result

    features = prepare_features(signals, service)
    if features is None:
        return result

    try:
        tensor = torch.tensor(features, dtype=torch.float32).unsqueeze(0)
        with torch.no_grad():
            score, logits = model(tensor)
        score_val = float(score.squeeze().item())
        logits_np = logits.squeeze().numpy()
        type_idx = int(np.argmax(logits_np))
        result["anomaly_score"] = round(score_val, 4)
        result["anomaly_type"] = ANOMALY_TYPES[type_idx]
        result["raw_logits"] = [round(float(v), 4) for v in logits_np]
        result["available"] = True
    except Exception as exc:
        logger.warning("ML prediction failed: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Synthetic training data generator (demo / testing)
# ---------------------------------------------------------------------------

def generate_synthetic_training_data(
    n_samples: int = 2000,
    window: int = WINDOW_SIZE,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create labelled training data for the anomaly classifier.

    Returns:
        X: (n_samples, window, NUM_FEATURES)
        y_score: (n_samples,) binary 0/1
        y_type: (n_samples,) class index in [0..3]
    """
    rng = np.random.default_rng(42)
    X = np.zeros((n_samples, window, NUM_FEATURES), dtype=np.float32)
    y_score = np.zeros(n_samples, dtype=np.float32)
    y_type = np.zeros(n_samples, dtype=np.int64)

    for i in range(n_samples):
        label = rng.integers(0, len(ANOMALY_TYPES))
        base_err = rng.uniform(0.0, 0.02)
        base_lat = rng.uniform(0.05, 0.3)
        base_rps = rng.uniform(5.0, 50.0)

        err_series = base_err + rng.normal(0, 0.005, window).clip(0)
        lat_series = base_lat + rng.normal(0, 0.02, window).clip(0)
        rps_series = base_rps + rng.normal(0, 2.0, window).clip(0)

        if label == 1:  # latency_spike
            spike_start = rng.integers(window // 3, window - 5)
            lat_series[spike_start:] += rng.uniform(1.0, 5.0)
        elif label == 2:  # error_burst
            spike_start = rng.integers(window // 3, window - 5)
            err_series[spike_start:] += rng.uniform(0.1, 0.6)
        elif label == 3:  # throughput_drop
            drop_start = rng.integers(window // 3, window - 5)
            rps_series[drop_start:] *= rng.uniform(0.05, 0.3)

        X[i, :, 0] = err_series
        X[i, :, 1] = lat_series
        X[i, :, 2] = rps_series
        y_score[i] = 0.0 if label == 0 else 1.0
        y_type[i] = label

    return X, y_score, y_type


if __name__ == "__main__":
    if not TORCH_AVAILABLE:
        print("PyTorch is required.  pip install torch")
        raise SystemExit(1)

    print("Generating synthetic training data ...")
    X, y_score, y_type = generate_synthetic_training_data(2000)
    print(f"  X: {X.shape}, y_score unique: {np.unique(y_score)}, y_type unique: {np.unique(y_type)}")

    model = TimeSeriesTransformer()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    bce = torch.nn.BCELoss()
    ce = torch.nn.CrossEntropyLoss()

    X_t = torch.tensor(X)
    ys_t = torch.tensor(y_score).unsqueeze(1)
    yt_t = torch.tensor(y_type)

    model.train()
    for epoch in range(20):
        optimizer.zero_grad()
        score_pred, type_pred = model(X_t)
        loss = bce(score_pred, ys_t) + ce(type_pred, yt_t)
        loss.backward()
        optimizer.step()
        if (epoch + 1) % 5 == 0:
            print(f"  epoch {epoch+1:3d}  loss={loss.item():.4f}")

    torch.save(model.state_dict(), "model_weights.pt")
    print("Saved model_weights.pt")
