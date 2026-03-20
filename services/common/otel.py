"""See instrumentation.py for OTLP trace setup used by all services."""
from common.instrumentation import instrument_flask_app

__all__ = ["instrument_flask_app"]
