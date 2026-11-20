package com.easyjob.controller;

import com.easyjob.agent.component.ArticleIndexOutbox;
import com.easyjob.entity.Article;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.ArticleTagMapper;
import com.easyjob.vo.TagVO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.UUID;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class InternalSearchIndexControllerTests {
    private static final String KEY = "index-fixture-key-at-least-32-bytes";
    private static final String HEADER = "X-Search-Index-Key";
    private final ArticleMapper articles = mock(ArticleMapper.class);
    private final ArticleTagMapper tags = mock(ArticleTagMapper.class);
    private final ArticleIndexOutbox outbox = mock(ArticleIndexOutbox.class);
    private MockMvc http;

    @BeforeEach
    void setup() {
        http = MockMvcBuilders.standaloneSetup(new InternalSearchIndexController(articles, tags, outbox, KEY)).build();
    }

    @Test
    void rejectsMissingOrWrongServiceKeyBeforeTouchingData() throws Exception {
        http.perform(get("/internal/search-index/articles/42")).andExpect(status().isUnauthorized());
        http.perform(post("/internal/search-index/jobs/{id}/complete", UUID.randomUUID())
                .param("articleId", "42").header(HEADER, "wrong")).andExpect(status().isUnauthorized());
        verifyNoInteractions(articles, tags, outbox);
    }

    @Test
    void snapshotExposesPublishedDocumentAndTagsButNoUnpublishedContent() throws Exception {
        Article article = new Article();
        article.setArticleId(42L);
        article.setUserId(7L);
        article.setTitle("Example");
        article.setContent("<p>Published content</p>");
        article.setStatus(1);
        article.setDeleted(0);
        article.setRequiredLevel(2);
        TagVO tag = new TagVO();
        tag.setTagName("Java");
        when(articles.selectById(42L)).thenReturn(article);
        when(tags.getTagsByArticleId(42L)).thenReturn(List.of(tag));
        http.perform(get("/internal/search-index/articles/42").header(HEADER, KEY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.document.articleId").value(42))
                .andExpect(jsonPath("$.document.content").value("<p>Published content</p>"))
                .andExpect(jsonPath("$.requiredLevel").value(2))
                .andExpect(jsonPath("$.tags[0]").value("Java"));

        article.setStatus(2);
        http.perform(get("/internal/search-index/articles/42").header(HEADER, KEY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.document").doesNotExist());
        verify(tags, times(1)).getTagsByArticleId(42L);
    }

    @Test
    void readsJobStatusAndReceivesCompletionForExactArticle() throws Exception {
        UUID job = UUID.randomUUID();
        when(outbox.completed(job.toString(), 42L)).thenReturn(true);
        http.perform(get("/internal/search-index/jobs/{id}", job).param("articleId", "42").header(HEADER, KEY))
                .andExpect(status().isOk()).andExpect(jsonPath("$.completed").value(true));
        http.perform(post("/internal/search-index/jobs/{id}/complete", job).param("articleId", "42").header(HEADER, KEY))
                .andExpect(status().isNoContent());
        verify(outbox).complete(job.toString(), 42L);
    }

    @Test
    void failedAcknowledgementReturnsAnHttpFailure() throws Exception {
        UUID job = UUID.randomUUID();
        doThrow(new org.springframework.dao.TransientDataAccessResourceException("fixture failure"))
                .when(outbox).complete(job.toString(), 42L);
        http.perform(post("/internal/search-index/jobs/{id}/complete", job).param("articleId", "42").header(HEADER, KEY))
                .andExpect(status().isServiceUnavailable());
    }
}
