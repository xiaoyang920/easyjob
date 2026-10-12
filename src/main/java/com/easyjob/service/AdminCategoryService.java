package com.easyjob.service;

import com.baomidou.mybatisplus.core.toolkit.IdWorker;
import com.easyjob.exception.BusinessException;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DuplicateKeyException;
import com.easyjob.mapper.AdminCategoryMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.text.Normalizer;
import java.util.*;

@Service @RequiredArgsConstructor
public class AdminCategoryService {
    private final AdminCategoryMapper store;
    private final AdminConsoleService admin;
    private final ObjectMapper json;
    public record Create(String categoryName,Long parentId,Integer sortOrder,String description) {}

    public List<Map<String,Object>> list(Long actor) {
        admin.requirePermission(actor,"categories.read");
        return store.findCategories();
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
            var rows=store.lockParent(parent);
            if(rows.isEmpty())throw new BusinessException(400,"父分类不存在");
            var row=rows.getFirst();
            if(!(row.get("status") instanceof Number status) || status.intValue()!=1 || row.get("parent_id")==null || ((Number)row.get("parent_id")).longValue()!=0)throw new BusinessException(400,"只能在启用的一级分类下添加二级分类");
        }
        long id=IdWorker.getId();
        try {
            store.insertCategory(id,name,parent,order,description);
        }catch(DuplicateKeyException e){throw new BusinessException(409,"同一父分类下已有该名称，请使用其他名称");}
        var result=new LinkedHashMap<String,Object>();result.put("categoryId",Long.toString(id));result.put("categoryName",name);result.put("parentId",Long.toString(parent));result.put("sortOrder",order);result.put("description",description);result.put("status",1);result.put("version","0");
        try {
            store.insertCreateAudit(actor,id,name,json.writeValueAsString(result));
        }catch(JsonProcessingException e){throw new IllegalStateException("分类操作记录生成失败",e);}
        return result;
    }
}
