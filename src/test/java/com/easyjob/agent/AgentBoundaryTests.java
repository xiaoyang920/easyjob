package com.easyjob.agent;

import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.agent.service.AgentDraftService;
import com.easyjob.entity.Article;
import com.easyjob.mapper.ArticleMapper;
import org.junit.jupiter.api.Test;
import com.easyjob.mapper.AgentDraftMapper;
import org.springframework.web.server.ResponseStatusException;
import java.lang.reflect.Proxy;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class AgentBoundaryTests {
    @Test void summaryAllows500UnicodeCharactersAndRejects501BeforeSaving() {
        for (String character : List.of("摘", "🙂")) {
            var ledger = new DraftLedger();
            List<Article> inserted = new ArrayList<>();
            ArticleMapper mapper = (ArticleMapper) Proxy.newProxyInstance(ArticleMapper.class.getClassLoader(), new Class[]{ArticleMapper.class},
                    (proxy, method, args) -> { if (method.getName().equals("insert")) { inserted.add((Article)args[0]); return 1; } throw new UnsupportedOperationException(); });
            var revisions=org.mockito.Mockito.mock(com.easyjob.service.ArticleRevisionService.class);
            var service = new AgentDraftService(ledger,revisions);
            String summary = character.repeat(500);
            var raw = new AgentDraftService.DraftRequest("run", "token", 99L, "标题", summary, "# 标题", "<h1>标题</h1>", null);
            ledger.hash = AgentDraftService.contentHash(raw);
            var request = new AgentDraftService.DraftRequest("run", "token", 99L, "标题", summary, "# 标题", "<h1>标题</h1>", ledger.hash);
            assertEquals("99", service.save(7, request).get("articleId"));
            var capture=org.mockito.ArgumentCaptor.forClass(com.easyjob.dto.ArticleCreateDTO.class);
            org.mockito.Mockito.verify(revisions).create(org.mockito.ArgumentMatchers.eq(7L),org.mockito.ArgumentMatchers.eq(99L),capture.capture());
            assertEquals(summary,capture.getValue().getSummary());
            var tooLong = new AgentDraftService.DraftRequest("run", "token", 100L, "标题", character.repeat(501), "# 标题", "<h1>标题</h1>", null);
            assertEquals(400, assertThrows(ResponseStatusException.class, () -> service.save(7, tooLong)).getStatusCode().value());
            assertEquals(0, inserted.size());
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
                + "<a href='javascript:bad()'>link</a><pre><code class='language-java'>int n=1;</code></pre><img src='/uploads/image.png'><img src='javascript:bad()' onerror='bad()'>");
        assertTrue(html.contains("<h1>Title</h1>"));
        assertTrue(html.contains("<pre><code"));
        assertFalse(html.contains("script"));
        assertFalse(html.contains("onclick"));
        assertFalse(html.contains("javascript:"));
        assertTrue(html.contains("src=\"/uploads/image.png\""));
        assertFalse(html.contains("onerror"));
    }
    static class DraftLedger implements AgentDraftMapper {
        String status = "running", hash, token = "token";
        Long savedId;
        List<String> queries = new ArrayList<>();
        List<String> updates = new ArrayList<>();
        int writes;
        public List<Map<String,Object>> findRunConversation(String runId,long userId) {
            queries.add("findRunConversation");return List.of(Map.of("conversation_id",11L));
        }
        public List<Map<String,Object>> lockConversation(Long conversationId) {
            queries.add("lockConversation");return List.of(Map.of("user_id",7L,"status",1));
        }
        public Map<String,Object> lockRun(String runId) {
            queries.add("lockRun");
            Map<String,Object> row = new HashMap<>();
            row.put("status", status); row.put("execution_token", token); row.put("draft_hash", hash);
            row.put("draft_article_id", savedId); row.put("alive", 1);
            return row;
        }
        public int recordSavedDraft(Long articleId,String draftHash,String runId) {
            writes++;updates.add("recordSavedDraft");savedId=articleId;return 1;
        }
    }
    @Test void draftCommitIsIdempotentAndUsesHtmlBusinessFormat() {
        var ledger = new DraftLedger();
        List<Article> inserted = new ArrayList<>();
        ArticleMapper mapper = (ArticleMapper) Proxy.newProxyInstance(ArticleMapper.class.getClassLoader(), new Class[]{ArticleMapper.class},
                (proxy, method, args) -> { if (method.getName().equals("insert")) { inserted.add((Article)args[0]); return 1; } throw new UnsupportedOperationException(); });
        var raw = new AgentDraftService.DraftRequest("run", "token", 99L, "A", "S", "# A", "<h1>A</h1>", null);
        ledger.hash = AgentDraftService.contentHash(raw);
        var request = new AgentDraftService.DraftRequest("run", "token", 99L, "A", "S", "# A", "<h1>A</h1>", ledger.hash);
        var revisions=org.mockito.Mockito.mock(com.easyjob.service.ArticleRevisionService.class);
        var service = new AgentDraftService(ledger,revisions);
        assertEquals("99", service.save(7, request).get("articleId"));
        assertEquals("99", service.save(7, request).get("articleId"));
        assertEquals(0, inserted.size()); assertEquals(1, ledger.writes);
        assertEquals(1,ledger.updates.stream().filter(name->name.equals("recordSavedDraft")).count());
        var capture=org.mockito.ArgumentCaptor.forClass(com.easyjob.dto.ArticleCreateDTO.class);
        org.mockito.Mockito.verify(revisions,org.mockito.Mockito.times(1)).create(org.mockito.ArgumentMatchers.eq(7L),org.mockito.ArgumentMatchers.eq(99L),capture.capture());
        assertEquals(1,capture.getValue().getContentType());assertEquals(0,capture.getValue().getStatus());
        assertEquals(List.of("findRunConversation","lockConversation","lockRun"),ledger.queries.subList(0,3));
    }
    @Test void cancelledOrStaleExecutorCannotInsertDraft() {
        var ledger = new DraftLedger();
        ArticleMapper mapper = (ArticleMapper) Proxy.newProxyInstance(ArticleMapper.class.getClassLoader(), new Class[]{ArticleMapper.class},
                (proxy, method, args) -> { fail("No article write allowed"); return null; });
        var raw = new AgentDraftService.DraftRequest("run", "stale", 99L, "A", "S", "# A", "<h1>A</h1>", null);
        ledger.hash = AgentDraftService.contentHash(raw);
        var request = new AgentDraftService.DraftRequest("run", "stale", 99L, "A", "S", "# A", "<h1>A</h1>", ledger.hash);
        var service = new AgentDraftService(ledger,null);
        assertThrows(ResponseStatusException.class, () -> service.save(7, request));
        ledger.token = "stale"; ledger.status = "cancelled";
        assertThrows(ResponseStatusException.class, () -> service.save(7, request));
        assertEquals(0, ledger.writes);
    }

    @Test void editedDraftUsesOriginalApprovalHashAndNewContentHash() {
        var ledger = new DraftLedger();ledger.hash="original-approval";
        var mapper=org.mockito.Mockito.mock(ArticleMapper.class);
        var revisions=org.mockito.Mockito.mock(com.easyjob.service.ArticleRevisionService.class);
        var service=new AgentDraftService(ledger,revisions);
        var raw=new AgentDraftService.DraftRequest("run","token",99L,"手动标题","摘要","手动正文","<p>手动正文</p>",null);
        String editedHash=AgentDraftService.contentHash(raw);
        var request=new AgentDraftService.DraftRequest("run","token",99L,raw.title(),raw.summary(),raw.markdown(),raw.html(),editedHash,ledger.hash,null);
        assertEquals("99",service.save(7,request).get("articleId"));
        org.mockito.Mockito.verify(revisions).create(org.mockito.ArgumentMatchers.eq(7L),org.mockito.ArgumentMatchers.eq(99L),org.mockito.ArgumentMatchers.argThat(a->"手动正文".equals(a.getContent().replaceAll("<[^>]+>",""))));
        // Emulate the committed ledger and retry the same request after response loss.
        ledger.hash=editedHash;
        assertEquals("99",service.save(7,request).get("articleId"));
        org.mockito.Mockito.verify(revisions,org.mockito.Mockito.times(1)).create(org.mockito.ArgumentMatchers.eq(7L),org.mockito.ArgumentMatchers.eq(99L),org.mockito.ArgumentMatchers.any());
        org.mockito.Mockito.verifyNoInteractions(mapper);
    }

    @Test void editingExistingDraftUpdatesSameArticleWithExpectedRevision() {
        var ledger=new DraftLedger();ledger.hash="approved-preview";
        var mapper=org.mockito.Mockito.mock(ArticleMapper.class);
        var revisions=org.mockito.Mockito.mock(com.easyjob.service.ArticleRevisionService.class);
        var raw=new AgentDraftService.DraftRequest("run","token",42L,"修改标题","摘要","修改正文","<p>修改正文</p>",null);
        var request=new AgentDraftService.DraftRequest("run","token",42L,raw.title(),raw.summary(),raw.markdown(),raw.html(),AgentDraftService.contentHash(raw),ledger.hash,"5",3L);
        assertEquals("42",new AgentDraftService(ledger,revisions).save(7,request).get("articleId"));
        org.mockito.Mockito.verify(revisions).updateAgentDraft(7L,42L,"5",3L,"修改标题","摘要","<p>修改正文</p>");
        org.mockito.Mockito.verifyNoInteractions(mapper);
    }

    @Test void changedApprovalHashPreventsAnyArticleWrite() {
        var ledger=new DraftLedger();ledger.hash="new-preview";
        var mapper=org.mockito.Mockito.mock(ArticleMapper.class);
        var raw=new AgentDraftService.DraftRequest("run","token",42L,"标题","摘要","正文","<p>正文</p>",null);
        var request=new AgentDraftService.DraftRequest("run","token",42L,raw.title(),raw.summary(),raw.markdown(),raw.html(),AgentDraftService.contentHash(raw),"old-preview","5");
        assertEquals(409,assertThrows(ResponseStatusException.class,()->new AgentDraftService(ledger,null).save(7,request)).getStatusCode().value());
        org.mockito.Mockito.verifyNoInteractions(mapper);assertEquals(0,ledger.writes);
    }
}
