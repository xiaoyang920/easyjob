package com.easyjob.agent;

import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.agent.service.AgentDraftService;
import com.easyjob.entity.Article;
import com.easyjob.mapper.ArticleMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.lang.reflect.Proxy;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class AgentBoundaryTests {
    @Test void summaryAllows500UnicodeCharactersAndRejects501BeforeSaving() {
        for (String character : List.of("摘", "🙂")) {
            var jdbc = new LedgerJdbc();
            List<Article> inserted = new ArrayList<>();
            ArticleMapper mapper = (ArticleMapper) Proxy.newProxyInstance(ArticleMapper.class.getClassLoader(), new Class[]{ArticleMapper.class},
                    (proxy, method, args) -> { if (method.getName().equals("insert")) { inserted.add((Article)args[0]); return 1; } throw new UnsupportedOperationException(); });
            var service = new AgentDraftService(jdbc, mapper);
            String summary = character.repeat(500);
            var raw = new AgentDraftService.DraftRequest("run", "token", 99L, "标题", summary, "# 标题", "<h1>标题</h1>", null);
            jdbc.hash = AgentDraftService.contentHash(raw);
            var request = new AgentDraftService.DraftRequest("run", "token", 99L, "标题", summary, "# 标题", "<h1>标题</h1>", jdbc.hash);
            assertEquals("99", service.save(7, request).get("articleId"));
            assertEquals(summary, inserted.getFirst().getSummary());
            var tooLong = new AgentDraftService.DraftRequest("run", "token", 100L, "标题", character.repeat(501), "# 标题", "<h1>标题</h1>", null);
            assertEquals(400, assertThrows(ResponseStatusException.class, () -> service.save(7, tooLong)).getStatusCode().value());
            assertEquals(1, inserted.size());
        }
    }
    @Test void unicodeDraftHashMatchesPythonGateway() {
        var request = new AgentDraftService.DraftRequest("run", "token", 99L, "标题", "摘要", "# 标题\n正文", "<h1>标题</h1>\n<p>正文</p>\n", null);
        assertEquals("8f612bd2cabc3e0c922797bf70bfb67aac75931b79fddcb16053a37fca90f33c", AgentDraftService.contentHash(request));
    }
    @Test void serviceBoundaryRejectsUserJwtAndMissingIdentity() {
        var auth = new AgentServiceAuth("offline-service-key-32-bytes-long!!");
        assertThrows(ResponseStatusException.class, () -> auth.verify("a-user-jwt", "7"));
        assertThrows(ResponseStatusException.class, () -> auth.verify("offline-service-key-32-bytes-long!!", "0"));
        assertThrows(ResponseStatusException.class, () -> new AgentServiceAuth("").headers(7L));
        assertEquals(7, auth.verify("offline-service-key-32-bytes-long!!", "7"));
    }
    @Test void htmlSanitizerKeepsArticleStructureAndRemovesActiveContent() {
        String html = AgentDraftService.cleanHtml("<h1>Title</h1><script>bad()</script><p onclick='bad()'>safe</p>"
                + "<a href='javascript:bad()'>link</a><pre><code class='language-java'>int n=1;</code></pre><img src='https://tracking/x'>");
        assertTrue(html.contains("<h1>Title</h1>"));
        assertTrue(html.contains("<pre><code"));
        assertFalse(html.contains("script"));
        assertFalse(html.contains("onclick"));
        assertFalse(html.contains("javascript:"));
        assertFalse(html.contains("<img"));
    }
    static class LedgerJdbc extends JdbcTemplate {
        String status = "running", hash, token = "token";
        Long savedId;
        List<String> queries = new ArrayList<>();
        int writes;
        @Override public List<Map<String,Object>> queryForList(String sql, Object... args) {
            queries.add(sql);
            return sql.contains("FROM agent_run") ? List.of(Map.of("conversation_id", 11L)) : List.of(Map.of("user_id", 7L, "status", 1));
        }
        @Override public Map<String,Object> queryForMap(String sql, Object... args) {
            queries.add(sql);
            Map<String,Object> row = new HashMap<>();
            row.put("status", status); row.put("execution_token", token); row.put("draft_hash", hash);
            row.put("draft_article_id", savedId); row.put("alive", 1);
            return row;
        }
        @Override public int update(String sql, Object... args) { writes++; savedId=(Long)args[0]; return 1; }
    }
    @Test void draftCommitIsIdempotentAndUsesHtmlBusinessFormat() {
        var jdbc = new LedgerJdbc();
        List<Article> inserted = new ArrayList<>();
        ArticleMapper mapper = (ArticleMapper) Proxy.newProxyInstance(ArticleMapper.class.getClassLoader(), new Class[]{ArticleMapper.class},
                (proxy, method, args) -> { if (method.getName().equals("insert")) { inserted.add((Article)args[0]); return 1; } throw new UnsupportedOperationException(); });
        var raw = new AgentDraftService.DraftRequest("run", "token", 99L, "A", "S", "# A", "<h1>A</h1>", null);
        jdbc.hash = AgentDraftService.contentHash(raw);
        var request = new AgentDraftService.DraftRequest("run", "token", 99L, "A", "S", "# A", "<h1>A</h1>", jdbc.hash);
        var service = new AgentDraftService(jdbc, mapper);
        assertEquals("99", service.save(7, request).get("articleId"));
        assertEquals("99", service.save(7, request).get("articleId"));
        assertEquals(1, inserted.size()); assertEquals(1, jdbc.writes);
        assertEquals(1, inserted.getFirst().getContentType()); assertEquals(0, inserted.getFirst().getStatus());
        assertTrue(jdbc.queries.get(1).contains("ai_conversation"));
        assertTrue(jdbc.queries.get(1).contains("FOR UPDATE"));
        assertTrue(jdbc.queries.get(2).contains("agent_run"));
        assertTrue(jdbc.queries.get(2).contains("FOR UPDATE"));
    }
    @Test void cancelledOrStaleExecutorCannotInsertDraft() {
        var jdbc = new LedgerJdbc();
        ArticleMapper mapper = (ArticleMapper) Proxy.newProxyInstance(ArticleMapper.class.getClassLoader(), new Class[]{ArticleMapper.class},
                (proxy, method, args) -> { fail("No article write allowed"); return null; });
        var raw = new AgentDraftService.DraftRequest("run", "stale", 99L, "A", "S", "# A", "<h1>A</h1>", null);
        jdbc.hash = AgentDraftService.contentHash(raw);
        var request = new AgentDraftService.DraftRequest("run", "stale", 99L, "A", "S", "# A", "<h1>A</h1>", jdbc.hash);
        var service = new AgentDraftService(jdbc, mapper);
        assertThrows(ResponseStatusException.class, () -> service.save(7, request));
        jdbc.token = "stale"; jdbc.status = "cancelled";
        assertThrows(ResponseStatusException.class, () -> service.save(7, request));
        assertEquals(0, jdbc.writes);
    }
}
