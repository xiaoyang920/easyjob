package com.easyjob.controller;

import com.easyjob.agent.component.ArticleIndexOutbox;
import com.easyjob.dto.ArticleEsDTO;
import com.easyjob.dto.ArticleIndexSnapshot;
import com.easyjob.entity.Article;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.ArticleTagMapper;
import com.easyjob.vo.TagVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

@RestController
@RequestMapping("/internal/search-index")
@Slf4j
public class InternalSearchIndexController {
    private final ArticleMapper articles;
    private final ArticleTagMapper tags;
    private final ArticleIndexOutbox outbox;
    private final byte[] key;

    public InternalSearchIndexController(ArticleMapper articles, ArticleTagMapper tags, ArticleIndexOutbox outbox,
                                         @Value("${SEARCH_INDEX_SERVICE_KEY:}") String key) {
        this.articles = articles;
        this.tags = tags;
        this.outbox = outbox;
        this.key = key.getBytes(StandardCharsets.UTF_8);
    }

    @GetMapping("/articles/{articleId}")
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public ArticleIndexSnapshot snapshot(@RequestHeader(value = "X-Search-Index-Key", defaultValue = "") String supplied,
                                         @PathVariable long articleId) {
        authorize(supplied);
        Article article = articles.selectById(articleId);
        if (!published(article)) {
            return new ArticleIndexSnapshot(null, 0, List.of());
        }
        ArticleEsDTO document = new ArticleEsDTO();
        BeanUtils.copyProperties(article, document);
        List<String> tagNames = tags.getTagsByArticleId(articleId).stream().map(TagVO::getTagName).toList();
        int level = Objects.requireNonNullElse(article.getRequiredLevel(), 0);
        return new ArticleIndexSnapshot(document, level, tagNames);
    }

    @GetMapping("/articles/{articleId}/counts")
    public ArticleIndexSnapshot.Counts counts(@RequestHeader(value = "X-Search-Index-Key", defaultValue = "") String supplied,
                                              @PathVariable long articleId) {
        authorize(supplied);
        Article article = articles.selectInteractionCounts(articleId);
        if (!published(article)) {
            return new ArticleIndexSnapshot.Counts(false, 0, 0);
        }
        return new ArticleIndexSnapshot.Counts(true, Math.max(0, Objects.requireNonNullElse(article.getLikeCount(), 0)),
                Math.max(0, Objects.requireNonNullElse(article.getCollectCount(), 0)));
    }

    @GetMapping("/jobs/{jobId}")
    public ArticleIndexSnapshot.JobState job(@RequestHeader(value = "X-Search-Index-Key", defaultValue = "") String supplied,
                                             @PathVariable UUID jobId, @RequestParam long articleId) {
        authorize(supplied);
        return new ArticleIndexSnapshot.JobState(outbox.completed(jobId.toString(), articleId));
    }

    @PostMapping("/jobs/{jobId}/complete")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void complete(@RequestHeader(value = "X-Search-Index-Key", defaultValue = "") String supplied,
                         @PathVariable UUID jobId, @RequestParam long articleId) {
        authorize(supplied);
        outbox.complete(jobId.toString(), articleId);
    }

    @GetMapping("/ready")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void ready(@RequestHeader(value = "X-Search-Index-Key", defaultValue = "") String supplied) {
        authorize(supplied);
    }

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<Void> requestRejected(ResponseStatusException failure) {
        return ResponseEntity.status(failure.getStatusCode()).build();
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Void> requestFailed(Exception failure) {
        log.warn("Internal index request failed: {}", failure.getClass().getSimpleName());
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).build();
    }

    private void authorize(String supplied) {
        if (key.length < 32 || !MessageDigest.isEqual(key, supplied.getBytes(StandardCharsets.UTF_8))) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
        }
    }

    private boolean published(Article article) {
        return article != null && Objects.equals(article.getStatus(), 1) && Objects.equals(article.getDeleted(), 0);
    }
}
