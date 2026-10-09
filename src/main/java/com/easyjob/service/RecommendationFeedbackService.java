package com.easyjob.service;
import com.easyjob.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.*;

@Service @RequiredArgsConstructor
public class RecommendationFeedbackService {
 private final JdbcTemplate jdbc;
 @Transactional public void save(Long uid,Long aid,String kind){
  if(uid==null)throw new BusinessException(401,"请先登录");
  if(aid==null || aid<=0 || kind==null || !Set.of("not_interested","hide_author").contains(kind))throw new BusinessException(400,"推荐反馈无效");
  if(jdbc.queryForList("SELECT user_id FROM user_info WHERE user_id=? AND status=1 FOR UPDATE",uid).isEmpty())throw new BusinessException(403,"账号不可用");
  var article=jdbc.queryForList("SELECT user_id FROM article_info WHERE article_id=? AND status=1 AND deleted=0",aid);if(article.isEmpty())throw new BusinessException(404,"文章不存在或已下架");
  if(jdbc.queryForObject("SELECT COUNT(*) FROM recommendation_feedback WHERE user_id=? AND article_id<>?",Long.class,uid,aid)>=200)throw new BusinessException(400,"最多保留200条推荐反馈，请先移除旧记录");
  jdbc.update("INSERT INTO recommendation_feedback(user_id,article_id,target_author_id,kind) VALUES (?,?,?,?) ON DUPLICATE KEY UPDATE kind=VALUES(kind),target_author_id=VALUES(target_author_id),created_at=NOW(3)",uid,aid,article.getFirst().get("user_id"),kind);
 }
 public void remove(Long uid,Long aid){if(uid==null)throw new BusinessException(401,"请先登录");if(aid==null || aid<=0)throw new BusinessException(400,"反馈ID无效");jdbc.update("DELETE FROM recommendation_feedback WHERE user_id=? AND article_id=?",uid,aid);}
 public List<Map<String,Object>> list(Long uid){if(uid==null)throw new BusinessException(401,"请先登录");return jdbc.queryForList("SELECT CAST(f.article_id AS CHAR) AS articleId,f.kind,a.title,u.nick_name AS authorName,f.created_at AS createdAt FROM recommendation_feedback f LEFT JOIN article_info a ON a.article_id=f.article_id LEFT JOIN user_info u ON u.user_id=f.target_author_id WHERE f.user_id=? ORDER BY f.created_at DESC,f.article_id DESC LIMIT 200",uid);}
}
