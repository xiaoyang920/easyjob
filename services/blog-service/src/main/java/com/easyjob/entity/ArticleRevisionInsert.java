package com.easyjob.entity;

import lombok.Builder;
import lombok.Data;

/** Parameters for a new working revision; revisionId is filled by MyBatis. */
@Data
@Builder
public class ArticleRevisionInsert {
    private Long revisionId;
    private String clientRequestId;
    private Long articleId;
    private Integer version;
    private Long authorId;
    private Long baseRevisionId;
    private Integer state;
    private String payload;
    private String contentHash;
    private Integer requiredLevel;
}
