package com.easyjob.service;

import com.easyjob.component.EsComponent;
import com.easyjob.mapper.ArticleSearchMapper;
import com.easyjob.vo.ArticleSearchVO;
import com.easyjob.vo.PageVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Search recall with fresh publication metadata from the authoritative database. */
@Service
@RequiredArgsConstructor
public class ArticleSearchService {
    private final EsComponent es;
    private final ArticleSearchMapper store;
    public PageVO<ArticleSearchVO> search(Boolean highlight,String keyword,Integer orderType,Integer pageNo,Integer pageSize) {
        PageVO<ArticleSearchVO> result = es.search(highlight, keyword, orderType, pageNo, pageSize);
        if(!result.getRecords().isEmpty()) {
            List<Long> ids=result.getRecords().stream().map(a->Long.valueOf(a.getArticleId())).toList();
            List<Map<String, Object>> rows=store.findCurrentArticles(ids);
            HashMap<String, Map<String, Object>> current=new java.util.HashMap<String,java.util.Map<String,Object>>();
            for(Map<String, Object> row:rows) current.put(row.get("article_id").toString(),row);
            result.setRecords(result.getRecords().stream().filter(a->current.containsKey(a.getArticleId())).peek(a->{
                Map<String, Object> row=current.get(a.getArticleId());
                a.setRequiredLevel(((Number)row.get("required_level")).intValue());
                a.setSummary((String)row.get("summary"));
            }).toList());
        }
        return result;
    }
}
