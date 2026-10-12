package com.easyjob.service;

import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.UserMapper;
import com.easyjob.vo.PageVO;
import lombok.RequiredArgsConstructor;
import com.easyjob.mapper.AdminConsoleMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.util.*;

@Service @RequiredArgsConstructor
public class AdminConsoleService {
    private final AdminConsoleMapper store;
    private final ArticleAccessService access;
    private final ReadingGrowthService growth;
    private final RedisComponent redis;
    private final UserMapper users;
    private final ArticleIndexPublisher index;

    public void requireAdmin(Long uid) {
        if (!access.isAdmin(uid)) throw new BusinessException(403,"只有管理员可以访问管理后台");
    }
    public Map<String,Object> me(Long uid) {
        var permissions=access.permissions(uid);if(permissions.isEmpty())throw new BusinessException(403,"没有后台访问权限");
        var result=new LinkedHashMap<>(store.findOperator(uid));result.put("permissions",permissions.stream().sorted().toList());return result;
    }
    public void requirePermission(Long uid,String permission){if(!access.isAdmin(uid) && !access.hasPermission(uid,permission))throw new BusinessException(403,"没有执行此操作的权限");}
    public Map<String,Object> overview(Long uid) {
        requirePermission(uid,"overview.read");
        var result=new LinkedHashMap<String,Object>();
        result.put("users",store.countUsers());
        result.put("published",store.countPublished());
        result.put("restricted",store.countRestricted());
        result.put("removed",store.countRemoved());
        result.put("readingSeconds",store.totalReadingSeconds());
        result.put("rules",growth.rules());
        result.put("pendingReviews",store.countPendingReviews());
        return result;
    }
    static String searchPattern(String keyword) {
        String value=keyword==null?"":keyword.strip();
        if(value.length()>80) throw new BusinessException(400,"搜索词不能超过80字");
        return "%"+value.replace("!","!!").replace("%","!%").replace("_","!_")+"%";
    }
    public PageVO<Map<String,Object>> articles(Long uid,String keyword,Integer status,int page,int size) {
        requirePermission(uid,"articles.read");
        if(status!=null && status!=1 && status!=2) throw new BusinessException(400,"文章管理仅管理已发布及下架文章，待审核内容请到文章审核查看");
        String pattern=searchPattern(keyword);
        ArticleRevisionService.bounds(page,size);
        long total=store.countArticles(pattern,status);
        var records=store.findArticles(pattern,status,size,(page-1)*size);
        return new PageVO<>(records,total,(long)size,(long)page,(total+size-1)/size);
    }
    public PageVO<Map<String,Object>> users(Long uid,String keyword,int page,int size) {
        requirePermission(uid,"users.read");
        String pattern=searchPattern(keyword);
        ArticleRevisionService.bounds(page,size);
        long total=store.countMatchingUsers(pattern);
        var records=store.findUsers(pattern,size,(page-1)*size);
        return new PageVO<>(records,total,(long)size,(long)page,(total+size-1)/size);
    }
    public PageVO<Map<String,Object>> logs(Long uid,int page,int size) {
        requirePermission(uid,"logs.read");
        if(page<1 || page>10000 || size<1 || size>100) throw new BusinessException(400,"分页参数无效");
        long total=store.countOperationLogs();
        var rows=store.findOperationLogs(size,(page-1)*size);
        return new PageVO<>(rows,total,(long)size,(long)page,(total+size-1)/size);
    }
    private Map<String,Object> lockArticle(Long aid) {
        if(aid==null || aid<=0) throw new BusinessException(400,"文章ID无效");
        var owners=store.findArticleOwner(aid);
        if(owners.isEmpty())throw new BusinessException(404,"文章不存在");
        store.lockOwner(((Number)owners.getFirst().get("user_id")).longValue());
        var rows=store.lockArticle(aid);
        if(rows.isEmpty()) throw new BusinessException(404,"文章不存在");
        return rows.getFirst();
    }
    private void audit(Long uid,Long aid,String action,int before,int after) {
        store.insertArticleAudit(uid,action,aid,String.valueOf(before),String.valueOf(after));
    }
    @Transactional public void level(Long uid,Long aid,Integer expected,Integer level) {
        requirePermission(uid,"articles.manage");var article=lockArticle(aid);
        int old=((Number)article.get("required_level")).intValue();
        if(expected==null || old!=expected) throw new BusinessException(409,"文章等级已变化，请刷新后重试");
        if(level==null) throw new BusinessException(400,"阅读等级无效");
        access.setRequiredLevel(aid,uid,level);
        if(old!=level) audit(uid,aid,"reading_level",old,level);
    }
    @Transactional public void visibility(Long uid,Long aid,Integer expected,Integer status) {
        requirePermission(uid,"articles.manage");
        if(status==null || (status!=1 && status!=2)) throw new BusinessException(400,"只支持下架或恢复已发布文章");
        var article=lockArticle(aid);int old=((Number)article.get("status")).intValue();
        if(old!=1 && old!=2) throw new BusinessException(409,"草稿由作者发布，不能通过管理后台直接发布");
        if(expected==null || old!=expected) throw new BusinessException(409,"文章状态已变化，请刷新后重试");
        if(old==status) return;
        long author=((Number)article.get("user_id")).longValue();
        store.updateArticleVisibility(status,aid);
        users.changeArticleCount(author,status==1?1:-1);
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() { redis.deleteArticleDetail(aid);redis.deleteUserSpaceVO(author); }
        });
        index.publish(aid,"UPDATE",RabbitMqConstants.ROUTING_KEY_UPDATE);
        audit(uid,aid,"visibility",old,status);
    }
}
