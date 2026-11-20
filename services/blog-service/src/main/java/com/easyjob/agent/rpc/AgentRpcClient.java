package com.easyjob.agent.rpc;

import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.rpc.v1.AgentQuery;
import com.easyjob.rpc.v1.AgentRpc;
import com.easyjob.rpc.v1.Reply;
import org.apache.dubbo.rpc.RpcException;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.sql.Timestamp;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

/** Internal administrative/profile queries. Browser Agent APIs terminate in Python. */
public final class AgentRpcClient {
    private final AgentRpc remote;
    private final AgentServiceAuth auth;

    public AgentRpcClient(AgentRpc remote, AgentServiceAuth auth) {
        this.remote = com.easyjob.observability.TracingAgentRpc.wrap(remote);
        this.auth = auth;
    }

    public Object edit(long uid, String kind, String name, Map<String, Object> values) {
        return call(() -> remote.serviceQuery(AgentQuery.newBuilder().setIdentity(auth.identity(uid))
            .setKind(kind).setName(name).setEdit(RpcValues.encode(values).getObject()).build()));
    }

    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> serviceRows(String kind, Timestamp start, Timestamp end, String source) {
        return (List<Map<String, Object>>) call(() -> remote.serviceQuery(AgentQuery.newBuilder()
            .setIdentity(auth.identity(1L)).setKind(kind).setStart(start.toLocalDateTime().toString())
            .setEnd(end.toLocalDateTime().toString()).setSource(source).build()));
    }

    public Object serviceQuery(long uid, String kind, String state, String name, int page, int limit, String command) {
        return call(() -> remote.serviceQuery(AgentQuery.newBuilder().setIdentity(auth.identity(uid)).setKind(kind)
            .setState(state).setName(name).setPage(page).setLimit(limit).setSource(command).build()));
    }

    private Object call(Supplier<Reply> action) {
        try {
            Reply reply = action.get();
            if (reply.hasError()) throw failure(reply.getError().getStatus());
            if (!reply.hasData()) throw failure(502);
            return RpcValues.decode(reply.getData());
        } catch (RpcException error) {
            throw failure(error.isTimeout() ? 504 : 503);
        } catch (IllegalStateException unavailable) {
            throw failure(503);
        }
    }

    private ResponseStatusException failure(int code) {
        HttpStatus status = HttpStatus.resolve(code);
        if (status == null || !status.isError()) status = HttpStatus.BAD_GATEWAY;
        String message = switch (code) {
            case 409 -> "操作版本已变化，请刷新后重试";
            case 400, 422 -> "请求参数无效，请检查后重试";
            case 401, 403 -> "无权执行当前操作";
            case 404 -> "请求的资源不存在，或已不可访问";
            case 429 -> "请求过于频繁，请稍后重试";
            case 504 -> "智能助手请求超时，请稍后重试";
            default -> "智能助手服务暂时不可用，请稍后重试";
        };
        return new ResponseStatusException(status.is5xxServerError() && code != 504
            ? HttpStatus.BAD_GATEWAY : status, message);
    }
}
