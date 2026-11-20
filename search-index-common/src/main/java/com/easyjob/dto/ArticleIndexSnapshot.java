package com.easyjob.dto;

import java.util.List;
import java.util.Objects;

/** Published article data for the search index consumer. A null document means it is no longer published. */
public record ArticleIndexSnapshot(ArticleEsDTO document, int requiredLevel, List<String> tags) {
    public ArticleIndexSnapshot {
        tags = List.copyOf(tags);
    }

    public boolean sameContentAs(ArticleIndexSnapshot other) {
        return document != null && other.document != null
                && requiredLevel == other.requiredLevel && tags.equals(other.tags)
                && Objects.equals(document.getArticleId(), other.document.getArticleId())
                && Objects.equals(document.getUserId(), other.document.getUserId())
                && Objects.equals(document.getTitle(), other.document.getTitle())
                && Objects.equals(document.getContent(), other.document.getContent())
                && Objects.equals(document.getPublishTime(), other.document.getPublishTime())
                && Objects.equals(document.getCategoryId(), other.document.getCategoryId())
                && Objects.equals(document.getTags(), other.document.getTags());
    }

    public record Counts(Boolean published, int likes, int collects) {
        public Counts {
            Objects.requireNonNull(published);
        }
    }

    public record JobState(Boolean completed) {
        public JobState {
            Objects.requireNonNull(completed);
        }
    }
}
