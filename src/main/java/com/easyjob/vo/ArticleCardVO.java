package com.easyjob.vo;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.Builder;
import lombok.NoArgsConstructor;

/**
 * 文章卡片VO（用于AI聊天展示）
 */
@Data
@Builder
@NoArgsConstructor   // 新增
@AllArgsConstructor  // 新增
public class ArticleCardVO {
    private String articleId;    // 文章ID（String避免JS精度丢失）
    private String title;        // 标题
    private String coverImage;   // 封面图URL
    private String authorName;   // 作者名
    private String summary;      // 摘要（截取前100字）
    private Integer viewCount;   // 阅读数
    private Integer likeCount;   // 点赞数
}