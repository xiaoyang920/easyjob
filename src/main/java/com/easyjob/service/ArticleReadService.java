package com.easyjob.service;

import com.easyjob.component.ArticleViewSync;
import com.easyjob.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import com.easyjob.mapper.ArticleReadMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.Map;

/** One effective reading per reader/article/Shanghai calendar day, committed with its count. */
@Service
@RequiredArgsConstructor
public class ArticleReadService {
    private final ArticleReadMapper store;
    private final ArticleViewSync viewSync;
    private final ArticleAccessService access;

    @Transactional
    public Map<String, Object> record(Long articleId, Long userId, String readerHash) {
        if (articleId == null || articleId <= 0 || readerHash == null || !readerHash.matches("[a-f0-9]{64}"))
            throw new BusinessException(400, "阅读参数无效");
        // Shared article lock also serializes changes to the existing single-row reading history.
        var rows = store.lockArticle(articleId);
        if (rows.isEmpty() || ((Number) rows.getFirst().get("status")).intValue() != 1
                || ((Number) rows.getFirst().get("deleted")).intValue() != 0)
            throw new BusinessException(404, "文章不存在或不可访问");
        var row = rows.getFirst();
        int count = row.get("view_count") == null ? 0 : ((Number) row.get("view_count")).intValue();
        long author = ((Number) row.get("user_id")).longValue();
        if(!access.canRead(userId,author,((Number)row.get("required_level")).intValue()))
            throw new BusinessException(403,"尚未达到文章阅读等级");
        if (userId != null && userId == author) return Map.of("counted", false, "viewCount", count);
        var day = LocalDate.now(ZoneId.of("Asia/Shanghai"));
        boolean counted = store.insertReceipt(articleId,readerHash,day) == 1;
        if (counted) {
            store.incrementViews(articleId);
            count++;
            if (userId != null) {
                var history = store.findHistory(userId,articleId);
                if (history.isEmpty()) store.insertHistory(userId,articleId,author);
                else store.touchHistory(author,((Number)history.getFirst().get("action_id")).longValue());
            }
            viewSync.enqueue(articleId, count);
        }
        return Map.of("counted", counted, "viewCount", count);
    }
}
