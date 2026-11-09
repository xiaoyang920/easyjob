"""Unary internal queries for Java; browser chat and SSE use the public HTTP API."""
import asyncio
import hmac
import logging
import traceback
from pathlib import Path
from time import monotonic
from app.services.logging_config import request_trace
from app.services.trace_rpc import RpcServerTracingInterceptor

import grpc
from fastapi import HTTPException
from pydantic import ValidationError

from app.config import settings
from app.security.principal import Principal
from .codec import encode
from .generated import easyjob_rpc_pb2 as pb, easyjob_rpc_pb2_grpc as api

log = logging.getLogger(__name__)


def principal(identity):
    if len(settings.AGENT_SERVICE_KEY.encode()) < 32:
        raise HTTPException(503, 'Agent 服务认证尚未配置')
    if not hmac.compare_digest(identity.service_key.encode(), settings.AGENT_SERVICE_KEY.encode()):
        raise HTTPException(401, '服务身份无效')
    if identity.user_id <= 0:
        raise HTTPException(401, '用户身份无效')
    return Principal(identity.user_id)
def fault(exc):
    from app.services.grounding import DraftVerificationError
    if isinstance(exc, DraftVerificationError):
        return pb.Error(status=422, message=str(exc))
    if isinstance(exc, HTTPException):
        return pb.Error(status=exc.status_code, message=str(exc.detail))
    if isinstance(exc, (ValidationError, ValueError, TypeError)):
        return pb.Error(status=422, message='请求参数无效')
    # Keep useful server-side locations without logging prompts, credentials,
    # SQL parameters or exception messages that might contain user content.
    locations = ' > '.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
        for frame in traceback.extract_tb(exc.__traceback__)[-6:])
    log.error('Agent RPC failed: %s at %s', type(exc).__name__, locations or 'unknown')
    return pb.Error(status=500, message='Agent 服务暂时不可用')


class AgentRpc(api.AgentRpcServicer):
    async def invoke(self, method, request):
        user = principal(request.identity)
        from app.security.delegation import verify
        claims=verify(request.identity,method)
        if claims=='service_observe' and (method!='ServiceQuery' or request.kind not in ('health','metric_states','metric_rows','metric_daily','metric_stages','run_summary','memory_summary','reconcile_summary') or request.edit.fields or request.state):
            raise HTTPException(403,'服务观察凭证不能执行此操作')
        if method != 'ServiceQuery':
            raise HTTPException(404, 'RPC 方法不存在')
        from app.services.service_queries import query
        return await query(request, user.user_id)

    async def unary(self, method, request, context):
        started = monotonic()
        with request_trace(trace_id=request.identity.trace_id):
            reply = await self._unary_reply(method, request, context)
            log.info('rpc_server method=%s status=%s duration_ms=%.2f', method,
                reply.error.status if reply.HasField('error') else 200, (monotonic() - started) * 1000)
            return reply

    async def _unary_reply(self, method, request, context):
        from app.security.delegation import current_identity
        delegation_scope=current_identity.set(None)
        try:
            return pb.Reply(data=encode(await self.invoke(method, request)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return pb.Reply(error=fault(exc))
        finally:
            current_identity.reset(delegation_scope)

    async def ServiceQuery(self, request, context):
        return await self.unary('ServiceQuery', request, context)


async def start_server():
    server = grpc.aio.server(
        interceptors=[RpcServerTracingInterceptor()],
        options=[('grpc.max_receive_message_length', 4 * 1024 * 1024),
                 ('grpc.max_send_message_length', 8 * 1024 * 1024)],
    )
    api.add_AgentRpcServicer_to_server(AgentRpc(), server)
    bound = server.add_insecure_port(settings.AGENT_RPC_BIND)
    if not bound:
        raise RuntimeError('Agent RPC 监听地址不可用')
    await server.start()
    log.info('Agent RPC listening on %s', settings.AGENT_RPC_BIND)
    return server
