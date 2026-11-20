package com.easyjob.dto;

import com.alibaba.fastjson2.annotation.JSONField;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * ES文档 - 文章
 */
@Data
@NoArgsConstructor
public class ArticleEsDTO {
    
    private Long articleId;
    
    private Long userId;
    
    private String title;
    
    private String coverImage;
    
    private String summary;
    
    private String content;
    
    private Integer contentType;
    
    private Long categoryId;
    
    private String tags;
    
    private Integer viewCount;
    
    private Integer likeCount;
    
    private Integer collectCount;
    
    private Integer commentCount;
    
    private Integer shareCount;
    
    private Integer status;
    
    private Integer isTop;
    
    private Integer isEssence;
    
    private Integer isOriginal;

    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
    @JSONField(format = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime publishTime;

    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
    @JSONField(format = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
    @JSONField(format = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
    
}
