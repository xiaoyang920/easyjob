package com.easyjob.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class ArticleVectorMessage {
    
    /**
     * 文章ID
     */
    private Long articleId;
    
    /**
     * 操作类型: PUBLISH / UPDATE / DELETE
     */
    private String action;
}