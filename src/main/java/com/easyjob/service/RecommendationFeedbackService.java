package com.easyjob.service;
import com.easyjob.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import com.easyjob.mapper.RecommendationFeedbackMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.*;

@Service @RequiredArgsConstructor
public class RecommendationFeedbackService {
 private final RecommendationFeedbackMapper store;
 @Transactional public void save(Long uid,Long aid,String kind){
  if(uid==null)throw new BusinessException(401,"请先登录");
  if(aid==null || aid<=0 || kind==null || !Set.of("not_interested","hide_author").contains(kind))throw new BusinessException(400,"推荐反馈无效");
  if(store.lockActiveUser(uid).isEmpty())throw new BusinessException(403,"账号不可用");
  var article=store.findPublicArticle(aid);if(article.isEmpty())throw new BusinessException(404,"文章不存在或已下架");
  if(store.countOtherFeedback(uid,aid)>=200)throw new BusinessException(400,"最多保留200条推荐反馈，请先移除旧记录");
  store.upsertFeedback(uid,aid,((Number)article.getFirst().get("user_id")).longValue(),kind);
 }
 public void remove(Long uid,Long aid){if(uid==null)throw new BusinessException(401,"请先登录");if(aid==null || aid<=0)throw new BusinessException(400,"反馈ID无效");store.deleteFeedback(uid,aid);}
 public List<Map<String,Object>> list(Long uid){if(uid==null)throw new BusinessException(401,"请先登录");return store.findFeedback(uid);}
}
