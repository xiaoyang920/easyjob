"""Agent tracing integration checks against loopback HTTP and Redis protocol fixtures."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from redis.asyncio import Redis

from app.services import tracing


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
        env = {
            "EASYJOB_TRACING_ENABLED": "true",
            "OTEL_TRACES_SAMPLER_ARG": "1.0",
            "OTEL_SERVICE_NAME": "easyjob-agent-fixture",
            "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
            "OTEL_EXPORTER_OTLP_HEADERS": "",
            "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
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
