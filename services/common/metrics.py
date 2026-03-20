"""Prometheus metrics are registered via instrumentation.instrument_flask_app."""
from common.instrumentation import instrument_flask_app

__all__ = ["instrument_flask_app"]
