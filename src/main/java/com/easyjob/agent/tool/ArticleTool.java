package com.easyjob.agent.tool;

import com.easyjob.component.EsComponent;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.component.RedisComponent;
import com.easyjob.entity.DocumentChunk;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.service.ArticleService;
import com.easyjob.vo.ArticleCardVO;
import com.easyjob.vo.ArticleDetailVO;
import com.easyjob.vo.ArticleSearchVO;
import com.easyjob.vo.PageVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.List;


@Slf4j
@Component
public class ArticleTool {
    @Autowired
    private ArticleService articleService;
    @Autowired
    private EsVectorStore vectorStore;
    @Autowired
    private EsComponent esComponent;
    @Autowired
    private ArticleMapper articleMapper;
    @Autowired
    private RedisComponent redisComponent;

    /**
     * 关键词搜索文章（使用ES全文搜索）
     */
    @Tool(description = "根据关键词搜索平台上的文章。当用户想查找特定主题的文章时使用。")
    public String searchArticles(
            @ToolParam(description = "搜索关键词") String keyword,
            @ToolParam(description = "返回数量，默认5", required = false) Integer limit,
            ToolContext toolContext
    ) {
        if (limit == null || limit <= 0) {
            limit = 5;
        }
        // 从ToolContext获取会话ID
        Long conversationId = (Long) toolContext.getContext().get("conversationId");
        try {
            // 使用ES搜索，支持中文分词
            PageVO<ArticleSearchVO> pageResult = esComponent.search(false, keyword, null, 1, limit);
            List<ArticleSearchVO> articles = pageResult.getRecords();

            if (articles == null || articles.isEmpty()) {
                return "未找到与\"" + keyword + "\"相关的文章。";
            }
            log.info("tool关键词搜索结果：{}", articles);
            StringBuilder result = new StringBuilder();
            result.append("找到以下相关文章：\n\n");
            
            // 把文章信息保存到ThreadLocal
            List<ArticleCardVO> cards = articles.stream()
                    .map(this::toArticleCard)
                    .toList();
            if (conversationId != null) {
                redisComponent.addArticleCards(conversationId, cards);
            }

            for (int i = 0; i < articles.size(); i++) {
                ArticleSearchVO article = articles.get(i);
                result.append(String.format("%d. 《%s》(文章ID: %s)\n", i + 1, article.getTitle(), article.getArticleId()));
                result.append(String.format("   作者: %s | 阅读: %d | 点赞: %d\n",
                        article.getAuthorName() != null ? article.getAuthorName() : "未知",
                        article.getViewCount() != null ? article.getViewCount() : 0,
                        article.getLikeCount() != null ? article.getLikeCount() : 0));
                result.append(String.format("   摘要: %s\n\n",
                        truncate(article.getSummary(), 100)));
            }

            return result.toString();

        } catch (Exception e) {
            log.error("搜索文章失败", e);
            return "搜索文章时出现错误，请稍后重试。";
        }
    }
    /**
     * 语义搜索文章（RAG）
     */
    @Tool(description = "语义搜索文章。当用户的问题比较模糊，或者想找相关主题的内容时使用。")
    public String semanticSearch(
            @ToolParam(description = "搜索问题或描述") String query,
            @ToolParam(description = "返回数量，默认5", required = false) Integer topK,
            ToolContext toolContext
    ) {
        if (topK == null || topK <= 0) {
            topK = 5;
        }
        Long conversationId = (Long) toolContext.getContext().get("conversationId");

        try {
            List<DocumentChunk> chunks = vectorStore.search(query, topK, 0.7f);

            if (chunks.isEmpty()) {
                return "未找到与您问题相关的内容。";
            }
            log.info("tool语义搜索结果：{}", chunks);
            //去重articleId 批量回查
            List<String> articleIds = chunks.stream().map(DocumentChunk::getArticleId).distinct().toList();
            log.info("准备回查文章，articleIds: {}", articleIds);

            List<ArticleDetailVO> articles = articleMapper.selectArticlesAndUsers(articleIds);
            log.info("回查文章结果，数量: {}, articles: {}", articles.size(), articles);

            if(!articles.isEmpty()){
                List<ArticleCardVO> cards = articles.stream()
                        .map(this::toArticleCard)
                        .toList();
                redisComponent.addArticleCards(conversationId, cards);
            }

            StringBuilder result = new StringBuilder();
            result.append("找到以下相关内容：\n\n");

            for (int i = 0; i < chunks.size(); i++) {
                DocumentChunk chunk = chunks.get(i);
                result.append(String.format("【%d】来自《%s》(文章ID: %s, 相似度: %.0f%%)\n",
                        i + 1, chunk.getTitle(), chunk.getArticleId(), chunk.getScore() * 100));
                result.append(chunk.getContent());
                result.append("\n\n");
            }

            return result.toString();

        } catch (Exception e) {
            log.error("语义搜索失败", e);
            return "搜索时出现错误，请稍后重试。";
        }
    }
    @Tool(description = "获取指定文章的详细内容。当用户想了解某篇文章的具体内容时使用。")
    public String getArticleDetail(@ToolParam(description = "文章ID") Long articleId){
        try {
            ArticleDetailVO  article = articleService.getArticleById(articleId);
            if (article == null) {
                return "未找到该文章。";
            }

            StringBuilder result = new StringBuilder();
            result.append("《").append(article.getTitle()).append("》\n\n");
            result.append("作者: ").append(article.getAuthorName()).append("\n");
            result.append("发布时间: ").append(article.getCreateTime()).append("\n");
            result.append("阅读: ").append(article.getViewCount());
            result.append(" | 点赞: ").append(article.getLikeCount());
            result.append(" | 收藏: ").append(article.getCollectCount()).append("\n\n");
            result.append("--- 正文 ---\n\n");
            result.append(cleanHtml(article.getContent()));

            return result.toString();
         }catch (Exception e) {
            log.error("获取文章详情失败", e);
            return "获取文章详情时出现错误。";
        }
    }
    private ArticleCardVO toArticleCard(ArticleDetailVO article){
        return ArticleCardVO.builder()
                .articleId(article.getArticleId())  // 已经是String
                .title(article.getTitle())
                .coverImage(article.getCoverImage())
                .authorName(article.getAuthorName())
                .summary(truncate(article.getSummary(), 100))
                .viewCount(article.getViewCount())
                .likeCount(article.getLikeCount())
                .build();
    }
    
    private ArticleCardVO toArticleCard(ArticleSearchVO article){
        return ArticleCardVO.builder()
                .articleId(article.getArticleId())  // 已经是String
                .title(article.getTitle())
                .coverImage(article.getCoverImage())
                .authorName(article.getAuthorName())
                .summary(truncate(article.getSummary(), 100))
                .viewCount(article.getViewCount())
                .likeCount(article.getLikeCount())
                .build();
    }
    /**
     * 截断文本
     */
    private String truncate(String text, int maxLength) {
        if (text == null) return "";
        return text.length() > maxLength ? text.substring(0, maxLength) + "..." : text;
    }
    /**
     * 清理HTML标签
     */
    private String cleanHtml(String html){
        if(html== null){
            return "";
        }
        return html.replaceAll("<[^>]+>", "").replaceAll("\\s+", " ").trim();
    }
}
