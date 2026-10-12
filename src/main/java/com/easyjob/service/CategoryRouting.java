package com.easyjob.service;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleRevisionMapper;
import java.util.HashSet;

/** Administrative category redirects apply when replaying immutable author snapshots. */
final class CategoryRouting {
    static Long resolve(ArticleRevisionMapper store,Long id){
        var seen=new HashSet<Long>();
        for(int hop=0;hop<32;hop++){
            if(!seen.add(id))throw new BusinessException(409,"分类迁移关系存在循环，请联系管理员");
            var rows=store.lockCategoryRedirect(id);
            if(rows.isEmpty() || rows.getFirst().get("migrated_to")==null)return id;
            id=((Number)rows.getFirst().get("migrated_to")).longValue();
        }
        throw new BusinessException(409,"分类迁移层级过多，请联系管理员");
    }
}
