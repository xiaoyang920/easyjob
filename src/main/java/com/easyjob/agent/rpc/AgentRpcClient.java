package com.easyjob.agent.rpc;

import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.rpc.v1.*;
import org.apache.dubbo.common.stream.StreamObserver;
import org.apache.dubbo.rpc.CancellationContext;
import org.apache.dubbo.rpc.RpcContext;
import org.apache.dubbo.rpc.RpcException;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpMethod;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.util.UriComponentsBuilder;
import reactor.core.publisher.Flux;
import reactor.core.publisher.FluxSink;
import java.time.LocalDateTime;
import java.util.*;
import java.util.function.Consumer;
import java.util.function.Supplier;

/** Typed Protobuf requests; no browser identity and no automatic retry of mutations. */
public final class AgentRpcClient {
    public java.lang.Object edit(long uid,String kind,String name,Map<String,java.lang.Object> values) {
        return call(() -> remote.serviceQuery(AgentQuery.newBuilder().setIdentity(auth.identity(uid))
            .setKind(kind).setName(name).setEdit(RpcValues.encode(values).getObject()).build()));
    }
    private final AgentRpc remote;
    private final AgentServiceAuth auth;
    public AgentRpcClient(AgentRpc remote, AgentServiceAuth auth) { this.remote = remote; this.auth = auth; }
    @SuppressWarnings("unchecked")
    public List<Map<String,java.lang.Object>> serviceRows(String kind,java.sql.Timestamp start,java.sql.Timestamp end,String source) {
        return (List<Map<String,java.lang.Object>>)call(() -> remote.serviceQuery(AgentQuery.newBuilder().setIdentity(auth.identity(1L))
            .setKind(kind).setStart(start.toLocalDateTime().toString()).setEnd(end.toLocalDateTime().toString()).setSource(source).build()));
    }
    public java.lang.Object serviceQuery(long uid,String kind,String state,String name,int page,int limit,String command) {
        return call(() -> remote.serviceQuery(AgentQuery.newBuilder().setIdentity(auth.identity(uid)).setKind(kind)
            .setState(state).setName(name).setPage(page).setLimit(limit).setSource(command).build()));
    }
    public java.lang.Object call(Supplier<Reply> action) {
        try {
            Reply reply = action.get();
            if (reply.hasError()) throw failure(reply.getError().getStatus());
            if (!reply.hasData()) throw failure(502);
            return RpcValues.decode(reply.getData());
        } catch (RpcException e) { throw failure(e.isTimeout() ? 504 : 503); }
        catch(IllegalStateException unavailable) { throw failure(503); }
    }
    private ResponseStatusException failure(int code) {
        HttpStatus status = HttpStatus.resolve(code);
        if (status == null || !status.isError()) status = HttpStatus.BAD_GATEWAY;
        String message = switch (code) {
            case 409 -> "操作版本已变化或当前会话已有运行，请刷新后重试";
            case 400, 422 -> "请求参数无效，请检查后重试";
            case 401, 403 -> "无权执行当前操作";
            case 404 -> "会话、运行或记忆不存在，或已不可访问";
            case 429 -> "请求过于频繁，请稍后重试";
            case 504 -> "智能助手请求超时，可刷新后查看运行进度";
            default -> "智能助手服务暂时不可用，请稍后重试";
        };
        return new ResponseStatusException(status.is5xxServerError() && code != 504 ? HttpStatus.BAD_GATEWAY : status, message);
    }
    private ConversationRequest conversation(Long uid, Long cid) {
        return ConversationRequest.newBuilder().setIdentity(auth.identity(uid)).setConversationId(cid).build();
    }
    private RunRequest run(Long uid, String runId, long after) {
        UUID.fromString(runId);
        if (after < 0) throw failure(400);
        return RunRequest.newBuilder().setIdentity(auth.identity(uid)).setRunId(runId).setAfter(after).build();
    }
    private ChatRequest chat(Long uid, Map<String, java.lang.Object> body) {
        var b = ChatRequest.newBuilder().setIdentity(auth.identity(uid)).setMessage((String)body.get("message"))
                .setRequestId((String)body.get("request_id"));
        if (body.get("conversation_id") != null) b.setConversationId(((Number)body.get("conversation_id")).longValue());
        if (body.get("origin_article_id") != null) b.setOriginArticleId(((Number)body.get("origin_article_id")).longValue());
        for (var image : (List<?>)body.getOrDefault("image_paths", List.of())) b.addImagePaths(image.toString());
        return b.build();
    }
    private ResumeRequest resume(Long uid, Map<String, java.lang.Object> body) {
        var b = ResumeRequest.newBuilder().setIdentity(auth.identity(uid))
                .setConversationId(((Number)body.get("conversation_id")).longValue())
                .setAction((String)body.get("action")).setRunId((String)body.get("run_id"))
                .setDraftHash((String)body.get("draft_hash"));
        if (body.get("edited_draft") != null) b.setEditedDraft(RpcValues.encode(body.get("edited_draft")).getObject());
        return b.build();
    }
    public java.lang.Object post(String path, Long uid, Map<String, java.lang.Object> body) {
        if (path.equals("/chat")) return call(() -> remote.chat(chat(uid, body)));
        if (path.equals("/chat/resume")) return call(() -> remote.resume(resume(uid, body)));
        if (path.matches("/chat/\\d+/cancel\\?user_id=\\d+"))
            return call(() -> remote.cancel(conversation(uid, Long.parseLong(path.split("/")[2]))));
        throw failure(400);
    }
    public java.lang.Object runStatus(Long uid, String id) { return call(() -> remote.runStatus(run(uid,id,0))); }
    public java.lang.Object overview(Long uid) {
        return call(() -> remote.runOverview(UserRequest.newBuilder().setIdentity(auth.identity(uid)).build()));
    }
    public java.lang.Object conversationRun(Long uid, Long cid) { return call(() -> remote.conversationRun(conversation(uid,cid))); }
    public java.lang.Object getConversation(Long uid, Long cid) { return call(() -> remote.conversation(conversation(uid,cid))); }
    public void deleteConversation(Long uid, Long cid) { call(() -> remote.deleteConversation(conversation(uid,cid))); }
    public java.lang.Object conversations(Long uid, LocalDateTime time, Long id, int limit, String scope, Long origin) {
        var b = ConversationsRequest.newBuilder().setIdentity(auth.identity(uid)).setScope(scope).setLimit(limit);
        if (time != null) b.setLastUpdateTime(time.toString());
        if (id != null) b.setLastId(id);
        if (origin != null) b.setOriginArticleId(origin);
        return call(() -> remote.conversations(b.build()));
    }
    public java.lang.Object history(Long uid, Long cid, boolean questions, Integer limit, Long before, Long after, Long around, Long snapshot) {
        var b = HistoryRequest.newBuilder().setIdentity(auth.identity(uid)).setConversationId(cid);
        if (limit != null) b.setLimit(limit);
        if (before != null) b.setBefore(before);
        if (after != null) b.setAfter(after);
        if (around != null) b.setAround(around);
        if (snapshot != null) b.setSnapshot(snapshot);
        return call(() -> questions ? remote.questions(b.build()) : remote.messages(b.build()));
    }
    public java.lang.Object memory(Long uid, HttpMethod method, String path, Map<String,java.lang.Object> body) {
        var uri = UriComponentsBuilder.fromUriString(path).build();
        var query = uri.getQueryParams();
        var b = MemoryRequest.newBuilder().setIdentity(auth.identity(uid));
        if (body != null) b.setEdit(RpcValues.encode(body).getObject());
        if (method == HttpMethod.GET && "/memory".equals(uri.getPath())) {
            b.setLimit(Integer.parseInt(query.getFirst("limit"))).setKind(query.getFirst("kind"));
            if (query.containsKey("before")) b.setBefore(Long.parseLong(query.getFirst("before")));
            return call(() -> remote.memory(b.build()));
        }
        if (method == HttpMethod.PUT && "/memory/profile".equals(uri.getPath())) return call(() -> remote.editProfile(b.build()));
        if (uri.getPath() != null && uri.getPath().matches("/memory/records/\\d+")) {
            b.setMemoryId(Long.parseLong(uri.getPath().substring("/memory/records/".length())));
            if (method == HttpMethod.PUT) return call(() -> remote.editMemory(b.build()));
            if (method == HttpMethod.DELETE && query.getFirst("version") != null) {
                b.setVersion(query.getFirst("version")); return call(() -> remote.deleteMemory(b.build()));
            }
        }
        throw failure(400);
    }
    public Flux<String> stream(String path, Long uid, Map<String,java.lang.Object> body) {
        return stream(observer -> {
            switch (path) {
                case "/chat/stream" -> remote.chatStream(chat(uid,body),observer);
                case "/chat/resume/stream" -> remote.resumeStream(resume(uid,body),observer);
                default -> {
                    if (!path.matches("/runs/[^/]+/recover")) throw failure(400);
                    remote.recover(run(uid,path.split("/")[2],0),observer);
                }
            }
        });
    }
    public Flux<String> events(Long uid, String id, long after) {
        return stream(observer -> remote.runEvents(run(uid,id,after),observer));
    }
    private Flux<String> stream(Consumer<StreamObserver<Frame>> invoke) {
        String traceId=com.easyjob.observability.RequestTrace.current();
        return Flux.<String>create(sink -> {
            var cancellation = new CancellationContext();
            sink.onDispose(() -> cancellation.cancel(new java.util.concurrent.CancellationException("Subscriber disconnected")));
            var previous = RpcContext.getCancellationContext();
            RpcContext.restoreCancellationContext(cancellation);
            try (var trace=new com.easyjob.observability.RequestTrace(traceId,null)) {
                invoke.accept(new StreamObserver<>() {
                    public void onNext(Frame frame) {
                        if (frame.hasError()) sink.error(failure(frame.getError().getStatus()));
                        else if (frame.hasData()) sink.next(frame.getData());
                        else if (frame.hasHeartbeat()) sink.next("");
                    }
                    public void onError(Throwable error) { sink.error(failure(503)); }
                    public void onCompleted() { sink.complete(); }
                });
            } catch (Exception e) { sink.error(e instanceof ResponseStatusException ? e : failure(503)); }
            finally { RpcContext.restoreCancellationContext(previous); }
        }, FluxSink.OverflowStrategy.ERROR).onBackpressureBuffer(256);
    }
}
