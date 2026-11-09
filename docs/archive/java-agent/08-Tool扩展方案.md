> 历史归档：本文包含已移除的 Java Agent 实现，仅供学习参考。当前结构见[运行架构](../../architecture/current-runtime.md)。

# Tool 扩展方案

## 现有 Tool 清单

| Tool | 类 | 方法 | 说明 |
|------|----|------|------|
| 关键词搜索 | ArticleTool | searchArticles | ES 全文搜索，返回文章卡片 |
| 语义搜索 | ArticleTool | semanticSearch | 向量 KNN 搜索，返回相似文档块 |
| 文章详情 | ArticleTool | getArticleDetail | 根据文章ID获取完整内容 |
| 联网搜索 | BochaSearchTool | webSearch | 调用博查 API 获取实时信息 |

---

## 扩展一：HotArticleTool — 热门文章排行

### 功能

用户问"最近什么文章最火"、"热门文章有哪些"、"推荐几篇好文章"时，模型调用此 Tool 按热度排序返回文章。

### 和现有 searchArticles 的区别

`searchArticles` 需要关键词，是"用户知道想找什么"的场景。`getHotArticles` 不需要关键词，是"用户想看推荐"的场景。两者互补，模型会根据用户意图自主选择。

### 代码实现

```java
package com.easyjob.agent.tool;

import com.easyjob.component.RedisComponent;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.vo.ArticleCardVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.List;

@Slf4j
@Component
public class HotArticleTool {

    @Autowired
    private ArticleMapper articleMapper;

    @Autowired
    private RedisComponent redisComponent;

    @Tool(description = "获取平台热门文章排行。当用户想看推荐、热门、排行榜、最受欢迎的文章时使用。不需要关键词。")
    public String getHotArticles(
            @ToolParam(description = "排序方式: view(浏览量)/like(点赞)/collect(收藏)，默认like", required = false) String sortBy,
            @ToolParam(description = "时间范围: day(今日)/week(本周)/month(本月)/all(全部)，默认week", required = false) String timeRange,
            @ToolParam(description = "返回数量，默认10", required = false) Integer limit,
            ToolContext toolContext
    ) {
        // 参数默认值
        if (sortBy == null || sortBy.isBlank()) {
            sortBy = "like";
        }
        if (timeRange == null || timeRange.isBlank()) {
            timeRange = "week";
        }
        if (limit == null || limit <= 0) {
            limit = 10;
        }

        Long conversationId = (Long) toolContext.getContext().get("conversationId");

        try {
            // 映射排序字段
            String orderField = switch (sortBy) {
                case "view" -> "view_count";
                case "collect" -> "collect_count";
                default -> "like_count";
            };

            // 映射时间范围（天数）
            int days = switch (timeRange) {
                case "day" -> 1;
                case "month" -> 30;
                case "all" -> 0; // 0 表示不限
                default -> 7;
            };

            // 查询热门文章（需要在 ArticleMapper 中新增方法）
            List<ArticleCardVO> articles = articleMapper.selectHotArticles(orderField, days, limit);

            if (articles.isEmpty()) {
                return "当前暂无热门文章。";
            }

            // 存入 Redis 供前端展示文章卡片
            if (conversationId != null) {
                redisComponent.addArticleCards(conversationId, articles);
            }

            // 拼接返回给模型的文本
            String sortLabel = switch (sortBy) {
                case "view" -> "浏览量";
                case "collect" -> "收藏数";
                default -> "点赞数";
            };
            String timeLabel = switch (timeRange) {
                case "day" -> "今日";
                case "month" -> "本月";
                case "all" -> "全部时间";
                default -> "本周";
            };

            StringBuilder result = new StringBuilder();
            result.append(String.format("以下是%s热门文章（按%s排序）：\n\n", timeLabel, sortLabel));

            for (int i = 0; i < articles.size(); i++) {
                ArticleCardVO a = articles.get(i);
                result.append(String.format("%d. 《%s》(文章ID: %s)\n", i + 1, a.getTitle(), a.getArticleId()));
                result.append(String.format("   作者: %s | 浏览: %d | 点赞: %d | 收藏: %d\n",
                        a.getAuthorName() != null ? a.getAuthorName() : "未知",
                        a.getViewCount() != null ? a.getViewCount() : 0,
                        a.getLikeCount() != null ? a.getLikeCount() : 0,
                        a.getCollectCount() != null ? a.getCollectCount() : 0));
                if (a.getSummary() != null && !a.getSummary().isBlank()) {
                    result.append(String.format("   摘要: %s\n", a.getSummary()));
                }
                result.append("\n");
            }

            return result.toString();

        } catch (Exception e) {
            log.error("获取热门文章失败", e);
            return "获取热门文章时出现错误，请稍后重试。";
        }
    }
}
```

### 需要新增的 Mapper 方法

`ArticleMapper.java` 新增：

```java
/**
 * 查询热门文章
 * @param orderField 排序字段（like_count/view_count/collect_count）
 * @param days 时间范围（天数，0表示不限）
 * @param limit 返回数量
 */
List<ArticleCardVO> selectHotArticles(@Param("orderField") String orderField,
                                       @Param("days") int days,
                                       @Param("limit") int limit);
```

`ArticleMapper.xml` 新增：

```xml
<select id="selectHotArticles" resultType="com.easyjob.vo.ArticleCardVO">
    SELECT
        a.article_id AS articleId,
        a.title,
        a.cover_image AS coverImage,
        a.summary,
        a.view_count AS viewCount,
        a.like_count AS likeCount,
        a.collect_count AS collectCount,
        u.nick_name AS authorName
    FROM article_info a
    LEFT JOIN user_info u ON a.user_id = u.user_id
    WHERE a.status = 1 AND a.deleted = 0
    <if test="days > 0">
        AND a.publish_time >= DATE_SUB(NOW(), INTERVAL #{days} DAY)
    </if>
    ORDER BY ${orderField} DESC
    LIMIT #{limit}
</select>
```

> 注意：`${orderField}` 用的是 `$` 不是 `#`，因为是列名不能用预编译。orderField 的值来自代码中的 switch 硬编码映射，不存在 SQL 注入风险。

### 注册到 ChatClient

在 `AgentService.chatStream()` 中把 `hotArticleTool` 加入 tools 列表：

```java
@Autowired
private HotArticleTool hotArticleTool;

// chatStream() 中：
.tools(articleTool, bochaSearchTool, hotArticleTool)
```

### ArticleCardVO 补充

现有 `ArticleCardVO` 需要确认是否有 `collectCount` 字段，如果没有需要新增：

```java
// ArticleCardVO.java 中新增
private Integer collectCount;
```

---

## 扩展二：DraftArticleTool — AI 起草文章

### 功能

用户说"帮我写一篇关于 Redis 缓存的文章"、"帮我起草一篇 Spring Boot 入门教程"时，模型调用此 Tool 生成文章草稿并保存到用户的草稿箱。

### 安全设计

这是写入类 Tool，必须做权限控制：
- 通过 ToolContext 获取 userId，只能给当前登录用户创建草稿
- 状态固定为 0（草稿），不会直接发布
- 用户可以在草稿箱中查看、编辑、确认后再发布

### 代码实现

```java
package com.easyjob.agent.tool;

import com.easyjob.entity.Article;
import com.easyjob.mapper.ArticleMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

@Slf4j
@Component
public class DraftArticleTool {

    @Autowired
    private ArticleMapper articleMapper;

    @Tool(description = "帮用户起草文章并保存到草稿箱。当用户明确要求写文章、起草、创作内容时使用。生成的是草稿，用户可以在草稿箱中编辑后再发布。")
    public String createDraft(
            @ToolParam(description = "文章标题") String title,
            @ToolParam(description = "文章正文内容，使用Markdown格式") String content,
            @ToolParam(description = "文章摘要，100字以内") String summary,
            @ToolParam(description = "文章标签，多个用逗号分隔", required = false) String tags,
            ToolContext toolContext
    ) {
        // 1. 从 ToolContext 获取用户ID（权限控制）
        Long userId = (Long) toolContext.getContext().get("userId");
        if (userId == null) {
            return "无法识别当前用户，请先登录。";
        }

        // 2. 参数校验
        if (title == null || title.isBlank()) {
            return "文章标题不能为空。";
        }
        if (content == null || content.isBlank()) {
            return "文章内容不能为空。";
        }
        if (title.length() > 100) {
            title = title.substring(0, 100);
        }
        if (summary != null && summary.length() > 500) {
            summary = summary.substring(0, 500);
        }

        try {
            // 3. 创建草稿
            Article article = new Article();
            article.setUserId(userId);
            article.setTitle(title);
            article.setContent(content);
            article.setSummary(summary);
            article.setTags(tags);
            article.setContentType(2);  // Markdown 格式
            article.setStatus(0);       // 草稿状态
            article.setIsOriginal(1);
            article.setIsTop(0);
            article.setIsEssence(0);
            article.setViewCount(0);
            article.setLikeCount(0);
            article.setCollectCount(0);
            article.setCommentCount(0);
            article.setShareCount(0);
            article.setDeleted(0);
            article.setCreateTime(LocalDateTime.now());
            article.setUpdateTime(LocalDateTime.now());

            articleMapper.insert(article);

            log.info("AI起草文章成功, articleId={}, userId={}, title={}", article.getArticleId(), userId, title);

            return String.format("文章草稿已保存！\n\n" +
                    "标题：%s\n" +
                    "状态：草稿（未发布）\n\n" +
                    "你可以在「草稿箱」中查看和编辑这篇文章，确认无误后再发布。",
                    title);

        } catch (Exception e) {
            log.error("AI起草文章失败, userId={}", userId, e);
            return "保存草稿时出现错误，请稍后重试。";
        }
    }
}
```

### ToolContext 传递 userId

现有代码中 ToolContext 只传了 `conversationId`，需要补充 `userId`。

`AgentService.chatStream()` 中修改：

```java
// 修改前
.toolContext(Map.of("conversationId", finalConversionId))

// 修改后
.toolContext(Map.of(
    "conversationId", finalConversionId,
    "userId", userId
))
```

`AgentService.chat()` 中同样修改。

### 注册到 ChatClient

```java
@Autowired
private DraftArticleTool draftArticleTool;

// chatStream() 中：
.tools(articleTool, bochaSearchTool, hotArticleTool, draftArticleTool)
```

---

## 注册汇总

扩展完成后，`AgentService` 中的 tools 注册：

```java
// 注入
@Autowired
private ArticleTool articleTool;
@Autowired
private BochaSearchTool bochaSearchTool;
@Autowired
private HotArticleTool hotArticleTool;
@Autowired
private DraftArticleTool draftArticleTool;

// 调用时
.tools(articleTool, bochaSearchTool, hotArticleTool, draftArticleTool)
```

模型会根据用户意图自主选择调用哪个 Tool，不需要手动编排。
