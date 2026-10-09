package com.easyjob.service;

import com.baomidou.mybatisplus.core.toolkit.IdWorker;
import com.easyjob.exception.BusinessException;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.text.Normalizer;
import java.util.*;

@Service @RequiredArgsConstructor
public class AdminCategoryService {
    private final JdbcTemplate jdbc;
    private final AdminConsoleService admin;
    private final ObjectMapper json;
    public record Create(String categoryName,Long parentId,Integer sortOrder,String description) {}

    public List<Map<String,Object>> list(Long actor) {
        admin.requirePermission(actor,"categories.read");
        return jdbc.queryForList("SELECT CAST(c.category_id AS CHAR) AS categoryId,c.category_name AS categoryName,CAST(c.parent_id AS CHAR) AS parentId,c.sort_order AS sortOrder,c.description,c.status,CAST(c.version AS CHAR) AS version,CAST(c.migrated_to AS CHAR) AS migratedTo,(SELECT COUNT(*) FROM article_info a WHERE a.category_id=c.category_id AND a.deleted=0) AS articleCount FROM category c ORDER BY c.parent_id,c.sort_order,c.category_id");
    }
    @Transactional public Map<String,Object> create(Long actor,Create body) {
        admin.requirePermission(actor,"categories.manage");
        if(body==null)throw new BusinessException(400,"请填写分类信息");
        String name=Normalizer.normalize(body.categoryName()==null?"":body.categoryName(),Normalizer.Form.NFKC).strip();
        String description=body.description()==null?"":body.description().strip();
        long parent=body.parentId()==null?0:body.parentId();int order=body.sortOrder()==null?0:body.sortOrder();
        if(name.isBlank() || name.codePointCount(0,name.length())>50 || name.codePoints().anyMatch(Character::isISOControl))throw new BusinessException(400,"分类名称需为1至50字，不能包含控制字符");
        if(description.codePointCount(0,description.length())>200)throw new BusinessException(400,"分类说明最多200字");
        if(parent<0 || order<0 || order>9999)throw new BusinessException(400,"父分类或排序值无效");
        if(parent!=0) {
            var rows=jdbc.queryForList("SELECT parent_id,status FROM category WHERE category_id=? FOR UPDATE",parent);
            if(rows.isEmpty())throw new BusinessException(400,"父分类不存在");
            var row=rows.getFirst();
            if(!(row.get("status") instanceof Number status) || status.intValue()!=1 || row.get("parent_id")==null || ((Number)row.get("parent_id")).longValue()!=0)throw new BusinessException(400,"只能在启用的一级分类下添加二级分类");
        }
        long id=IdWorker.getId();
        try {
            jdbc.update("INSERT INTO category(category_id,category_name,parent_id,sort_order,description,article_count,status,create_time,update_time) VALUES (?,?,?,?,?,0,1,NOW(),NOW())",id,name,parent,order,description);
        }catch(DuplicateKeyException e){throw new BusinessException(409,"同一父分类下已有该名称，请使用其他名称");}
        var result=new LinkedHashMap<String,Object>();result.put("categoryId",Long.toString(id));result.put("categoryName",name);result.put("parentId",Long.toString(parent));result.put("sortOrder",order);result.put("description",description);result.put("status",1);result.put("version","0");
        try {
            jdbc.update("INSERT INTO admin_operation_log(admin_user_id,action,target_type,target_id,before_value,after_value,details_json) VALUES (?,'category_create','category',?,'',?,?)",actor,id,name,json.writeValueAsString(result));
        }catch(JsonProcessingException e){throw new IllegalStateException("分类操作记录生成失败",e);}
        return result;
    }
}
