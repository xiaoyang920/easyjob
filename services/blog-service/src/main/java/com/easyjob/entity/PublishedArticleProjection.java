package com.easyjob.entity;

import lombok.Builder;
import lombok.Getter;

/** Validated publication content projected from an approved revision. */
@Getter
@Builder
public class PublishedArticleProjection {
    private Long articleId;
    private Long userId;
    private Long revisionId;
    private String title;
    private String summary;
    private String content;
    private Integer contentType;
    private Long categoryId;
    private String coverImage;
    private Integer isOriginal;
    private String tags;
    private Integer requiredLevel;
}
