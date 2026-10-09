package com.easyjob.agent.service;

import com.easyjob.entity.Article;
import com.easyjob.mapper.ArticleMapper;
import org.jsoup.Jsoup;
import org.jsoup.safety.Safelist;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.Map;

@Service
public class AgentDraftService {
    public static final int SUMMARY_MAX_LENGTH = 500;
    private final JdbcTemplate jdbc;
    private final ArticleMapper articles;
    public AgentDraftService(JdbcTemplate jdbc, ArticleMapper articles) { this.jdbc = jdbc; this.articles = articles; }
    public record DraftRequest(String runId, String executionToken, Long articleId,
        String title, String summary, String markdown, String html, String draftHash) {}
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
        return com.easyjob.utils.HtmlContentSanitizer.clean(html, false);
    }
    @Transactional
    public Map<String, String> save(long userId, DraftRequest draft) {
        if (draft.runId() == null || draft.executionToken() == null || draft.articleId() == null || draft.articleId() <= 0
                || draft.title() == null || draft.title().isBlank() || draft.title().length() > 50
                || draft.summary() == null || draft.summary().codePointCount(0, draft.summary().length()) > SUMMARY_MAX_LENGTH || draft.markdown() == null
                || draft.markdown().isBlank() || draft.markdown().length() > 100000
                || draft.html() == null || draft.html().length() > 300000
                || !contentHash(draft).equals(draft.draftHash())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Draft contract failed");
        }
        var rows = jdbc.queryForList("SELECT conversation_id FROM agent_run WHERE run_id=? AND user_id=?", draft.runId(), userId);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        Object cid = rows.getFirst().get("conversation_id");
        var conversations = jdbc.queryForList("SELECT user_id,status FROM ai_conversation WHERE conversation_id=? FOR UPDATE", cid);
        if (conversations.isEmpty() || ((Number) conversations.getFirst().get("user_id")).longValue() != userId
                || ((Number) conversations.getFirst().get("status")).intValue() != 1) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        var run = jdbc.queryForMap("SELECT *, deadline>UTC_TIMESTAMP(6) AS alive FROM agent_run WHERE run_id=? FOR UPDATE", draft.runId());
        if (!draft.draftHash().equals(run.get("draft_hash"))) throw new ResponseStatusException(HttpStatus.CONFLICT, "Approval version changed");
        if (run.get("draft_article_id") != null) return Map.of("articleId", run.get("draft_article_id").toString());
        if (!"running".equals(run.get("status")) || !draft.executionToken().equals(run.get("execution_token"))
                || !(Boolean.TRUE.equals(run.get("alive")) || run.get("alive") instanceof Number n && n.intValue() == 1)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Run cancelled or expired");
        }
        var article = new Article();
        article.setArticleId(draft.articleId()); article.setUserId(userId);
        article.setTitle(draft.title()); article.setSummary(draft.summary());
        article.setContent(cleanHtml(draft.html())); article.setContentType(1);
        article.setStatus(0); article.setDeleted(0);
        article.setCreateTime(LocalDateTime.now()); article.setUpdateTime(LocalDateTime.now());
        articles.insert(article);
        jdbc.update("UPDATE article_info a JOIN user_info u ON u.user_id=a.user_id SET a.data_source=u.data_source WHERE a.article_id=? AND a.user_id=?",draft.articleId(),userId);
        jdbc.update("UPDATE agent_run SET draft_article_id=?,updated_at=UTC_TIMESTAMP(6) WHERE run_id=?", draft.articleId(), draft.runId());
        return Map.of("articleId", draft.articleId().toString());
    }
}
