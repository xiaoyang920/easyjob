package com.easyjob.agent;

import com.easyjob.agent.security.*;
import com.easyjob.agent.service.AgentDraftService;
import com.easyjob.agent.service.AgentDraftService.DraftRequest;
import com.easyjob.mapper.AgentDraftMapper;
import com.easyjob.service.ArticleRevisionService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;
import java.util.*;
import java.nio.charset.StandardCharsets;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentBoundaryTests {
    static final String KEY="offline-service-key-32-bytes-long!!";
    final AgentDraftMapper store=mock(AgentDraftMapper.class);
    final ArticleRevisionService revisions=mock(ArticleRevisionService.class);
    final DraftSavePermit verifier=new DraftSavePermit(new AgentServiceAuth(KEY),new ObjectMapper());
    final AgentDraftService service=new AgentDraftService(store,revisions,verifier);
    DraftRequest signed(String summary,String revision,Long lock,long expiry) throws Exception {
        var raw=new DraftRequest("run","token",99L,"标题",summary,"# 标题","<h1>标题</h1>",null);
        String hash=AgentDraftService.contentHash(raw);
        var claims=Map.of("uid",7L,"rid","run","aid",99L,"hash",hash,"revision",revision==null?"":revision,
            "lock",lock==null?"":lock.toString(),"exp",expiry);
        String payload=Base64.getUrlEncoder().withoutPadding().encodeToString(new ObjectMapper().writeValueAsBytes(claims));
        var mac=javax.crypto.Mac.getInstance("HmacSHA256");mac.init(new javax.crypto.spec.SecretKeySpec(KEY.getBytes(StandardCharsets.UTF_8),"HmacSHA256"));
        String permit=payload+"."+Base64.getUrlEncoder().withoutPadding().encodeToString(mac.doFinal(payload.getBytes(StandardCharsets.US_ASCII)));
        when(store.lockReceipt("run")).thenReturn(Map.of("user_id",7L,"article_id",99L,"draft_hash",hash,"completed",0));
        return new DraftRequest("run","token",99L,raw.title(),summary,raw.markdown(),raw.html(),hash,"base",revision,lock,permit);
    }
    DraftRequest signed(String summary) throws Exception { return signed(summary,null,null,java.time.Instant.now().getEpochSecond()+120); }
    @Test void summaryAllows500UnicodeCharactersAndRejects501BeforeSaving() throws Exception {
        for(String c:List.of("摘","🙂")) {
            reset(store,revisions);var d=signed(c.repeat(500));assertEquals("99",service.save(7,d).get("articleId"));
            verify(revisions).create(eq(7L),eq(99L),argThat(r->r.getSummary().equals(c.repeat(500))));
            var bad=signed(c.repeat(501));assertEquals(400,assertThrows(ResponseStatusException.class,()->service.save(7,bad)).getStatusCode().value());
            verify(store,times(1)).complete("run");
        }
    }
    @Test void unicodeDraftHashMatchesPythonGateway() {
        var d=new DraftRequest("run","token",99L,"标题","摘要","# 标题\n正文","<h1>标题</h1>\n<p>正文</p>\n",null);
        assertEquals("8f612bd2cabc3e0c922797bf70bfb67aac75931b79fddcb16053a37fca90f33c",AgentDraftService.contentHash(d));
    }
    @Test void completedReceiptMakesLostResponseRetryIdempotentEvenAfterPermitExpiry() throws Exception {
        var d=signed("摘要");service.save(7,d);
        when(store.receipt("run",7)).thenReturn(Map.of("article_id",99L,"draft_hash",d.draftHash()));
        var expired=signed("摘要",null,null,1);
        assertEquals("99",service.save(7,expired).get("articleId"));
        verify(revisions,times(1)).create(anyLong(),anyLong(),any());verify(store,times(1)).complete("run");
    }
    @Test void missingExpiredOrAlteredPermitCannotStartAWrite() throws Exception {
        var expired=signed("摘要",null,null,1);
        assertEquals(409,assertThrows(ResponseStatusException.class,()->service.save(7,expired)).getStatusCode().value());
        var valid=signed("摘要");var forged=new DraftRequest(valid.runId(),valid.executionToken(),99L,valid.title(),valid.summary(),valid.markdown(),valid.html(),valid.draftHash(),"base",null,null,"forged");
        assertThrows(ResponseStatusException.class,()->service.save(7,forged));
        verify(store,never()).reserve(anyString(),anyLong(),anyLong(),anyString());verifyNoInteractions(revisions);
    }
    @Test void permitBindsOwnerAndRevisionLockWithoutRefreshingConflicts() throws Exception {
        var d=signed("摘要","5",3L,java.time.Instant.now().getEpochSecond()+120);
        assertThrows(ResponseStatusException.class,()->service.save(8,d));
        service.save(7,d);verify(revisions).updateAgentDraft(7L,99L,"5",3L,"标题","摘要","<h1>标题</h1>");
        verify(revisions,never()).ownDraft(anyLong(),anyLong());
    }
    @Test void sameRunCannotCommitDifferentContent() throws Exception {
        var d=signed("摘要");when(store.receipt("run",7)).thenReturn(Map.of("article_id",99L,"draft_hash","another-hash"));
        assertThrows(ResponseStatusException.class,()->service.save(7,d));verifyNoInteractions(revisions);
    }
    @Test void serviceBoundaryRejectsUserJwtAndMissingIdentity() {
        var auth=new AgentServiceAuth(KEY);assertThrows(ResponseStatusException.class,()->auth.verify("user-jwt","7"));
        assertThrows(ResponseStatusException.class,()->auth.verify(KEY,"0"));assertEquals(7,auth.verify(KEY,"7"));
    }
    @Test void htmlSanitizerKeepsCodeAndRemovesActiveContent() {
        var html=AgentDraftService.cleanHtml("<h1>Title</h1><script>bad()</script><p onclick='bad()'>safe</p><pre><code class='language-java'>int n=1;</code></pre><img src='/uploads/image.png'><a href='javascript:bad()'>x</a>");
        assertTrue(html.contains("<h1>Title</h1>"));assertTrue(html.contains("<pre><code"));
        assertFalse(html.contains("script"));assertFalse(html.contains("onclick"));assertTrue(html.contains("/uploads/image.png"));
    }
}
