"""gRPC metadata propagation, independent of business Protobuf fields."""

import grpc
from opentelemetry.trace import SpanKind
from app.services.tracing import capture, traced, mark_status

TRACE_KEYS = frozenset(("traceparent", "tracestate"))


def outgoing_metadata(existing):
    # Preserve caller metadata; replace stale trace keys.
    metadata = [(key, value) for key, value in (existing or ()) if key not in TRACE_KEYS]
    metadata.extend((key, value) for key, value in capture().items() if key in TRACE_KEYS)
    return tuple(metadata)


def incoming_metadata(metadata):
    carrier = {}
    duplicated = set()
    for key, value in metadata or ():
        if key in TRACE_KEYS and isinstance(value, str):
            if key in carrier:
                duplicated.add(key)
            carrier[key] = value
    # Ambiguous context becomes a new root, not a business error.
    return {} if duplicated else carrier


def reply_status(reply):
    descriptor = getattr(reply, "DESCRIPTOR", None)
    if descriptor is None or descriptor.full_name != "com.easyjob.rpc.v1.Reply":
        # Other interfaces can use another DTO; add its business mapping separately.
        return 200
    if reply.HasField("error"):
        return reply.error.status
    return 200 if reply.HasField("data") else 502


def rpc_identity(full_method):
    if isinstance(full_method, bytes):
        full_method = full_method.decode("ascii")
    service, method = full_method.lstrip("/").rsplit("/", 1)
    return service, method


class RpcClientTracingInterceptor(grpc.aio.UnaryUnaryClientInterceptor):
    async def intercept_unary_unary(self, continuation, details, request):
        service, method = rpc_identity(details.method)
        with traced(f"{service}/{method}", kind=SpanKind.CLIENT,
                    attributes={"rpc.system": "grpc", "rpc.service": service, "rpc.method": method}) as span:
            outbound = grpc.aio.ClientCallDetails(
                details.method, details.timeout, outgoing_metadata(details.metadata),
                details.credentials, details.wait_for_ready,
            )
            call = await continuation(outbound, request)
            # Await the response, not just creation of the asynchronous Call.
            reply = await call
            mark_status(span, reply_status(reply))
            return reply


class RpcServerTracingInterceptor(grpc.aio.ServerInterceptor):
    async def intercept_service(self, continuation, details):
        handler = await continuation(details)
        if handler is None or handler.request_streaming or handler.response_streaming:
            return handler
        service, method = rpc_identity(details.method)
        attributes = {"rpc.system": "grpc", "rpc.service": service, "rpc.method": method}

        async def unary(request, context):
            with traced(f"{service}/{method}", kind=SpanKind.SERVER,
                        carrier=incoming_metadata(context.invocation_metadata()),
                        attributes=attributes) as span:
                reply = await handler.unary_unary(request, context)
                mark_status(span, reply_status(reply))
                return reply

        return grpc.unary_unary_rpc_method_handler(unary,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer)
