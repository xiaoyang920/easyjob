"""Pooled asynchronous client for Java's Dubbo Triple business service."""
import grpc
from app.config import settings
from .codec import decode
from .generated import easyjob_rpc_pb2 as pb, easyjob_rpc_pb2_grpc as api
from .peer_pool import PeerPool

_channel = None
_stub = None
def _peer(target):
    channel = grpc.aio.insecure_channel(target, options=[('grpc.enable_retries', 0),
        ('grpc.max_receive_message_length', 8 * 1024 * 1024)])
    return channel, api.BlogRpcStub(channel)


pool = PeerPool(_peer)


class ServiceError(Exception):
    def __init__(self, status, message='内部业务调用失败'):
        super().__init__(message)
        self.status = status


def identity(user_id):
    if len(settings.AGENT_SERVICE_KEY.encode()) < 32 or user_id <= 0:
        raise ServiceError(503, '服务身份未配置')
    from app.services.logging_config import current_trace_id, normalize_trace
    return pb.Identity(user_id=user_id, service_key=settings.AGENT_SERVICE_KEY,
        trace_id=normalize_trace(current_trace_id()))


def client():
    global _channel, _stub
    if _channel is None:
        # No transparent retry: writes are retried only by their durable idempotency contract.
        _channel = grpc.aio.insecure_channel(settings.BLOG_RPC_TARGET,
            options=[('grpc.enable_retries', 0), ('grpc.max_receive_message_length', 8 * 1024 * 1024)])
        _stub = api.BlogRpcStub(_channel)
    return _stub


async def close_client():
    global _channel, _stub, pool
    if _channel is not None:
        await _channel.close()
    _channel = _stub = None
    await pool.close()
    pool = PeerPool(_peer)


async def call(method, request):
    try:
        from .discovery import catalog
        if catalog.enabled:
            target = await catalog.target(request.identity.user_id)
            async with pool.lease(target, catalog.healthy_targets()) as stub:
                reply = await getattr(stub, method)(request, timeout=20)
        else:
            stub = client()
            reply = await getattr(stub, method)(request, timeout=20)
    except RuntimeError:
        raise ServiceError(503) from None
    except grpc.aio.AioRpcError as exc:
        status = 504 if exc.code() == grpc.StatusCode.DEADLINE_EXCEEDED else 503
        raise ServiceError(status) from None
    if reply.HasField('error'):
        raise ServiceError(reply.error.status, reply.error.message)
    if not reply.HasField('data'):
        raise ServiceError(502, '内部业务响应不完整')
    return decode(reply.data)


async def list_drafts(user_id, keyword):
    return await call('ListDrafts', pb.DraftRequest(identity=identity(user_id), keyword=keyword))


async def read_draft(user_id, article_id):
    return await call('ReadDraft', pb.DraftRequest(identity=identity(user_id), article_id=article_id))


async def public_read(kind, *, ids=(), names=(), name='', target_id=0, page=1, limit=20):
    # These methods expose published, unrestricted blog data only. 1 is the service
    # routing key; target_id is data, never a private authorization principal.
    ids=list(ids)
    if len(ids)>128:
        raise ServiceError(400,'查询批次过大')
    if kind=='published' and len(ids)>4:
        rows=[]
        for offset in range(0,len(ids),4):
            rows.extend(await public_read(kind,ids=ids[offset:offset+4],limit=limit))
        return rows
    return await call('ReadPublic', pb.BlogQuery(identity=identity(1), kind=kind,
        ids=[int(i) for i in ids], names=names, name=name, target_id=int(target_id), page=page, limit=limit))


async def maintenance(kind, *, target_id=0, cursor=0, name='', expected=None):
    from .codec import encode
    return await call('Maintenance', pb.BlogQuery(identity=identity(1), kind=kind,
        target_id=target_id, cursor=cursor, name=name, expected=encode(expected or {}).object))


async def save_draft(user_id, body):
    request = pb.DraftRequest(identity=identity(user_id), article_id=int(body['articleId']),
        run_id=body['runId'], execution_token=body['executionToken'], title=body['title'],
        summary=body['summary'], markdown=body['markdown'], html=body['html'], draft_hash=body['draftHash'], save_permit=body.get('savePermit', ''))
    for key, field in [('baseDraftHash', 'base_draft_hash'), ('expectedRevisionId', 'expected_revision_id'),
                       ('expectedLockVersion', 'expected_lock_version')]:
        if body.get(key) is not None:
            setattr(request, field, body[key])
    return await call('SaveDraft', request)


async def draft_receipt(user_id, run_id):
    return await call('DraftReceipt', pb.DraftRequest(identity=identity(user_id),run_id=run_id))
