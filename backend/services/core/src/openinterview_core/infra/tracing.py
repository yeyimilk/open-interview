from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


try:  # pragma: no cover - optional runtime integration.
    from opentelemetry import trace
except Exception:  # pragma: no cover
    trace = None  # type: ignore[assignment]


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


def _set_attr(span: Any, key: str, value: Any) -> None:
    if span is None or value is None:
        return
    try:
        span.set_attribute(key, value)
    except Exception:
        pass
