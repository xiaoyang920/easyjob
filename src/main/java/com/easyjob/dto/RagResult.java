package com.easyjob.dto;

import lombok.Data;

@Data
public class RagResult {
    private String articleId;
    private String title;
    private String chunkContent;
    private Double score;
    
    // 从MySQL回查补充
    private String coverImage;
    private String authorName;
}