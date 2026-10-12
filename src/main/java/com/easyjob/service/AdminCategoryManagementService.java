package com.easyjob.service;

import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.exception.BusinessException;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import com.easyjob.mapper.AdminCategoryManagementMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.text.Normalizer;
import java.util.*;

@Service @RequiredArgsConstructor @Slf4j
public class AdminCategoryManagementService {
    private final AdminCategoryManagementMapper store;
    private final AdminConsoleService admin;
    private final ObjectMapper json;
    private final RedisComponent redis;
    private final ArticleIndexPublisher index;
    public record Update(Long expectedVersion,String categoryName,Integer sortOrder,String description,Integer status) {}
    public record Move(Long expectedVersion,Long targetId,Long targetVersion) {}
    private static long number(Map<String,Object> row,String key){return ((Number)row.get(key)).longValue();}
    private Map<String,Object> row(long id){var rows=store.lockCategory(id);if(rows.isEmpty())throw new BusinessException(404,"分类不存在");return rows.getFirst();}
    private void lock(long... ids){
        var lockIds=new TreeSet<Long>();
        for(long id:ids){if(id<=0)throw new BusinessException(400,"分类ID无效");var metadata=store.findParent(id);if(metadata.isEmpty())throw new BusinessException(404,"分类不存在");var r=metadata.getFirst();lockIds.add(id);if(r.get("parent_id") instanceof Number p && p.longValue()>0)lockIds.add(p.longValue());}
        for(long id:lockIds)store.lockIdentity(id);
    }
    private static void version(Map<String,Object> row,Long expected){if(expected==null || expected!=number(row,"version"))throw new BusinessException(409,"分类已被其他管理员修改，请刷新后重试");}
    private boolean active(Map<String,Object> row){return number(row,"status")==1 && (number(row,"parent_id")==0 || number(row(number(row,"parent_id")),"status")==1);}
    private void children(long id){if(!store.lockEnabledChildren(id).isEmpty())throw new BusinessException(409,"请先停用或迁移启用的二级分类");}
    private void audit(Long actor,long id,String action,Map<String,Object> before,Map<String,Object> after){try{store.insertAudit(actor,action,id,String.valueOf(before.getOrDefault("category_name","")),String.valueOf(after.getOrDefault("categoryName",before.get("category_name"))),json.writeValueAsString(Map.of("before",before,"after",after)));}catch(JsonProcessingException e){throw new IllegalStateException(e);}}
    @Transactional public void update(Long actor,long id,Update body){
        admin.requirePermission(actor,"categories.manage");if(body==null)throw new BusinessException(400,"分类信息无效");lock(id);var before=row(id);version(before,body.expectedVersion());
        String name=Normalizer.normalize(body.categoryName()==null?"":body.categoryName(),Normalizer.Form.NFKC).strip(),description=body.description()==null?"":body.description().strip();
        if(name.isBlank() || name.codePointCount(0,name.length())>50 || name.codePoints().anyMatch(Character::isISOControl) || description.codePointCount(0,description.length())>200 || body.sortOrder()==null || body.sortOrder()<0 || body.sortOrder()>9999 || body.status()==null || !List.of(0,1).contains(body.status()))throw new BusinessException(400,"分类名称、说明、排序或状态无效");
        if(body.status()==0)children(id);
        if(body.status()==1 && (before.get("migrated_to")!=null || (number(before,"parent_id")>0 && number(row(number(before,"parent_id")),"status")!=1)))throw new BusinessException(409,"已迁移分类不能启用，二级分类的父分类也必须启用");
        try{store.updateCategory(name,body.sortOrder(),description,body.status(),id);}catch(DuplicateKeyException e){throw new BusinessException(409,"同一父分类下已有该名称");}
        audit(actor,id,"category_update",before,Map.of("categoryName",name,"sortOrder",body.sortOrder(),"description",description,"status",body.status(),"version",number(before,"version")+1));
        if(!Objects.equals(name,before.get("category_name"))) {
            var articleIds=store.findArticleIds(id);
            invalidate(articleIds);
        }
    }
    @Transactional public Map<String,Object> move(Long actor,long id,Move body){
        admin.requirePermission(actor,"categories.manage");if(body==null || body.targetId()==null || body.targetId()==id)throw new BusinessException(400,"请选择不同的目标分类");
        // Match author writes: article locks precede category locks. Category routing uses current shared reads.
        var articles=store.lockArticlesForMove(id);
        lock(id,body.targetId());var source=row(id);var target=row(body.targetId());version(source,body.expectedVersion());version(target,body.targetVersion());children(id);
        if(source.get("migrated_to")!=null || !active(target) || target.get("migrated_to")!=null)throw new BusinessException(409,"原分类已迁移或目标分类不可用，请刷新");
        if(articles.size()>500)throw new BusinessException(400,"一次迁移最多500篇，当前分类需使用后台批处理迁移");
        var changed=new ArrayList<Long>();
        for(var article:articles){long aid=number(article,"article_id");store.moveArticle(body.targetId(),aid);changed.add(aid);if(number(article,"status")==1)index.publish(aid,"UPDATE",RabbitMqConstants.ROUTING_KEY_UPDATE);}
        store.redirectCategory(body.targetId(),id);
        store.incrementVersion(body.targetId());
        var after=Map.<String,Object>of("targetId",body.targetId().toString(),"categoryName",target.get("category_name"),"articleCount",changed.size(),"status",0);
        audit(actor,id,"category_migrate",source,after);
        invalidate(changed);
        return after;
    }
    private void invalidate(List<Long> ids){TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization(){@Override public void afterCommit(){for(long aid:ids)try{redis.deleteArticleDetail(aid);}catch(RuntimeException e){log.warn("分类修改缓存失效失败，articleId={}",aid);}}});}
}
