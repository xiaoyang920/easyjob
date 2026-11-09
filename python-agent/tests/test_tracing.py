"""Chapter 7 tracing checks; no production DB, Redis, models or exporters are used."""
import asyncio
from contextlib import aclosing
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from databases import Database
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from redis.asyncio import Redis
from app.services import tracing, observability
from app.services.logging_config import TraceFilter, request_trace
from app.services.traced_database import TracedDatabase


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


class InstrumentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_httpx_redis_concurrency_exclusion_and_provider_isolation(self):
        exporter = InMemorySpanExporter()
        global_provider = trace.get_tracer_provider()
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                captured.append(self.headers.get("traceparent"))
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args): pass
        http_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=http_server.serve_forever, daemon=True).start()

        async def redis_handler(reader, writer):
            try:
                while line := await reader.readline():
                    count = int(line[1:])
                    arguments = []
                    for _ in range(count):
                        size = int((await reader.readline())[1:])
                        arguments.append(await reader.readexactly(size))
                        await reader.readexactly(2)
                    writer.write(b"+PONG\r\n" if arguments[0].upper() == b"PING" else b"+OK\r\n")
                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()
        redis_server = await asyncio.start_server(redis_handler, "127.0.0.1", 0)
        redis_port = redis_server.sockets[0].getsockname()[1]
        app = FastAPI()
        @app.get("/work")
        async def work():
            context = trace.get_current_span().get_span_context()
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get(f"http://127.0.0.1:{http_server.server_port}/fixture")
                self.assertEqual(response.status_code, 200)
            redis = Redis(host="127.0.0.1", port=redis_port)
            try:
                self.assertTrue(await redis.ping())
            finally:
                await redis.aclose()
            return {"trace": f"{context.trace_id:032x}"}
        @app.get("/identity")
        async def identity():
            await asyncio.sleep(0)
            context = trace.get_current_span().get_span_context()
            return {"trace": f"{context.trace_id:032x}", "span": f"{context.span_id:016x}"}
        @app.get("/health")
        @app.get("/health/ready")
        async def health(): return {"status": "ok"}
        env = {"EASYJOB_TRACING_ENABLED": "true", "OTEL_TRACES_SAMPLER_ARG": "1.0"}
        with patch.object(tracing, "_provider", None), patch.dict(os.environ, env), patch.object(tracing, "OTLPSpanExporter", return_value=exporter):
            try:
                tracing.init_tracing(app)
                provider = tracing._provider
                tracing.init_tracing(app)
                self.assertIs(tracing._provider, provider)
                self.assertIs(trace.get_tracer_provider(), global_provider)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://fixture") as client:
                    tid, pid = "a" * 32, "b" * 16
                    reply = await client.get("/work", headers={"traceparent": f"00-{tid}-{pid}-01"})
                    self.assertEqual(reply.json()["trace"], tid)
                    async def one(index):
                        trace_id, parent_id = f"{index + 1:032x}", f"{index + 100:016x}"
                        reply = await client.get("/identity", headers={"traceparent": f"00-{trace_id}-{parent_id}-01"})
                        self.assertEqual(reply.json()["trace"], trace_id)
                        return trace_id
                    self.assertEqual(len(set(await asyncio.gather(*(one(i) for i in range(8))))), 8)
                    await client.get("/health")
                    await client.get("/health/ready")
                self.assertTrue(provider.force_flush())
                spans = exporter.get_finished_spans()
                servers = [s for s in spans if s.kind == SpanKind.SERVER]
                self.assertEqual(len(servers), 9)
                root = next(s for s in servers if s.name == "GET /work")
                self.assertEqual(root.parent.span_id, int(pid, 16))
                self.assertTrue(any(s.name == "PING" and s.context.trace_id == int(tid, 16) for s in spans))
                outbound = next(s for s in spans if s.kind == SpanKind.CLIENT and s.name == "GET")
                self.assertEqual(outbound.parent.span_id, root.context.span_id)
                self.assertEqual(captured[0].split("-")[2], f"{outbound.context.span_id:016x}")
                for server in servers:
                    if server.name == "GET /identity":
                        index = server.context.trace_id - 1
                        self.assertEqual(server.parent.span_id, index + 100)
                self.assertFalse(trace.get_current_span().get_span_context().is_valid)
            finally:
                await tracing.shutdown_tracing()
                FastAPIInstrumentor.uninstrument_app(app)
                HTTPXClientInstrumentor().uninstrument()
                RedisInstrumentor().uninstrument()
                redis_server.close()
                await redis_server.wait_closed()
                await asyncio.to_thread(http_server.shutdown)
                http_server.server_close()


    async def test_real_otlp_http_export_uses_configured_private_provider(self):
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
        received = []
        class Collector(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = self.rfile.read(int(self.headers["Content-Length"]))
                request = ExportTraceServiceRequest()
                request.ParseFromString(payload)
                received.append((self.path, request))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        app = FastAPI()
        @app.get("/export")
        async def export():
            return {"ok": True}
        env = {"EASYJOB_TRACING_ENABLED": "true", "OTEL_TRACES_SAMPLER_ARG": "1.0",
               "OTEL_SERVICE_NAME": "easyjob-agent-fixture",
               "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
               "OTEL_EXPORTER_OTLP_HEADERS": "", "OTEL_EXPORTER_OTLP_TRACES_HEADERS": ""}
        with patch.object(tracing, "_provider", None), patch.dict(os.environ, env):
            try:
                tracing.init_tracing(app)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://fixture") as client:
                    response = await client.get("/export", headers={"traceparent": "00-" + "c" * 32 + "-" + "d" * 16 + "-01"})
                    self.assertEqual(response.status_code, 200)
                self.assertTrue(await asyncio.to_thread(tracing._provider.force_flush))
                self.assertTrue(received)
                self.assertEqual(received[0][0], "/v1/traces")
                batch = received[0][1].resource_spans[0]
                attributes = {a.key: a.value.string_value for a in batch.resource.attributes}
                self.assertEqual(attributes["service.name"], "easyjob-agent-fixture")
                spans = [s for scope in batch.scope_spans for s in scope.spans]
                self.assertTrue(any(s.name == "GET /export" and s.trace_id.hex() == "c" * 32 for s in spans))
            finally:
                await tracing.shutdown_tracing()
                FastAPIInstrumentor.uninstrument_app(app)
                HTTPXClientInstrumentor().uninstrument()
                RedisInstrumentor().uninstrument()
                await asyncio.to_thread(server.shutdown)
                server.server_close()


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

