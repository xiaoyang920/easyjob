"""Browser API contract. Calls Agent application functions locally, never Java's proxy."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, StreamingResponse

from app.models.draft import EditedDraft
from app.security.principal import Principal
from app.security.stream_sessions import sessions, guarded_frames
from app.services.editor_tools import EditorSnapshot
from app.services.writing_conversations import WritingContext
from app.services.memory_management import ProfileEdit, RecordEdit


def camel(value):
    parts = value.split('_')
    return parts[0] + ''.join(p.capitalize() for p in parts[1:])


class Input(BaseModel):
    model_config = ConfigDict(alias_generator=camel, populate_by_name=True, extra='forbid')


class ChatInput(Input):
    conversation_id: int | None = Field(default=None, gt=0, lt=2**63)
    origin_article_id: int | None = Field(default=None, gt=0, lt=2**63)
    message: str = Field(min_length=1, max_length=16000)
    image_paths: list[str] | None = Field(default=None, max_length=4)
    request_id: UUID = Field(default_factory=uuid4)
    editor_context: EditorSnapshot | None = None
    writing_context: WritingContext | None = None
    mode: str | None = None  # Kept for existing clients; execution is selected by the Agent.


class ResumeInput(Input):
    conversation_id: int = Field(gt=0, lt=2**63)
    action: str = Field(min_length=1, max_length=4000)
    run_id: UUID
    draft_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    edited_draft: EditedDraft | None = None


class ConversationEdit(Input):
    title: str | None = None
    pinned: bool | None = None
    version: int


class WritingInput(Input):
    article_id: int | None = Field(default=None, gt=0, lt=2**63)


class FeedbackInput(Input):
    rating: Literal['helpful', 'problem', '']
    reason: str = ''
    comment: str = Field(default='', max_length=500)


class DeliveryInput(Input):
    first_answer_ms: int = Field(ge=0, le=3600000, strict=True)


def principal(request: Request):
    identity = getattr(request.state, 'gateway_identity', None)
    if not identity:
        raise HTTPException(401, '请求身份无效')
    return Principal(identity['user_id'])


User = Annotated[Principal, Depends(principal)]
PositiveId = Annotated[int, Path(gt=0, lt=2**63)]
IDS = {'conversationId', 'userId', 'originArticleId', 'writingArticleId', 'messageId', 'draftArticleId', 'articleId'}
CONVERSATION_FIELDS = set('conversationId userId originArticleId originArticleTitle isWriting writingArticleId writingArticleTitle writingArticleAvailable title isPinned metadataVersion messageCount createTime updateTime status'.split())
MESSAGE_FIELDS = set('messageId conversationId role content tokenCount toolCalls imagePaths createTime articleCards draftArticleId citations interrupted interruptPayload isDraft runId runStatus runStartedAt runFinishedAt recoverable agentEvents'.split())


def browser_data(value):
    if isinstance(value, list):
        return [browser_data(v) for v in value]
    if isinstance(value, dict):
        return {k: str(v) if k in IDS and v is not None else browser_data(v) for k, v in value.items()}
    return value


def success(value):
    return JSONResponse({'status': 'success', 'code': 200, 'message': '操作成功',
                         'data': browser_data(jsonable_encoder(value, by_alias=True))})


class SessionStream(StreamingResponse):
    def __init__(self, response, identity):
        super().__init__(response.body_iterator, status_code=response.status_code,
                         media_type='text/event-stream', headers=dict(response.headers), background=response.background)
        self.identity = identity

    async def __call__(self, scope, receive, send):
        async with sessions.subscribe(self.identity) as revoked:
            self.body_iterator = guarded_frames(self.body_iterator, revoked)
            await super().__call__(scope, receive, send)


def stream(response, request):
    return SessionStream(response, request.state.gateway_identity)


async def feature(kind, uid, name='', edit=None, state='', page=1, limit=20):
    # Explicit endpoint -> fixed operation mapping; never expose arbitrary ServiceQuery to browsers.
    from app.rpc.generated import easyjob_rpc_pb2 as pb
    from app.rpc.codec import encode
    from app.services.service_queries import query
    q = pb.AgentQuery(kind=kind, name=name, state=state, page=page, limit=limit)
    if edit is not None:
        q.edit.CopyFrom(encode(edit).object)
    return await query(q, uid)


def router(application):
    api = APIRouter(prefix='/api/agent')

    @api.post('/chat')
    async def chat(body: ChatInput, user: User):
        data = application.ChatRequest(user_id=user.user_id, **body.model_dump(exclude={'mode'}))
        return success(await application.chat(data, user))

    @api.post('/chat/stream')
    async def chat_stream(body: ChatInput, request: Request, user: User):
        data = application.ChatRequest(user_id=user.user_id, **body.model_dump(exclude={'mode'}))
        return stream(await application.chat_stream(data, user), request)

    @api.post('/chat/resume')
    async def resume(body: ResumeInput, user: User):
        data = application.ResumeRequest(user_id=user.user_id, **body.model_dump())
        return success(await application.chat_resume(data, user))

    @api.post('/chat/resume/stream')
    async def resume_stream(body: ResumeInput, request: Request, user: User):
        data = application.ResumeRequest(user_id=user.user_id, **body.model_dump())
        return stream(await application.chat_resume_stream(data, user), request)

    @api.post('/chat/{cid}/cancel')
    async def cancel(cid: PositiveId, user: User):
        return success(await application.cancel_chat(cid, user.user_id, user))

    @api.get('/conversations')
    async def conversations(user: User, last_update_time: datetime | None = Query(default=None, alias='lastUpdateTime'),
                            last_id: int | None = Query(default=None, alias='lastId', gt=0, lt=2**63),
                            limit: int = Query(default=10, ge=1, le=100),
                            scope: Literal['all', 'general', 'article', 'writing'] = 'all',
                            origin_article_id: int | None = Query(default=None, alias='originArticleId', gt=0, lt=2**63),
                            writing_article_id: int | None = Query(default=None, alias='writingArticleId', gt=0, lt=2**63)):
        if last_update_time is not None and last_update_time.tzinfo is not None:
            # Existing cursors use local SQL datetimes, as the Java LocalDateTime adapter did.
            last_update_time = last_update_time.replace(tzinfo=None)
        data = await application.list_conversations(user.user_id, last_update_time, last_id, limit,
                                                    scope, origin_article_id, user, writing_article_id)
        return success([{k: v for k, v in row.items() if k in CONVERSATION_FIELDS} for row in data['data']])

    @api.get('/conversations/{cid}')
    async def conversation(cid: PositiveId, user: User):
        row = (await application.get_conversation(cid, user.user_id, user))['data']
        return success({k: v for k, v in row.items() if k in CONVERSATION_FIELDS})

    @api.delete('/conversations/{cid}')
    async def delete(cid: PositiveId, user: User):
        await application.delete_conversation(cid, user.user_id, user)
        return success(None)

    @api.get('/conversations/{cid}/messages')
    async def messages(cid: PositiveId, user: User, limit: int | None = Query(default=None, ge=1, le=50),
                       before: int | None = Query(default=None, gt=0), after: int | None = Query(default=None, gt=0),
                       around: int | None = Query(default=None, gt=0)):
        data = (await application.get_messages(cid, user.user_id, user, limit, before, after, around))['data']
        if isinstance(data, list):
            data = [{k: v for k, v in row.items() if k in MESSAGE_FIELDS} for row in data]
        return success(data)

    @api.get('/conversations/{cid}/questions')
    async def questions(cid: PositiveId, user: User, limit: int = Query(default=200, ge=1, le=500),
                        after: int | None = Query(default=None, gt=0), snapshot: int | None = Query(default=None, gt=0)):
        return success((await application.question_index(cid, user.user_id, user, after, limit, snapshot))['data'])

    @api.get('/conversations/{cid}/run')
    async def conversation_run(cid: PositiveId, user: User):
        return success(await application.conversation_run(cid, user))

    @api.get('/context-usage')
    async def context_defaults(user: User):
        return success(await application.context_usage_status(None, user))

    @api.get('/conversations/{cid}/context-usage')
    async def context_usage(cid: PositiveId, user: User):
        return success(await application.context_usage_status(cid, user))

    @api.get('/run-overview')
    async def overview(user: User):
        return success(await application.run_overview(user))

    @api.get('/runs/{rid}')
    async def run(rid: UUID, user: User):
        return success(await application.run_status(rid, user))

    @api.get('/runs/{rid}/events')
    async def events(rid: UUID, request: Request, user: User, after: int = Query(default=0, ge=0)):
        return stream(await application.replay_events(rid, after, user), request)

    @api.post('/runs/{rid}/recover')
    async def recover(rid: UUID, request: Request, user: User):
        return stream(await application.recover_run(rid, user), request)

    @api.get('/memory')
    async def memory(user: User, before: int | None = Query(default=None, gt=0),
                     limit: int = Query(default=30, ge=1, le=50),
                     kind: Literal['all', 'constraint', 'decision', 'event'] = 'all'):
        return success(await application.memory_overview(before, limit, kind, user))

    @api.put('/memory/profile')
    async def profile(body: ProfileEdit, user: User):
        return success(await application.edit_memory_profile(body, user))

    @api.put('/memory/records/{mid}')
    async def edit_memory(mid: PositiveId, body: RecordEdit, user: User):
        return success(await application.edit_memory_record(body, mid, user))

    @api.delete('/memory/records/{mid}')
    async def delete_memory(mid: PositiveId, user: User, version: str = Query(pattern=r'^[a-f0-9]{64}$')):
        return success(await application.remove_memory_record(mid, version, user))

    @api.get('/library')
    async def library(user: User, scope: Literal['all', 'general', 'article', 'writing'] = 'all',
                      keyword: str = Query(default='', max_length=80), page: int = Query(default=1, ge=1, le=10000),
                      size: int = Query(default=20, ge=1, le=100)):
        data = await feature('conversation_library', user.user_id, keyword, state=scope, page=page, limit=size)
        data['rows'] = [{k: v for k, v in row.items() if k in CONVERSATION_FIELDS} for row in data['rows']]
        return success(data)

    @api.patch('/conversations/{cid}')
    async def edit_conversation(cid: PositiveId, body: ConversationEdit, user: User):
        return success(await feature('conversation_edit', user.user_id, str(cid), body.model_dump(exclude_none=True)))

    @api.put('/conversations/{cid}/writing-context')
    async def writing(cid: PositiveId, body: WritingInput, user: User):
        return success(await feature('conversation_writing_context', user.user_id, str(cid), body.model_dump()))

    @api.get('/runs/{rid}/feedback')
    async def feedback(rid: UUID, user: User):
        return success(await feature('answer_feedback_get', user.user_id, str(rid), {}))

    @api.put('/runs/{rid}/feedback')
    async def save_feedback(rid: UUID, body: FeedbackInput, user: User):
        return success(await feature('answer_feedback', user.user_id, str(rid), body.model_dump()))

    @api.post('/runs/{rid}/delivery-metrics')
    async def delivery(rid: UUID, body: DeliveryInput, user: User):
        return success(await feature('delivery_metrics', user.user_id, str(rid), body.model_dump()))

    return api


def install(app, application):
    from app.security.gateway import GatewayIdentityMiddleware
    app.add_middleware(GatewayIdentityMiddleware)
    app.include_router(router(application))

    async def error(request, exc):
        public = request.url.path == '/api/agent' or request.url.path.startswith('/api/agent/')
        if not public:
            from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
            if isinstance(exc, RequestValidationError):
                return await request_validation_exception_handler(request, exc)
            if isinstance(exc, StarletteHTTPException):
                return await http_exception_handler(request, exc)
        status = exc.status_code if isinstance(exc, StarletteHTTPException) else 422 if isinstance(exc, (ValidationError, RequestValidationError)) else 503
        message = str(exc.detail) if isinstance(exc, StarletteHTTPException) and status < 500 else (
            '请求参数无效，请检查后重试' if status == 422 else '智能助手服务暂时不可用，请稍后重试')
        return JSONResponse({'status': 'error', 'code': status, 'message': message, 'data': None}, status_code=status)

    app.add_exception_handler(StarletteHTTPException, error)
    app.add_exception_handler(RequestValidationError, error)
    app.add_exception_handler(ValidationError, error)
    app.add_exception_handler(Exception, error)
