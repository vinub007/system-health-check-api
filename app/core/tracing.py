"""
OpenTelemetry tracing bootstrap.

Fixes applied
-------------
Issue 1: Module was never imported — now imported and called from main.py via setup_tracing().
Issue 2: Instrumentation was unconditional — now gated on settings.OTEL_ENABLED.
Issue 7: Bare TracerProvider used SynchronousMultiSpanProcessor (blocks request thread)
         — replaced with BatchSpanProcessor for async background export.
Issue 4: OTLP exporter package was missing from requirements — now wired here using
         opentelemetry-exporter-otlp-proto-grpc (gRPC) with HTTP fallback note.

Design decisions
----------------
* We use the gRPC OTLP exporter because it is the most efficient transport and is
  natively supported by Jaeger (all-in-one), Grafana Tempo, and the OTel Collector.
  Switch to opentelemetry-exporter-otlp-proto-http if gRPC is blocked by a firewall.
* BatchSpanProcessor exports spans in a background thread so individual requests are
  never blocked waiting for the exporter to flush.
* When OTEL_ENABLED=False (the default) this function is a no-op — zero overhead.
* Resource attributes (service.name, deployment.environment) are attached so spans
  are correctly grouped in Jaeger / Tempo UI.
"""
import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import settings

logger = logging.getLogger(__name__)


def setup_tracing() -> None:
    """
    Configure and register the global TracerProvider.
    Call this once at application startup, before FastAPIInstrumentor.instrument_app().
    Is a no-op when settings.OTEL_ENABLED is False.
    """
    if not settings.OTEL_ENABLED:
        logger.debug("OTEL tracing disabled (OTEL_ENABLED=false) — skipping setup")
        return

    resource = Resource.create(
        {
            SERVICE_NAME: settings.OTEL_SERVICE_NAME,
            SERVICE_VERSION: settings.APP_VERSION,
            "deployment.environment": settings.ENVIRONMENT,
        }
    )

    provider = TracerProvider(resource=resource)

    # Attach OTLP gRPC exporter with BatchSpanProcessor (async, non-blocking)
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info(
            "OTel tracing initialised (gRPC OTLP)",
            extra={
                "otel_endpoint": settings.OTEL_EXPORTER_OTLP_ENDPOINT,
                "service_name": settings.OTEL_SERVICE_NAME,
            },
        )
    except ImportError:
        logger.warning(
            "opentelemetry-exporter-otlp-proto-grpc not installed — "
            "tracing provider registered but no spans will be exported. "
            "Add it to requirements.txt to enable export."
        )

    trace.set_tracer_provider(provider)
