from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


try:  # pragma: no cover - optional runtime integration.
    from opentelemetry import trace
except Exception:  # pragma: no cover
    trace = None  # type: ignore[assignment]

try:  # pragma: no cover - optional runtime integration.
    from opentelemetry import propagate
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
except Exception:  # pragma: no cover
    propagate = None  # type: ignore[assignment]
    Resource = None  # type: ignore[assignment]
    TracerProvider = None  # type: ignore[assignment]
    BatchSpanProcessor = None  # type: ignore[assignment]
    TraceIdRatioBased = None  # type: ignore[assignment]
    OTLPSpanExporter = None  # type: ignore[assignment]


_configured = False


def configure_tracing(
    *,
    enabled: bool,
    service_name: str,
    endpoint: str | None = None,
    sample_ratio: float = 1.0,
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


@contextmanager
def start_span(name: str, **attributes: Any) -> Iterator[Any]:
    if trace is None:
        yield None
        return

    tracer = trace.get_tracer("openinterview-core")
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            _set_attr(span, key, value)
        yield span


def set_current_span_attribute(key: str, value: Any) -> None:
    if trace is None:
        return
    span = trace.get_current_span()
    _set_attr(span, key, value)


def current_trace_headers() -> dict[str, str]:
    if propagate is None:
        return {}
    headers: dict[str, str] = {}
    try:
        propagate.inject(headers)
    except Exception:
        return {}
    return headers


def _set_attr(span: Any, key: str, value: Any) -> None:
    if span is None or value is None:
        return
    try:
        span.set_attribute(key, value)
    except Exception:
        pass
