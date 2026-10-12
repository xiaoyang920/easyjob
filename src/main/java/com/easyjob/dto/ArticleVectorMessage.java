package com.easyjob.dto;

import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
public class ArticleVectorMessage {
    
    /**
     * 文章ID
     */
    private Long articleId;
    
    /**
     * 操作类型: PUBLISH / UPDATE / DELETE / COUNTS（只刷新热度，不生成向量）
     */
    private String action;
    private String indexJobId;

    public ArticleVectorMessage(Long articleId, String action) {
        this.articleId = articleId;
        this.action = action;
    }
}
