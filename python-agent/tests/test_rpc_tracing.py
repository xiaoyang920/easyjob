"""Chapter 8: real loopback gRPC, without production services or credentials."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault('DEEPSEEK_API_KEY', 'offline-test')
os.environ.setdefault('AGENT_SERVICE_KEY', 'offline-service-key-32-bytes-long!!')

import grpc
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from app.rpc import blog_client, server as agent_server
from app.rpc.generated import easyjob_rpc_pb2 as pb, easyjob_rpc_pb2_grpc as api
from app.rpc.peer_pool import PeerPool
from app.services import tracing, trace_rpc


class RpcTracingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.enterContext(patch.object(tracing, '_provider', self.provider))
        self.enterContext(patch.object(blog_client, '_channel', None))
        self.enterContext(patch.object(blog_client, '_stub', None))
        self.enterContext(patch.object(blog_client, 'pool', PeerPool(blog_client._peer)))
        self.servers, self.channels = [], []

    async def asyncTearDown(self):
        await blog_client.close_client()
        for channel in self.channels:
            await channel.close()
        for server in self.servers:
            await server.stop(0)
        self.assertFalse(trace.get_current_span().get_span_context().is_valid)
        self.provider.shutdown()

    async def serve(self, handler, service='com.easyjob.rpc.v1.BlogRpc', method='ReadPublic'):
        server = grpc.aio.server(interceptors=[trace_rpc.RpcServerTracingInterceptor()])
        server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(service, {
            method: grpc.unary_unary_rpc_method_handler(handler,
                request_deserializer=pb.BlogQuery.FromString,
                response_serializer=pb.Reply.SerializeToString),
        }),))
        bound = server.add_insecure_port('127.0.0.1:0')
        self.assertTrue(bound)
        await server.start()
        self.servers.append(server)
        return f'127.0.0.1:{bound}'

    def channel(self, target, *, intercepted=True):
        interceptors = [trace_rpc.RpcClientTracingInterceptor()] if intercepted else []
        channel = grpc.aio.insecure_channel(target, interceptors=interceptors)
        self.channels.append(channel)
        return channel

    def spans(self, kind=None):
        return [span for span in self.exporter.get_finished_spans()
                if kind is None or span.kind == kind]

    def test_metadata_replaces_stale_keys_preserves_other_headers_and_rejects_duplicates(self):
        carrier = {'traceparent': '00-' + '1' * 32 + '-' + '2' * 16 + '-01',
                   'tracestate': 'fixture=one'}
        with tracing.traced('parent', carrier=carrier) as span:
            metadata = trace_rpc.outgoing_metadata((('x-keep', 'value'), ('x-binary-bin', b'\x00\xff'),
                ('traceparent', 'stale'), ('tracestate', 'stale=one')))
            values = dict(metadata)
            self.assertEqual(values['x-keep'], 'value')
            self.assertEqual(values['x-binary-bin'], b'\x00\xff')
            self.assertEqual(values['traceparent'], tracing.capture()['traceparent'])
            self.assertIn(f'{span.get_span_context().span_id:016x}', values['traceparent'])
            self.assertEqual(values['tracestate'], 'fixture=one')
            self.assertEqual(len(metadata), 4)
        self.assertEqual(trace_rpc.incoming_metadata(metadata),
                         {key: values[key] for key in trace_rpc.TRACE_KEYS})
        for key in trace_rpc.TRACE_KEYS:
            self.assertEqual(trace_rpc.incoming_metadata((*metadata, (key, values[key]))), {})
        self.assertEqual(trace_rpc.incoming_metadata((('traceparent', b'bad'),)), {})

    async def test_dynamic_interface_names_and_real_parent_ids(self):
        seen = []
        async def reserve(request, context):
            seen.append((request.SerializeToString(), tuple(context.invocation_metadata())))
            return pb.Reply(data=pb.Value(text='reserved'))
        service, method = 'example.InventoryRpc', 'Reserve'
        target = await self.serve(reserve, service, method)
        reserve = self.channel(target).unary_unary(f'/{service}/{method}',
            request_serializer=pb.BlogQuery.SerializeToString, response_deserializer=pb.Reply.FromString)
        request = pb.BlogQuery(identity=pb.Identity(user_id=7, trace_id='legacy-id-123'), kind='fixture')
        original = request.SerializeToString()
        with tracing.traced('caller') as parent:
            reply = await reserve(request, metadata=(('x-keep', 'value'),), timeout=2)
            self.assertEqual(trace.get_current_span().get_span_context(), parent.get_span_context())
        self.assertEqual(reply.data.text, 'reserved')
        client, server = self.spans(SpanKind.CLIENT)[0], self.spans(SpanKind.SERVER)[0]
        self.assertEqual(server.context.trace_id, client.context.trace_id)
        self.assertEqual(server.parent.span_id, client.context.span_id)
        self.assertEqual(client.parent.span_id, parent.get_span_context().span_id)
        for span in (client, server):
            self.assertEqual(span.name, f'{service}/{method}')
            self.assertEqual(span.attributes['rpc.service'], service)
            self.assertEqual(span.attributes['rpc.method'], method)
            self.assertEqual(span.attributes['rpc.system'], 'grpc')
            self.assertFalse(span.events)
            self.assertNotIn('legacy-id-123', str(span.attributes))
        self.assertEqual(seen[0][0], original)
        self.assertEqual(request.SerializeToString(), original)
        self.assertIn(('x-keep', 'value'), seen[0][1])
        self.assertEqual(len(self.spans()), 3)

    async def test_fixed_and_discovered_blog_channels_both_trace_once(self):
        async def read(request, context):
            return pb.Reply(data=pb.Value(text='ok'))
        target = await self.serve(read)
        with patch.object(blog_client.settings, 'BLOG_RPC_TARGET', target), \
                patch.object(blog_client.settings, 'AGENT_SERVICE_KEY', 'offline-fixture-key-at-least-32-bytes'):
            for discovered in (False, True):
                with patch('app.rpc.discovery.catalog.enabled', discovered), \
                        patch('app.rpc.discovery.catalog.target', AsyncMock(return_value=target)), \
                        patch('app.rpc.discovery.catalog.healthy_targets', return_value=(target,)):
                    with tracing.traced(f'caller-{discovered}'):
                        self.assertEqual(await blog_client.public_read('fixture'), 'ok')
        self.assertEqual(len(self.spans(SpanKind.CLIENT)), 2)
        self.assertEqual(len(self.spans(SpanKind.SERVER)), 2)
        for client in self.spans(SpanKind.CLIENT):
            server = next(span for span in self.spans(SpanKind.SERVER)
                          if span.context.trace_id == client.context.trace_id)
            self.assertEqual(server.parent.span_id, client.context.span_id)

    async def test_server_starts_with_interceptor_and_authentication_stays_active(self):
        # Capture the OS-assigned port while using the production start_server.
        create_server = grpc.aio.server
        ports = []
        def factory(*args, **kwargs):
            server = create_server(*args, **kwargs)
            bind = server.add_insecure_port
            def capture_port(address):
                port = bind(address)
                ports.append(port)
                return port
            server.add_insecure_port = capture_port
            return server
        key = 'offline-fixture-key-at-least-32-bytes'
        query = AsyncMock(return_value={'ok': True})
        with patch.object(agent_server.settings, 'AGENT_RPC_BIND', '127.0.0.1:0'), \
                patch.object(agent_server.settings, 'AGENT_SERVICE_KEY', key), \
                patch.object(grpc.aio, 'server', side_effect=factory), \
                patch('app.security.delegation.verify', return_value={}), \
                patch('app.services.service_queries.query', query):
            self.servers.append(await agent_server.start_server())
            stub = api.AgentRpcStub(self.channel(f'127.0.0.1:{ports[0]}', intercepted=False))
            carrier = {'traceparent': '00-' + '3' * 32 + '-' + '4' * 16 + '-01'}
            reply = await stub.ServiceQuery(pb.AgentQuery(identity=pb.Identity(user_id=7,
                service_key=key, trace_id='legacy-request-123'), kind='health'),
                metadata=tuple(carrier.items()), timeout=2)
            self.assertTrue(reply.HasField('data'))
            denied = await stub.ServiceQuery(pb.AgentQuery(identity=pb.Identity(user_id=7,
                service_key='wrong-key'), kind='health'), metadata=tuple(carrier.items()), timeout=2)
            self.assertEqual(denied.error.status, 401)
            query.assert_awaited_once()
        spans = self.spans(SpanKind.SERVER)
        self.assertEqual(len(spans), 2)
        for span in spans:
            self.assertEqual(span.context.trace_id, int('3' * 32, 16))
            self.assertEqual(span.parent.span_id, int('4' * 16, 16))
        self.assertEqual([span.attributes['easyjob.result.code'] for span in spans], [200, 401])

    async def test_concurrent_calls_do_not_share_context(self):
        async def read(request, context):
            await asyncio.sleep(0)
            return pb.Reply(data=pb.Value(text=str(request.target_id)))
        target = await self.serve(read)
        stub = api.BlogRpcStub(self.channel(target))
        async def one(index):
            with tracing.traced(f'caller-{index}') as root:
                reply = await stub.ReadPublic(pb.BlogQuery(target_id=index), timeout=3)
                self.assertEqual(reply.data.text, str(index))
                self.assertEqual(trace.get_current_span().get_span_context(), root.get_span_context())
                return root.get_span_context().trace_id
        trace_ids = await asyncio.gather(*(one(index) for index in range(24)))
        self.assertEqual(len(set(trace_ids)), 24)
        for trace_id in trace_ids:
            spans = [span for span in self.spans() if span.context.trace_id == trace_id]
            self.assertEqual(len(spans), 3)
            client = next(span for span in spans if span.kind == SpanKind.CLIENT)
            server = next(span for span in spans if span.kind == SpanKind.SERVER)
            self.assertEqual(server.parent.span_id, client.context.span_id)

    async def test_invalid_missing_and_joined_headers_create_new_roots(self):
        async def read(request, context):
            return pb.Reply(data=pb.Value(text='ok'))
        stub = api.BlogRpcStub(self.channel(await self.serve(read), intercepted=False))
        valid = '00-' + '5' * 32 + '-' + '6' * 16 + '-01'
        other = '00-' + '7' * 32 + '-' + '8' * 16 + '-01'
        # gRPC's client metadata normalizes repeated keys before transmission.
        # Duplicates visible to the interceptor are checked separately above.
        for metadata in ((), (('traceparent', 'bad'),),
                         (('traceparent', valid + ',' + other),)):
            await stub.ReadPublic(pb.BlogQuery(), metadata=metadata, timeout=2)
        spans = self.spans(SpanKind.SERVER)
        self.assertEqual(len(spans), 3)
        self.assertEqual(len({span.context.trace_id for span in spans}), 3)
        self.assertTrue(all(span.parent is None for span in spans))

    async def test_business_errors_and_missing_reply_do_not_export_content(self):
        async def read(request, context):
            if request.target_id:
                return pb.Reply(error=pb.Error(status=request.target_id, message='private fixture'))
            return pb.Reply()
        stub = api.BlogRpcStub(self.channel(await self.serve(read)))
        for code, expected, error in ((409, 409, False), (500, 500, True), (0, 502, True)):
            before = len(self.spans())
            reply = await stub.ReadPublic(pb.BlogQuery(target_id=code), timeout=2)
            self.assertEqual(reply.error.status if code else 0, code)
            spans = self.spans()[before:]
            self.assertEqual(len(spans), 2)
            for span in spans:
                self.assertEqual(span.attributes['easyjob.result.code'], expected)
                self.assertEqual(span.status.status_code == StatusCode.ERROR, error)
                self.assertNotIn('private fixture', str(span.attributes))
                self.assertFalse(span.events)

    async def test_span_covers_full_response_and_cancel_closes_context(self):
        entered, closed = asyncio.Event(), asyncio.Event()
        async def read(request, context):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
        stub = api.BlogRpcStub(self.channel(await self.serve(read)))
        call = stub.ReadPublic(pb.BlogQuery(), timeout=3)
        await asyncio.wait_for(entered.wait(), 2)
        self.assertEqual(self.spans(), [])
        call.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await call
        await asyncio.wait_for(closed.wait(), 2)
        # Let the server's cancellation unwind through the tracing context.
        await asyncio.sleep(0)
        self.assertEqual(len(self.spans(SpanKind.CLIENT)), 1)
        self.assertEqual(len(self.spans(SpanKind.SERVER)), 1)
        self.assertTrue(all(span.attributes.get('easyjob.cancelled') for span in self.spans()))

    async def test_transport_abort_and_deadline_mark_client_error(self):
        async def read(request, context):
            if request.target_id:
                await context.abort(grpc.StatusCode.UNAVAILABLE, 'private fixture')
            await asyncio.Event().wait()
        stub = api.BlogRpcStub(self.channel(await self.serve(read)))
        for target_id, timeout, status in ((1, 2, grpc.StatusCode.UNAVAILABLE),
                                           (0, 0.05, grpc.StatusCode.DEADLINE_EXCEEDED)):
            with self.assertRaises(grpc.aio.AioRpcError) as caught:
                await stub.ReadPublic(pb.BlogQuery(target_id=target_id), timeout=timeout)
            self.assertEqual(caught.exception.code(), status)
        clients = self.spans(SpanKind.CLIENT)
        self.assertEqual(len(clients), 2)
        for span in clients:
            self.assertEqual(span.status.status_code, StatusCode.ERROR)
            self.assertEqual(span.attributes['error.type'], 'AioRpcError')
            self.assertNotIn('private fixture', str(span.attributes))
            self.assertFalse(span.events)

    async def test_tracing_disabled_does_not_replace_global_provider_or_break_calls(self):
        async def read(request, context):
            return pb.Reply(data=pb.Value(text='ok'))
        stub = api.BlogRpcStub(self.channel(await self.serve(read)))
        global_provider = trace.get_tracer_provider()
        with patch.object(tracing, '_provider', None):
            reply = await stub.ReadPublic(pb.BlogQuery(), timeout=2)
        self.assertEqual(reply.data.text, 'ok')
        self.assertIs(trace.get_tracer_provider(), global_provider)
        self.assertEqual(self.spans(), [])


if __name__ == '__main__':
    unittest.main()
