"""Prometheus /metrics and OpenTelemetry traces for Flask services."""
import logging
import os

from flask import Flask
from prometheus_flask_exporter import PrometheusMetrics
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

logger = logging.getLogger(__name__)


def instrument_flask_app(app: Flask, service_name: str) -> None:
    """Expose Prometheus metrics on /metrics and export traces via OTLP HTTP."""
    PrometheusMetrics(app)

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
    if not endpoint:
        logger.warning("OTEL_EXPORTER_OTLP_ENDPOINT not set; traces disabled for %s", service_name)
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    span_endpoint = f"{endpoint}/v1/traces"
    exporter = OTLPSpanExporter(endpoint=span_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    FlaskInstrumentor().instrument_app(app)
    RequestsInstrumentor().instrument()
