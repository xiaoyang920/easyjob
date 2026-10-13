package com.easyjob.agent.rpc;

import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.agent.service.AgentDraftService;
import com.easyjob.exception.BusinessException;
import com.easyjob.service.ArticleRevisionService;
import com.easyjob.rpc.v1.*;
import org.springframework.web.server.ResponseStatusException;
import java.util.function.Supplier;

/** Reuses the business service transaction, approval hash and optimistic lock checks. */
public class BlogRpcProvider extends DubboBlogRpcTriple.BlogRpcImplBase {
    private final AgentServiceAuth auth;
    private final AgentDraftService drafts;
    private final ArticleRevisionService revisions;
    private com.easyjob.agent.service.AgentBlogQueryService queries;
    public BlogRpcProvider queries(com.easyjob.agent.service.AgentBlogQueryService value) { queries=value; return this; }
    public BlogRpcProvider(AgentServiceAuth auth, AgentDraftService drafts, ArticleRevisionService revisions) {
        this.auth = auth; this.drafts = drafts; this.revisions = revisions;
    }
    private long user(DraftRequest request) {
        var identity = request.getIdentity();
        return auth.verify(identity.getServiceKey(), Long.toString(identity.getUserId()));
    }
    private Reply reply(Supplier<java.lang.Object> action) {
        try { return Reply.newBuilder().setData(RpcValues.encode(action.get())).build(); }
        catch (ResponseStatusException e) { return error(e.getStatusCode().value(), "草稿操作未完成"); }
        catch (BusinessException e) { return error(e.getCode(), e.getMessage()); }
        catch (Exception e) { return error(500, "草稿服务暂时不可用"); }
    }
    private Reply error(int status, String message) {
        return Reply.newBuilder().setError(com.easyjob.rpc.v1.Error.newBuilder().setStatus(status).setMessage(message)).build();
    }
    @Override public Reply listDrafts(DraftRequest r) {
        return reply(() -> revisions.ownDrafts(user(r), r.getKeyword()));
    }
    @Override public Reply readDraft(DraftRequest r) {
        return reply(() -> revisions.ownDraft(user(r), r.getArticleId()));
    }
    @Override public Reply saveDraft(DraftRequest r) {
        return reply(() -> drafts.save(user(r), new AgentDraftService.DraftRequest(
                r.getRunId(), r.getExecutionToken(), r.getArticleId(), r.getTitle(), r.getSummary(),
                r.getMarkdown(), r.getHtml(), r.getDraftHash(), r.hasBaseDraftHash() ? r.getBaseDraftHash() : null,
                r.hasExpectedRevisionId() ? r.getExpectedRevisionId() : null,
                r.hasExpectedLockVersion() ? r.getExpectedLockVersion() : null,r.getSavePermit())));
    }
    @Override public Reply draftReceipt(DraftRequest r) { return reply(() -> drafts.receipt(user(r),r.getRunId())); }
    @Override public Reply readPublic(BlogQuery r) {
        return reply(() -> { auth.verify(r.getIdentity().getServiceKey(),Long.toString(r.getIdentity().getUserId())); return queries.read(r); });
    }
    @Override public Reply maintenance(BlogQuery r) {
        return reply(() -> { auth.verify(r.getIdentity().getServiceKey(),Long.toString(r.getIdentity().getUserId())); return queries.maintenance(r); });
    }
}
