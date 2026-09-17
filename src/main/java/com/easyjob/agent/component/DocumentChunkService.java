package com.easyjob.agent.component;

import com.easyjob.entity.DocumentChunk;
import com.easyjob.exception.BusinessException;
import lombok.extern.slf4j.Slf4j;
import org.jsoup.Jsoup;
import org.jsoup.safety.Safelist;
import org.springframework.ai.document.Document;
import org.springframework.ai.transformer.splitter.TokenTextSplitter;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 文档分块服务
 *
 * 将文章内容（HTML）清洗后按token数切分为多个DocumentChunk，
 * 供Embedding向量化和ES存储使用。
 */
@Component
@Slf4j
public class DocumentChunkService {

    private final TokenTextSplitter textSplitter;

    public DocumentChunkService() {
        this.textSplitter = TokenTextSplitter.builder()
                .withChunkSize(500)
                .withMinChunkSizeChars(100)
                .withMinChunkLengthToEmbed(50)
                .withMaxNumChunks(50)
                .withKeepSeparator(true)
                .build();
    }

    /**
     * 将文章内容分块
     *
     * @param articleId 文章ID
     * @param title     标题
     * @param content   内容（wangEditor输出的HTML）
     * @param userId    作者ID
     * @param tags      标签列表
     * @return 文档块列表
     */
    public List<DocumentChunk> chunk(String articleId, String title, String content, Long userId, List<String> tags) {
        if (content == null || content.isEmpty()) {
            throw new BusinessException("文章内容不能为空");
        }

        // 1. 预处理：使用Jsoup去除HTML标签，提取纯文本
        String cleanContent = cleanHtml(content);

        if (cleanContent.isEmpty()) {
            throw new BusinessException("文章内容清洗后为空");
        }

        // 2. 使用Spring AI TokenTextSplitter按token数分块
        List<Document> splitDocs = textSplitter.apply(List.of(new Document(cleanContent)));
        List<String> textChunks = splitDocs.stream()
                .map(Document::getText)
                .toList();

        // 3. 如果分块器返回空（内容太短），将整个内容作为一个块
        if (textChunks.isEmpty()) {
            textChunks = List.of(cleanContent);
        }

        // 4. 转换为DocumentChunk
        List<DocumentChunk> chunks = new ArrayList<>();
        for (int i = 0; i < textChunks.size(); i++) {
            DocumentChunk chunk = new DocumentChunk();
            chunk.setArticleId(articleId);
            chunk.setUserId(userId);
            chunk.setTitle(title);
            chunk.setContent(textChunks.get(i));
            chunk.setChunkIndex(i);
            chunk.setTags(tags);
            chunks.add(chunk);
        }

        log.info("文章 {} 分块完成，共 {} 块", articleId, chunks.size());
        return chunks;
    }

    /**
     * 使用Jsoup清理HTML标签，提取纯文本
     *
     * 处理能力：
     * - 嵌套标签、自闭合标签
     * - HTML实体（&nbsp; &amp; &lt; 等）
     * - 保留文本间的自然空格和换行
     */
    private String cleanHtml(String html) {
        if (html == null || html.isEmpty()) {
            return "";
        }
        // 使用 Jsoup 解析并提取纯文本（自动处理所有 HTML 实体）
        String text = Jsoup.parse(html).text();
        // 合并连续空白为单个空格
        text = text.replaceAll("\\s+", " ").trim();
        log.info("cleanHtml 结果: {}", text.substring(0, Math.min(100, text.length())));
        return text;
    }
}
