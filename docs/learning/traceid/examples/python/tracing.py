"""Project tracing; each exporter is explicitly bound to our own provider."""
import asyncio
import inspect
import os
from contextlib import contextmanager
from functools import wraps
from time import time

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Link, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_provider = None
_noop = trace.NoOpTracerProvider()
_propagator = TraceContextTextMapPropagator()


def init_tracing(app):
    global _provider
    if _provider is not None or os.getenv("EASYJOB_TRACING_ENABLED", "false").lower() != "true":
        return
    ratio = float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0"))
    if not 0 <= ratio <= 1:
        raise ValueError("OTEL_TRACES_SAMPLER_ARG must be between zero and one")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:14318").rstrip("/")
    _provider = TracerProvider(
        resource=Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "easyjob-agent")}),
        sampler=ParentBased(TraceIdRatioBased(ratio)),
    )
    _provider.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", timeout=3),
        max_queue_size=2048, max_export_batch_size=512, schedule_delay_millis=1000,
    ))
    # Do not replace Langfuse's global TracerProvider.
    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=_provider, excluded_urls=r".*/health(?:/[^?]*)?(?:\?.*)?$",
    )
    HTTPXClientInstrumentor().instrument(tracer_provider=_provider)
    RedisInstrumentor().instrument(tracer_provider=_provider)


async def shutdown_tracing():
    if _provider is not None:
        await asyncio.to_thread(_provider.shutdown)


def tracer():
    return (_provider or _noop).get_tracer("easyjob.business", "1.0")


def capture():
    carrier = {}
    _propagator.inject(carrier)
    return carrier


def remote_context(carrier):
    safe = {key: carrier[key] for key in ("traceparent", "tracestate")
            if isinstance((carrier or {}).get(key), str)}
    return _propagator.extract(safe, context=Context())


def mark_error(span, error):
    span.set_attribute("error.type", type(error).__name__)
    span.set_status(Status(StatusCode.ERROR))


def mark_status(span, status):
    span.set_attribute("easyjob.result.code", int(status))
    if status >= 500:
        span.set_status(Status(StatusCode.ERROR))


@contextmanager
def traced(name, *, kind=SpanKind.INTERNAL, carrier=None, linked=False, attributes=None):
    options = {"kind": kind, "attributes": attributes or {},
               "record_exception": False, "set_status_on_exception": False}
    if linked:
        prior = trace.get_current_span(remote_context(carrier)).get_span_context()
        options.update(context=Context(), links=[Link(prior)] if prior.is_valid else [])
    elif carrier is not None:
        options["context"] = remote_context(carrier)
    with tracer().start_as_current_span(name, **options) as span:
        try:
            yield span
        except (asyncio.CancelledError, GeneratorExit):
            span.set_attribute("easyjob.cancelled", True)
            raise
        except BaseException as error:
            status = getattr(error, "status_code", None)
            if not isinstance(status, int):
                status = getattr(error, "status", None)
            if isinstance(status, int):
                mark_status(span, status)
            else:
                mark_error(span, error)
            raise


def trace_stage(name):
    def decorate(function):
        if not inspect.iscoroutinefunction(function):
            raise TypeError("trace_stage is for coroutine functions, not async generators")

        @wraps(function)
        async def wrapped(*args, **kwargs):
            with traced(name):
                return await function(*args, **kwargs)
        return wrapped
    return decorate


def attach_job_trace(payload):
    return {**payload, "_trace": capture(), "_trace_enqueued_ms": int(time() * 1000)}


@contextmanager
def durable_job_span(job):
    payload = job["payload"]
    with traced("agent.background_job", carrier=payload.get("_trace", {}), linked=True,
                attributes={"easyjob.job.kind": str(job["kind"]),
                            "easyjob.job.id": str(job["job_id"])}) as span:
        queued = payload.get("_trace_enqueued_ms")
        if isinstance(queued, (int, float)):
            span.set_attribute("easyjob.queue.wait_ms", max(0, int(time() * 1000 - queued)))
        yield span
