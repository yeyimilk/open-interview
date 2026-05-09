from __future__ import annotations

try:  # pragma: no cover - optional runtime integration.
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
except Exception:  # pragma: no cover
    trace = None  # type: ignore[assignment]
    OTLPSpanExporter = None  # type: ignore[assignment]
    Resource = None  # type: ignore[assignment]
    TracerProvider = None  # type: ignore[assignment]
    BatchSpanProcessor = None  # type: ignore[assignment]
    TraceIdRatioBased = None  # type: ignore[assignment]

_configured = False


def configure_tracing(
    *, enabled: bool, service_name: str, endpoint: str | None, sample_ratio: float
) -> None:
    global _configured
    if _configured or not enabled or trace is None or TracerProvider is None:
        return
    try:
        provider = TracerProvider(
            sampler=TraceIdRatioBased(max(0.0, min(1.0, sample_ratio))),
            resource=Resource.create({"service.name": service_name}),
        )
        if endpoint and OTLPSpanExporter is not None and BatchSpanProcessor is not None:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        _configured = True
    except Exception:
        pass
