"""gRPC transport for the existing owner-checked Agent application functions."""
import asyncio
import hmac
import logging
from contextlib import aclosing
from datetime import datetime
from uuid import UUID

import grpc
from fastapi import HTTPException
from pydantic import ValidationError

from app.config import settings
from app.security.principal import Principal
from .codec import encode, decode_object
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


def positive(value):
    if value <= 0:
        raise HTTPException(422, '标识必须为正整数')
    return value


def fault(exc):
    if isinstance(exc, HTTPException):
        return pb.Error(status=exc.status_code, message=str(exc.detail))
    if isinstance(exc, (ValidationError, ValueError, TypeError)):
        return pb.Error(status=422, message='请求参数无效')
    log.error('Agent RPC failed: %s', type(exc).__name__)
    return pb.Error(status=500, message='Agent 服务暂时不可用')


class AgentRpc(api.AgentRpcServicer):
    def __init__(self, application):
        self.app = application

    def chat_request(self, request, user):
        return self.app.ChatRequest(user_id=user.user_id, message=request.message,
            conversation_id=request.conversation_id if request.HasField('conversation_id') else None,
            origin_article_id=request.origin_article_id if request.HasField('origin_article_id') else None,
            image_paths=list(request.image_paths), request_id=request.request_id)

    def resume_request(self, request, user):
        return self.app.ResumeRequest(user_id=user.user_id, conversation_id=request.conversation_id,
            action=request.action, run_id=request.run_id, draft_hash=request.draft_hash,
            edited_draft=decode_object(request.edited_draft) if request.HasField('edited_draft') else None)

    async def invoke(self, method, request):
        user = principal(request.identity)
        app = self.app
        if method == 'ServiceQuery':
            from app.services.service_queries import query
            return await query(request, user.user_id)
        if method in ('Chat', 'ChatStream'):
            fn = app.chat if method == 'Chat' else app.chat_stream
            return await fn(self.chat_request(request, user), user)
        if method in ('Resume', 'ResumeStream'):
            fn = app.chat_resume if method == 'Resume' else app.chat_resume_stream
            return await fn(self.resume_request(request, user), user)
        if method in ('RunStatus', 'RunEvents', 'Recover'):
            run_id = UUID(request.run_id)
            if method == 'RunStatus':
                return await app.run_status(run_id, user)
            if method == 'Recover':
                return await app.recover_run(run_id, user)
            if request.after < 0:
                raise HTTPException(422, '事件游标无效')
            return await app.replay_events(run_id, request.after, user)
        if method == 'RunOverview':
            return await app.run_overview(user)
        if method == 'Conversations':
            if request.scope not in ('all', 'general', 'article') or not 1 <= request.limit <= 100:
                raise HTTPException(422, '会话筛选无效')
            origin = positive(request.origin_article_id) if request.HasField('origin_article_id') else None
            if origin is not None and request.scope == 'general':
                raise HTTPException(422, '普通会话不能指定来源文章')
            last = datetime.fromisoformat(request.last_update_time) if request.HasField('last_update_time') else None
            last_id = positive(request.last_id) if request.HasField('last_id') else None
            return await app.list_conversations(user.user_id, last, last_id, request.limit, request.scope, origin, user)
        if method in ('Memory', 'EditProfile', 'EditMemory', 'DeleteMemory'):
            if method == 'Memory':
                before = positive(request.before) if request.HasField('before') else None
                if not 1 <= request.limit <= 50 or request.kind not in ('all', 'constraint', 'decision', 'event'):
                    raise HTTPException(422, '记忆筛选无效')
                return await app.memory_overview(before, request.limit, request.kind, user)
            edit = decode_object(request.edit)
            if method == 'EditProfile':
                return await app.edit_memory_profile(app.ProfileEdit(**edit), user)
            mid = positive(request.memory_id)
            if method == 'EditMemory':
                return await app.edit_memory_record(app.RecordEdit(**edit), mid, user)
            if len(request.version) != 64 or any(c not in 'abcdef0123456789' for c in request.version):
                raise HTTPException(422, '记忆版本无效')
            return await app.remove_memory_record(mid, request.version, user)
        cid = positive(request.conversation_id)
        if method == 'Cancel':
            return await app.cancel_chat(cid, user.user_id, user)
        if method == 'ConversationRun':
            return await app.conversation_run(cid, user)
        if method == 'Conversation':
            return await app.get_conversation(cid, user.user_id, user)
        if method == 'DeleteConversation':
            return await app.delete_conversation(cid, user.user_id, user)
        if method in ('Messages', 'Questions'):
            before = positive(request.before) if request.HasField('before') else None
            after = positive(request.after) if request.HasField('after') else None
            around = positive(request.around) if request.HasField('around') else None
            snapshot = positive(request.snapshot) if request.HasField('snapshot') else None
            limit = request.limit if request.HasField('limit') else None
            if method == 'Messages':
                if limit is not None and not 1 <= limit <= 50:
                    raise HTTPException(422, '历史分页范围无效')
                return await app.get_messages(cid, user.user_id, user, limit, before, after, around)
            if before is not None or around is not None or limit is None or not 1 <= limit <= 500:
                raise HTTPException(422, '问题分页范围无效')
            return await app.question_index(cid, user.user_id, user, after, limit, snapshot)
        raise HTTPException(404, 'RPC 方法不存在')

    async def unary(self, method, request, context):
        try:
            return pb.Reply(data=encode(await self.invoke(method, request)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return pb.Reply(error=fault(exc))

    async def stream(self, method, request, context):
        iterator = None
        try:
            response = await self.invoke(method, request)
            iterator = response.body_iterator
            async for frame in iterator:
                frame = frame.decode() if isinstance(frame, bytes) else frame
                # Each durable frame is complete. Keep legacy data markers verbatim.
                data = [line[5:].removeprefix(' ') for line in frame.splitlines() if line.startswith('data:')]
                if data:
                    yield pb.Frame(data='\n'.join(data))
                elif frame.startswith(':'):
                    yield pb.Frame(heartbeat=True)
        except asyncio.CancelledError:
            # Disconnecting a subscriber must not cancel its durable Agent run.
            raise
        except Exception as exc:
            yield pb.Frame(error=fault(exc))
        finally:
            if iterator is not None and hasattr(iterator, 'aclose'):
                await iterator.aclose()


def _unary(method):
    async def handler(self, request, context):
        return await self.unary(method, request, context)
    return handler


def _stream(method):
    async def handler(self, request, context):
        async with aclosing(self.stream(method, request, context)) as frames:
            async for frame in frames:
                yield frame
    return handler


for _method in pb.DESCRIPTOR.services_by_name['AgentRpc'].methods:
    setattr(AgentRpc, _method.name, (_stream if _method.server_streaming else _unary)(_method.name))


async def start_server(application):
    server = grpc.aio.server(options=[('grpc.max_receive_message_length', 4 * 1024 * 1024),
                                      ('grpc.max_send_message_length', 8 * 1024 * 1024)])
    api.add_AgentRpcServicer_to_server(AgentRpc(application), server)
    bound = server.add_insecure_port(settings.AGENT_RPC_BIND)
    if not bound:
        raise RuntimeError('Agent RPC 监听地址不可用')
    await server.start()
    log.info('Agent RPC listening on %s', settings.AGENT_RPC_BIND)
    return server
