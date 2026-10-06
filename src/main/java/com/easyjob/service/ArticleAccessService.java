package com.easyjob.service;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.exception.BusinessException;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.vo.ArticleDetailVO;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.*;

@Service @RequiredArgsConstructor
public class ArticleAccessService {
    private final JdbcTemplate jdbc;
    private final ReadingGrowthService growth;
    private final RedisComponent redis;
    private final ArticleIndexPublisher index;
    public record Reader(int level, boolean admin) {}
    public Reader reader(Long uid) {
        if (uid == null) return new Reader(0, false);
        return new Reader(((Number)growth.summary(uid).get("level")).intValue(), isAdmin(uid));
    }
    public boolean isAdmin(Long uid) {
        return uid!=null && !jdbc.queryForList("SELECT user_id FROM user_info WHERE user_id=? AND role=2 AND status=1",uid).isEmpty();
    }
    public boolean canRead(Long uid,Long author,int required) {
        return required==0 || (uid!=null && uid.equals(author)) || isAdmin(uid)
                || ((Number)growth.summary(uid).get("level")).intValue()>=required;
    }
    public void apply(ArticleDetailVO detail,Long uid,Long author,int required) {
        var progress=growth.summary(uid); int level=((Number)progress.get("level")).intValue();
        boolean admin=isAdmin(uid);
        boolean allowed=required==0 || (uid!=null && uid.equals(author)) || admin || level>=required;
        detail.setRequiredLevel(required); detail.setReaderLevel(level); detail.setViewerAdmin(admin);
        detail.setCanReadFull(allowed); detail.setReadingProgress(progress);
        long threshold=growth.rules().stream().filter(r->((Number)r.get("level")).intValue()==required)
                .mapToLong(r->((Number)r.get("minSeconds")).longValue()).findFirst().orElse(0);
        detail.setSecondsToUnlock(allowed?0:Math.max(0,threshold-((Number)progress.get("totalSeconds")).longValue()));
        if(!allowed) detail.setContent(null);
    }
    @Transactional public void setRequiredLevel(Long aid,Long uid,Integer level) {
        if(!isAdmin(uid)) throw new BusinessException(403,"只有管理员可以设置文章阅读等级");
        if(level==null || growth.rules().stream().noneMatch(r->((Number)r.get("level")).intValue()==level))
            throw new BusinessException(400,"阅读等级无效");
        var rows=jdbc.queryForList("SELECT user_id FROM article_info WHERE article_id=? AND deleted=0 FOR UPDATE",aid);
        if(rows.isEmpty()) throw new BusinessException(404,"文章不存在");
        jdbc.update("UPDATE article_info SET required_level=?,update_time=NOW() WHERE article_id=?",level,aid);
        redis.deleteArticleDetail(aid);
        index.publish(aid,"UPDATE",RabbitMqConstants.ROUTING_KEY_UPDATE);
    }
}
