package com.easyjob.service;

import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.UserMapper;
import com.easyjob.vo.PageVO;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.util.*;

@Service @RequiredArgsConstructor
public class AdminConsoleService {
    private final JdbcTemplate jdbc;
    private final ArticleAccessService access;
    private final ReadingGrowthService growth;
    private final RedisComponent redis;
    private final UserMapper users;
    private final ArticleIndexPublisher index;

    public void requireAdmin(Long uid) {
        if (!access.isAdmin(uid)) throw new BusinessException(403,"只有管理员可以访问管理后台");
    }
    public Map<String,Object> me(Long uid) {
        requireAdmin(uid);
        return jdbc.queryForMap("SELECT CAST(user_id AS CHAR) AS userId,nick_name AS nickName FROM user_info WHERE user_id=?",uid);
    }
    public Map<String,Object> overview(Long uid) {
        requireAdmin(uid);
        var result=new LinkedHashMap<String,Object>();
        result.put("users",jdbc.queryForObject("SELECT COUNT(*) FROM user_info",Long.class));
        result.put("published",jdbc.queryForObject("SELECT COUNT(*) FROM article_info WHERE status=1 AND deleted=0",Long.class));
        result.put("restricted",jdbc.queryForObject("SELECT COUNT(*) FROM article_info WHERE status=1 AND deleted=0 AND required_level>0",Long.class));
        result.put("removed",jdbc.queryForObject("SELECT COUNT(*) FROM article_info WHERE status=2 AND deleted=0",Long.class));
        result.put("readingSeconds",jdbc.queryForObject("SELECT COALESCE(SUM(total_millis),0) DIV 1000 FROM user_reading_progress",Long.class));
        result.put("rules",growth.rules());
        result.put("pendingReviews",jdbc.queryForObject("SELECT COUNT(*) FROM article_revision r JOIN article_info a ON a.article_id=r.article_id WHERE r.state=1 AND a.deleted=0",Long.class));
        return result;
    }
    static String searchPattern(String keyword) {
        String value=keyword==null?"":keyword.strip();
        if(value.length()>80) throw new BusinessException(400,"搜索词不能超过80字");
        return "%"+value.replace("!","!!").replace("%","!%").replace("_","!_")+"%";
    }
    public PageVO<Map<String,Object>> articles(Long uid,String keyword,Integer status,int page,int size) {
        requireAdmin(uid);
        if(status!=null && status!=0 && status!=1 && status!=2) throw new BusinessException(400,"文章状态无效");
        String pattern=searchPattern(keyword);
        var args=new ArrayList<Object>(List.of(pattern,pattern));
        String where="FROM article_info a LEFT JOIN user_info u ON u.user_id=a.user_id WHERE a.deleted=0 AND (a.title LIKE ? ESCAPE '!' OR u.nick_name LIKE ? ESCAPE '!')";
        if(status!=null){where+=" AND a.status=?";args.add(status);}
        // The count query must not carry ORDER BY; stable ordering is added to the select only.
        if(page<1 || page>10000 || size<1 || size>100) throw new BusinessException(400,"分页参数无效");
        long total=jdbc.queryForObject("SELECT COUNT(*) "+where,Long.class,args.toArray());
        args.add(size);args.add((page-1)*size);
        var records=jdbc.queryForList("SELECT CAST(a.article_id AS CHAR) AS articleId,a.title,u.nick_name AS authorName,a.status,a.required_level AS requiredLevel,a.view_count AS viewCount,a.update_time AS updateTime "+where+" ORDER BY a.update_time DESC,a.article_id DESC LIMIT ? OFFSET ?",args.toArray());
        return new PageVO<>(records,total,(long)size,(long)page,(total+size-1)/size);
    }
    public PageVO<Map<String,Object>> users(Long uid,String keyword,int page,int size) {
        requireAdmin(uid);
        String pattern=searchPattern(keyword);
        String from="FROM user_info u LEFT JOIN user_reading_progress p ON p.user_id=u.user_id WHERE u.nick_name LIKE ? ESCAPE '!' OR CAST(u.user_id AS CHAR) LIKE ? ESCAPE '!'";
        if(page<1 || page>10000 || size<1 || size>100) throw new BusinessException(400,"分页参数无效");
        long total=jdbc.queryForObject("SELECT COUNT(*) "+from,Long.class,pattern,pattern);
        var records=jdbc.queryForList("SELECT CAST(u.user_id AS CHAR) AS userId,u.nick_name AS nickName,u.role,CAST(u.status AS UNSIGNED) AS status,u.join_time AS joinTime,"+
                "COALESCE(p.total_millis,0) DIV 1000 AS readingSeconds,GREATEST(COALESCE(p.earned_level,0),COALESCE((SELECT MAX(level) FROM reading_level_rule WHERE min_seconds<=COALESCE(p.total_millis,0) DIV 1000),0)) AS readingLevel "+from+" ORDER BY u.join_time DESC,u.user_id DESC LIMIT ? OFFSET ?",pattern,pattern,size,(page-1)*size);
        return new PageVO<>(records,total,(long)size,(long)page,(total+size-1)/size);
    }
    public PageVO<Map<String,Object>> logs(Long uid,int page,int size) {
        requireAdmin(uid);
        if(page<1 || page>10000 || size<1 || size>100) throw new BusinessException(400,"分页参数无效");
        long total=jdbc.queryForObject("SELECT COUNT(*) FROM admin_operation_log",Long.class);
        var rows=jdbc.queryForList("SELECT CAST(l.id AS CHAR) AS id,CAST(l.admin_user_id AS CHAR) AS adminUserId,u.nick_name AS adminName,l.action,CAST(l.target_id AS CHAR) AS targetId,l.before_value AS beforeValue,l.after_value AS afterValue,l.created_at AS createdAt FROM admin_operation_log l LEFT JOIN user_info u ON u.user_id=l.admin_user_id ORDER BY l.id DESC LIMIT ? OFFSET ?",size,(page-1)*size);
        return new PageVO<>(rows,total,(long)size,(long)page,(total+size-1)/size);
    }
    private Map<String,Object> lockArticle(Long aid) {
        if(aid==null || aid<=0) throw new BusinessException(400,"文章ID无效");
        var rows=jdbc.queryForList("SELECT user_id,status,required_level FROM article_info WHERE article_id=? AND deleted=0 FOR UPDATE",aid);
        if(rows.isEmpty()) throw new BusinessException(404,"文章不存在");
        return rows.getFirst();
    }
    private void audit(Long uid,Long aid,String action,int before,int after) {
        jdbc.update("INSERT INTO admin_operation_log(admin_user_id,action,target_type,target_id,before_value,after_value) VALUES (?,?,'article',?,?,?)",uid,action,aid,String.valueOf(before),String.valueOf(after));
    }
    @Transactional public void level(Long uid,Long aid,Integer expected,Integer level) {
        requireAdmin(uid);var article=lockArticle(aid);
        int old=((Number)article.get("required_level")).intValue();
        if(expected==null || old!=expected) throw new BusinessException(409,"文章等级已变化，请刷新后重试");
        if(level==null) throw new BusinessException(400,"阅读等级无效");
        access.setRequiredLevel(aid,uid,level);
        if(old!=level) audit(uid,aid,"reading_level",old,level);
    }
    @Transactional public void visibility(Long uid,Long aid,Integer expected,Integer status) {
        requireAdmin(uid);
        if(status==null || (status!=1 && status!=2)) throw new BusinessException(400,"只支持下架或恢复已发布文章");
        var article=lockArticle(aid);int old=((Number)article.get("status")).intValue();
        if(old!=1 && old!=2) throw new BusinessException(409,"草稿由作者发布，不能通过管理后台直接发布");
        if(expected==null || old!=expected) throw new BusinessException(409,"文章状态已变化，请刷新后重试");
        if(old==status) return;
        long author=((Number)article.get("user_id")).longValue();
        jdbc.update("UPDATE article_info SET status=?,update_time=NOW() WHERE article_id=?",status,aid);
        users.changeArticleCount(author,status==1?1:-1);
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() { redis.deleteArticleDetail(aid);redis.deleteUserSpaceVO(author); }
        });
        index.publish(aid,"UPDATE",RabbitMqConstants.ROUTING_KEY_UPDATE);
        audit(uid,aid,"visibility",old,status);
    }
}
