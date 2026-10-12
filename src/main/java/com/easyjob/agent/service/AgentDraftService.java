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
    public AgentDraftService(AgentDraftMapper store, ArticleRevisionService revisions) {
        this.store=store;this.revisions=revisions;
    }
    public record DraftRequest(String runId, String executionToken, Long articleId,
        String title, String summary, String markdown, String html, String draftHash,
        String baseDraftHash, String expectedRevisionId, Long expectedLockVersion) {
        public DraftRequest(String runId,String executionToken,Long articleId,String title,String summary,String markdown,String html,String draftHash,String baseDraftHash,String expectedRevisionId) {
            this(runId,executionToken,articleId,title,summary,markdown,html,draftHash,baseDraftHash,expectedRevisionId,null);
        }
        public DraftRequest(String runId,String executionToken,Long articleId,String title,String summary,String markdown,String html,String draftHash) {
            this(runId,executionToken,articleId,title,summary,markdown,html,draftHash,null,null);
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
    @Transactional
    public Map<String, String> save(long userId, DraftRequest draft) {
        if (draft.runId() == null || draft.executionToken() == null || draft.articleId() == null || draft.articleId() <= 0
                || draft.title() == null || draft.title().isBlank() || draft.title().codePointCount(0, draft.title().length()) > 50
                || draft.summary() == null || draft.summary().codePointCount(0, draft.summary().length()) > SUMMARY_MAX_LENGTH || draft.markdown() == null
                || draft.markdown().isBlank() || draft.markdown().codePointCount(0, draft.markdown().length()) > 100000
                || draft.html() == null || draft.html().length() > 300000
                || !contentHash(draft).equals(draft.draftHash())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Draft contract failed");
        }
        var rows = store.findRunConversation(draft.runId(),userId);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        Long cid = ((Number)rows.getFirst().get("conversation_id")).longValue();
        var conversations = store.lockConversation(cid);
        if (conversations.isEmpty() || ((Number) conversations.getFirst().get("user_id")).longValue() != userId
                || ((Number) conversations.getFirst().get("status")).intValue() != 1) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        var run = store.lockRun(draft.runId());
        String baseHash=draft.baseDraftHash()==null?draft.draftHash():draft.baseDraftHash();
        if (!baseHash.equals(run.get("draft_hash")) && !(run.get("draft_article_id")!=null && draft.draftHash().equals(run.get("draft_hash"))))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Approval version changed");
        if (run.get("draft_article_id") != null) return Map.of("articleId", run.get("draft_article_id").toString());
        if (!"running".equals(run.get("status")) || !draft.executionToken().equals(run.get("execution_token"))
                || !(Boolean.TRUE.equals(run.get("alive")) || run.get("alive") instanceof Number n && n.intValue() == 1)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Run cancelled or expired");
        }
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
        store.recordSavedDraft(draft.articleId(),draft.draftHash(),draft.runId());
        return Map.of("articleId", draft.articleId().toString());
    }
}
