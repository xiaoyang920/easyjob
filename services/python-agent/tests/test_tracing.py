"""Chapter 7 tracing checks; no production DB, Redis, models or exporters are used."""
import asyncio
from contextlib import aclosing
import logging
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from databases import Database
from fastapi import HTTPException
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from app.services import tracing, observability
from app.services.logging_config import TraceFilter, request_trace
from app.services.traced_database import TracedDatabase
from app.services.traced_chat_model import TracedChatOpenAI
from langchain_openai import ChatOpenAI


class TracingHelpersTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.provider_patch = patch.object(tracing, "_provider", self.provider)
        self.provider_patch.start()

    def tearDown(self):
        self.provider_patch.stop()
        self.provider.shutdown()

    async def test_propagation_links_and_context_restoration(self):
        incoming = {"traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01"}
        with tracing.traced("received", carrier=incoming) as span:
            self.assertEqual(span.get_span_context().trace_id, int("1" * 32, 16))
            carrier = tracing.capture()
            with tracing.traced("child"):
                self.assertEqual(tracing.capture()["traceparent"].split("-")[1], "1" * 32)
        with tracing.traced("job", carrier=carrier, linked=True):
            pass
        spans = self.exporter.get_finished_spans()
        received = next(s for s in spans if s.name == "received")
        job = next(s for s in spans if s.name == "job")
        self.assertEqual(received.parent.span_id, int("2" * 16, 16))
        self.assertIsNone(job.parent)
        self.assertEqual(job.links[0].context.span_id, received.context.span_id)
        with tracing.traced("invalid", carrier={"traceparent": "bad"}) as invalid:
            self.assertNotEqual(invalid.get_span_context().trace_id, received.context.trace_id)
        self.assertFalse(trace.get_current_span().get_span_context().is_valid)

    async def test_errors_cancel_and_async_stage(self):
        @tracing.trace_stage("stage")
        async def stage():
            raise HTTPException(400, "do not export this body")
        with self.assertRaises(HTTPException):
            await stage()
        span = self.exporter.get_finished_spans()[-1]
        self.assertEqual(span.attributes["easyjob.result.code"], 400)
        self.assertNotEqual(span.status.status_code, StatusCode.ERROR)
        with self.assertRaises(RuntimeError):
            with tracing.traced("failed"):
                raise RuntimeError("sensitive fixture")
        failed = self.exporter.get_finished_spans()[-1]
        self.assertEqual(failed.status.status_code, StatusCode.ERROR)
        self.assertEqual(failed.attributes["error.type"], "RuntimeError")
        self.assertFalse(failed.events)
        with self.assertRaises(asyncio.CancelledError):
            with tracing.traced("cancelled"):
                raise asyncio.CancelledError()
        self.assertTrue(self.exporter.get_finished_spans()[-1].attributes["easyjob.cancelled"])
        self.assertFalse(trace.get_current_span().get_span_context().is_valid)

    async def test_model_stream_records_first_content_and_does_not_leak_context_on_yield(self):
        model = TracedChatOpenAI(model="fixture", api_key="fixture")

        async def provider(*args, **kwargs):
            tracing.tracer().start_span("provider").end()
            yield SimpleNamespace(text="", message=SimpleNamespace(tool_call_chunks=[]))
            yield SimpleNamespace(text="", message=SimpleNamespace(tool_call_chunks=[{}]))
            yield SimpleNamespace(text="private content", message=SimpleNamespace(tool_call_chunks=[]))

        with patch.object(ChatOpenAI, "_astream", provider):
            with tracing.traced("request") as parent:
                async with aclosing(model._astream([])) as stream:
                    await anext(stream)
                    await anext(stream)
                    self.assertEqual(trace.get_current_span(), parent)
        provider_span, model_span, request_span = self.exporter.get_finished_spans()
        self.assertEqual(provider_span.parent.span_id, model_span.context.span_id)
        self.assertEqual(model_span.parent.span_id, request_span.context.span_id)
        self.assertEqual([event.name for event in model_span.events], ["agent.model.first_content"])
        self.assertTrue(model_span.attributes["easyjob.cancelled"])

    async def test_durable_job_span_links_to_enqueue_trace_and_marks_old_jobs(self):
        with tracing.traced("enqueue") as parent:
            payload = tracing.attach_job_trace({"key": "value"})
        for job in ({"kind": "memory_index", "job_id": "new", "payload": payload},
                    {"kind": "memory_index", "job_id": "old", "payload": {}}):
            with tracing.durable_job_span(job):
                pass
        _, new, old = self.exporter.get_finished_spans()
        self.assertEqual(new.links[0].context, tracing.trace.get_current_span(tracing.remote_context(payload['_trace'])).get_span_context())
        self.assertEqual(new.links[0].context.span_id, parent.get_span_context().span_id)
        self.assertIn("easyjob.queue.wait_ms", new.attributes)
        self.assertIsNone(old.parent)
        self.assertFalse(old.links)

    async def test_log_fields_keep_legacy_identifiers(self):
        with request_trace("123", "request-fixture-123", "run-fixture-123"):
            with tracing.traced("logging") as span:
                record = logging.LogRecord("fixture", logging.INFO, "", 0, "ok", (), None)
                TraceFilter().filter(record)
                self.assertEqual(record.otel_trace_id, f"{span.get_span_context().trace_id:032x}")
                self.assertEqual(record.otel_span_id, f"{span.get_span_context().span_id:016x}")
                self.assertEqual((record.trace_id, record.conv_id, record.run_id),
                                 ("request-fixture-123", "123", "run-fixture-123"))
        record = logging.LogRecord("fixture", logging.INFO, "", 0, "ok", (), None)
        TraceFilter().filter(record)
        self.assertEqual((record.otel_trace_id, record.otel_span_id), ("-", "-"))

    async def test_langfuse_switch_preserves_default_integration(self):
        observe = Mock(return_value=lambda fn: "decorated")
        callback = Mock(return_value="callback")
        modules = {"langfuse": SimpleNamespace(observe=observe),
                   "langfuse.langchain": SimpleNamespace(CallbackHandler=callback)}
        async def node(): pass
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {"EASYJOB_TRACING_LAB_ONLY": "true"}):
            self.assertIs(observability.trace_node("fixture")(node), node)
            self.assertIsNone(observability.get_langfuse_callback())
            observe.assert_not_called()
            callback.assert_not_called()
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {"EASYJOB_TRACING_LAB_ONLY": "false"}):
            self.assertEqual(observability.trace_node("fixture")(node), "decorated")
            self.assertEqual(observability.get_langfuse_callback(), "callback")

    async def test_database_methods_preserve_arguments_and_results(self):
        db = TracedDatabase("mysql://fixture:fixture@127.0.0.1/fixture")
        for method in ("fetch_all", "fetch_one", "fetch_val", "execute", "execute_many"):
            result = object()
            query, values = "private query", {"private": "value"}
            delegate = AsyncMock(return_value=result)
            with patch.object(Database, method, delegate):
                if method == "fetch_val":
                    actual = await db.fetch_val(query, values, column=2)
                    delegate.assert_awaited_once_with(query, values, 2)
                else:
                    actual = await getattr(db, method)(query, values)
                    delegate.assert_awaited_once_with(query, values)
                self.assertIs(actual, result)
        for span in self.exporter.get_finished_spans():
            self.assertEqual(set(span.attributes), {"db.system.name", "db.operation.name"})
            self.assertEqual(span.kind, SpanKind.CLIENT)

    async def test_database_iteration_closes_underlying_generator(self):
        closed = []
        async def source(self, query, values=None):
            try:
                yield 1
                yield 2
            finally:
                closed.append(True)
        db = TracedDatabase("mysql://fixture:fixture@127.0.0.1/fixture")
        with patch.object(Database, "iterate", source):
            async with aclosing(db.iterate("fixture")) as rows:
                self.assertEqual(await anext(rows), 1)
        self.assertEqual(closed, [True])
        self.assertEqual(self.exporter.get_finished_spans()[-1].name, "mysql.iterate")
        self.assertFalse(trace.get_current_span().get_span_context().is_valid)


class LifecycleTracingTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_and_cleanup_failures_still_close_tracing(self):
        with patch.dict(os.environ, {"EASYJOB_TRACING_ENABLED": "false", "EASYJOB_TRACING_LAB_ONLY": "true"}):
            from app import main
        from app.security.stream_sessions import sessions
        with patch.object(main.mysql_client, "startup", AsyncMock(side_effect=RuntimeError("fixture startup"))), \
                patch.object(sessions, "close", AsyncMock(side_effect=RuntimeError("fixture cleanup"))), \
                patch.object(main, "shutdown_tracing", AsyncMock()) as shutdown:
            with self.assertRaisesRegex(RuntimeError, "fixture cleanup"):
                async with main.lifespan(main.app):
                    self.fail("startup must fail")
            shutdown.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
