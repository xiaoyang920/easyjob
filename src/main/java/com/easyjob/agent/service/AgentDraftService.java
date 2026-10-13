package com.easyjob.agent.service;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Map;
import com.easyjob.service.ArticleRevisionService;
import com.easyjob.mapper.AgentDraftMapper;

@Service
public class AgentDraftService {
    public static final int SUMMARY_MAX_LENGTH = 500;
    private final AgentDraftMapper store;
    private final ArticleRevisionService revisions;
    private final com.easyjob.agent.security.DraftSavePermit permits;
    public AgentDraftService(AgentDraftMapper store, ArticleRevisionService revisions, com.easyjob.agent.security.DraftSavePermit permits) {
        this.store=store;this.revisions=revisions;this.permits=permits;
    }
    public record DraftRequest(String runId, String executionToken, Long articleId,
        String title, String summary, String markdown, String html, String draftHash,
        String baseDraftHash, String expectedRevisionId, Long expectedLockVersion, String savePermit) {
        public DraftRequest(String runId,String executionToken,Long articleId,String title,String summary,String markdown,String html,String draftHash,String baseDraftHash,String expectedRevisionId,Long expectedLockVersion) {
            this(runId,executionToken,articleId,title,summary,markdown,html,draftHash,baseDraftHash,expectedRevisionId,expectedLockVersion,null);
        }
        public DraftRequest(String runId,String executionToken,Long articleId,String title,String summary,String markdown,String html,String draftHash,String baseDraftHash,String expectedRevisionId) {
            this(runId,executionToken,articleId,title,summary,markdown,html,draftHash,baseDraftHash,expectedRevisionId,null,null);
        }
        public DraftRequest(String runId,String executionToken,Long articleId,String title,String summary,String markdown,String html,String draftHash) {
            this(runId,executionToken,articleId,title,summary,markdown,html,draftHash,null,null,null,null);
        }
    }
    public static String contentHash(DraftRequest draft) {
        try {
            var hasher = MessageDigest.getInstance("SHA-256");
            for (String field : new String[]{draft.title(), draft.summary(), draft.markdown(), draft.html()}) {
                byte[] value = field.getBytes(StandardCharsets.UTF_8);
                hasher.update(java.nio.ByteBuffer.allocate(4).putInt(value.length).array());
                hasher.update(value);
            }
            return HexFormat.of().formatHex(hasher.digest());
        } catch (Exception e) { throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid draft"); }
    }
    public static String cleanHtml(String html) {
        return com.easyjob.utils.HtmlContentSanitizer.clean(html, true);
    }
    public Map<String,String> receipt(long uid,String runId) {
        var found=store.receipt(runId,uid);
        return found==null || found.isEmpty()?null:Map.of("articleId",found.get("article_id").toString(),"draftHash",found.get("draft_hash").toString());
    }
    @Transactional(timeout=20)
    public Map<String, String> save(long userId, DraftRequest draft) {
        if (draft.runId() == null || draft.executionToken() == null || draft.articleId() == null || draft.articleId() <= 0
                || draft.title() == null || draft.title().isBlank() || draft.title().codePointCount(0, draft.title().length()) > 50
                || draft.summary() == null || draft.summary().codePointCount(0, draft.summary().length()) > SUMMARY_MAX_LENGTH || draft.markdown() == null
                || draft.markdown().isBlank() || draft.markdown().codePointCount(0, draft.markdown().length()) > 100000
                || draft.html() == null || draft.html().length() > 300000
                || !contentHash(draft).equals(draft.draftHash())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Draft contract failed");
        }
        var previous=receipt(userId,draft.runId());
        if(previous!=null) {
            if(!previous.get("draftHash").equals(draft.draftHash()) || !previous.get("articleId").equals(draft.articleId().toString()))
                throw new ResponseStatusException(HttpStatus.CONFLICT,"Save identity changed");
            return Map.of("articleId",previous.get("articleId"));
        }
        permits.verify(userId,draft);
        store.reserve(draft.runId(),userId,draft.articleId(),draft.draftHash());
        var reserved=store.lockReceipt(draft.runId());
        if(((Number)reserved.get("user_id")).longValue()!=userId || !draft.draftHash().equals(reserved.get("draft_hash"))
            || ((Number)reserved.get("article_id")).longValue()!=draft.articleId()) throw new ResponseStatusException(HttpStatus.CONFLICT);
        if(((Number)reserved.get("completed")).intValue()==1) return Map.of("articleId",draft.articleId().toString());
        if(draft.expectedRevisionId()!=null) {
            if(revisions==null)throw new IllegalStateException("Missing revision service");
            revisions.updateAgentDraft(userId,draft.articleId(),draft.expectedRevisionId(),draft.expectedLockVersion(),draft.title(),draft.summary(),cleanHtml(draft.html()));
        } else {
            if(revisions==null)throw new IllegalStateException("Missing revision service");
            var request=new com.easyjob.dto.ArticleCreateDTO();
            request.setTitle(draft.title());request.setSummary(draft.summary());
            request.setContent(cleanHtml(draft.html()));request.setContentType(1);request.setStatus(0);
            revisions.create(userId,draft.articleId(),request);
        }
        store.complete(draft.runId());
        return Map.of("articleId", draft.articleId().toString());
    }
}
