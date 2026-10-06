package com.easyjob.service;

import com.easyjob.component.ArticleViewSync;
import com.easyjob.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.Map;

/** One effective reading per reader/article/Shanghai calendar day, committed with its count. */
@Service
@RequiredArgsConstructor
public class ArticleReadService {
    private final JdbcTemplate jdbc;
    private final ArticleViewSync viewSync;
    private final ArticleAccessService access;

    @Transactional
    public Map<String, Object> record(Long articleId, Long userId, String readerHash) {
        if (articleId == null || articleId <= 0 || readerHash == null || !readerHash.matches("[a-f0-9]{64}"))
            throw new BusinessException(400, "阅读参数无效");
        // Shared article lock also serializes changes to the existing single-row reading history.
        var rows = jdbc.queryForList("SELECT user_id,status,deleted,view_count,required_level FROM article_info WHERE article_id=? FOR UPDATE", articleId);
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
        boolean counted = jdbc.update("INSERT IGNORE INTO article_read_receipt(article_id,reader_hash,read_day) VALUES (?,?,?)",
                articleId, readerHash, day) == 1;
        if (counted) {
            jdbc.update("UPDATE article_info SET view_count=COALESCE(view_count,0)+1 WHERE article_id=?", articleId);
            count++;
            if (userId != null) {
                var history = jdbc.queryForList("SELECT action_id FROM user_action WHERE user_id=? AND article_id=? AND action_type=7 ORDER BY action_id LIMIT 1", userId, articleId);
                if (history.isEmpty()) jdbc.update("INSERT INTO user_action(user_id,article_id,article_user_id,comment_id,action_type,action_count,action_time) VALUES (?,?,?,0,7,1,NOW())", userId, articleId, author);
                else jdbc.update("UPDATE user_action SET action_time=NOW(),article_user_id=? WHERE action_id=?", author, history.getFirst().get("action_id"));
            }
            viewSync.enqueue(articleId, count);
        }
        return Map.of("counted", counted, "viewCount", count);
    }
}
