package com.easyjob.entity;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 文档块实体
 * 
 * 一篇文章会被切分成多个DocumentChunk存储
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class DocumentChunk {
    
    /**
     * 原文章ID
     */
    @JsonProperty("article_id")
    private String articleId;
    
    /**
     * 作者ID
     */
    @JsonProperty("user_id")
    private Long userId;
    
    /**
     * 文章标题
     */
    private String title;
    
    /**
     * 块内容
     */
    @JsonProperty("chunk_content")
    private String content;
    
    /**
     * 块索引 (第几块)
     */
    @JsonProperty("chunk_index")
    private Integer chunkIndex;
    
    /**
     * 内容向量
     */
    @JsonProperty("content_vector")
    private List<Double> vector;
    
    /**
     * 来源类型: article(平台文章), external(外部文档)
     */
    @JsonProperty("source_type")
    private String sourceType = "article";
    
    /**
     * 标签
     */
    private List<String> tags;
    
    /**
     * 创建时间
     */
    @JsonProperty("create_time")
    private LocalDateTime createTime;
    
    /**
     * 点赞数
     */
    @JsonProperty("like_count")
    private Integer likeCount = 0;
    
    /**
     * 收藏数
     */
    @JsonProperty("collect_count")
    private Integer collectCount = 0;
    
    /**
     * 搜索得分 (查询时填充，不存储在ES中)
     */
    @JsonIgnore
    private Double score;
    
    /**
     * 转换为ES文档格式
     */
    public Map<String, Object> toEsDocument() {
        Map<String, Object> doc = new HashMap<>();
        doc.put("chunk_id", articleId + "_" + chunkIndex);
        doc.put("article_id", articleId);
        doc.put("user_id", userId);
        doc.put("title", title);
        doc.put("chunk_content", content);
        doc.put("chunk_index", chunkIndex);
        doc.put("content_vector", vector);
        doc.put("source_type", sourceType);
        doc.put("tags", tags);
        doc.put("create_time", createTime);
        doc.put("like_count", likeCount != null ? likeCount : 0);
        doc.put("collect_count", collectCount != null ? collectCount : 0);
        return doc;
    }
}