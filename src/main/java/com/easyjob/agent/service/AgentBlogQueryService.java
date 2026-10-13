package com.easyjob.agent.service;

import com.easyjob.mapper.AgentBlogQueryMapper;
import com.easyjob.rpc.v1.BlogQuery;
import com.easyjob.agent.rpc.RpcValues;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.util.*;

@Service
public class AgentBlogQueryService {
    private final AgentBlogQueryMapper store;
    public AgentBlogQueryService(AgentBlogQueryMapper store) { this.store=store; }
    public Object read(BlogQuery q) {
        if(q.getIdsCount()>128 || q.getNamesCount()>100 || q.getName().length()>200 || q.getNamesList().stream().anyMatch(s->s.length()>200)
            || q.getLimit()<0 || q.getLimit()>100 || q.getPage()<0 || q.getPage()>10000
            || q.getIdsList().stream().anyMatch(id->id<=0)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
        int limit=q.getLimit()==0?20:q.getLimit();
        return switch(q.getKind()) {
            case "user_sources" -> q.getIdsCount()==0?List.of():store.userSources(q.getIdsList());
            case "published" -> q.getIdsCount()==0?List.of():store.published(q.getIdsList());
            case "tags" -> q.getNamesCount()==0?List.of():store.tags(q.getNamesList());
            case "categories" -> q.getNamesCount()==0?List.of():store.categories(q.getNamesList());
            case "authors" -> q.getName().isBlank()?List.of():store.authors(q.getName());
            case "user_articles" -> store.userArticles(q.getTargetId(),limit,(Math.max(1,q.getPage())-1)*limit);
            case "comments" -> store.comments(q.getTargetId(),limit);
            case "trending" -> store.trending(limit);
            default -> throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
        };
    }
    @Transactional(timeout=20)
    public Object maintenance(BlogQuery q) {
        return switch(q.getKind()) {
            case "article_scan" -> store.scan(Math.max(0,q.getCursor()));
            case "article_lookup" -> store.article(q.getTargetId());
            case "article_repair" -> repair(q);
            case "metrics" -> Map.of("article_jobs",store.jobCounts(),"article_oldest_pending_seconds",store.oldestJob());
            case "cleanup" -> {
                int jobs=store.cleanJobs();var ids=store.oldSessions();
                int sessions=ids.isEmpty()?0:store.cleanSessions(ids);int reads=store.cleanReads();
                yield Map.of("jobs",jobs,"sessions",sessions,"reads",reads);
            }
            default -> throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
        };
    }
    private boolean repair(BlogQuery q) {
        if(q.getTargetId()<=0) throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
        var current=store.lockArticle(q.getTargetId());
        @SuppressWarnings("unchecked") var prior=(Map<String,Object>)RpcValues.decode(com.easyjob.rpc.v1.Value.newBuilder().setObject(q.getExpected()).build());
        if(!prior.isEmpty()) {
            if(current==null) return false;
            for(String k:List.of("content","title","tags","category_id","user_id","status","deleted","required_level","update_time"))
                if(!normal(current.get(k)).equals(normal(prior.get(k)))) return false;
        } else if(current!=null && "1".equals(normal(current.get("status"))) && "0".equals(normal(current.get("deleted")))) return false;
        if(q.getName().equals("view_count") && current!=null) {
            store.repairViews(q.getTargetId(),((Number)current.get("view_count")).longValue());return true;
        }
        if(store.activeJobs(q.getTargetId())>0) return false;
        store.repair(q.getTargetId(),UUID.randomUUID().toString());return true;
    }
    private static String normal(Object v) {
        if(v==null) return "";
        if(v instanceof java.sql.Timestamp t) return t.toLocalDateTime().toString();
        if(v instanceof java.time.LocalDateTime t) return t.toString();
        String s=v.toString();
        if(s.matches("\\d{4}-\\d{2}-\\d{2}[ T].*")) {
            try { return java.time.LocalDateTime.parse(s.replace(' ','T')).toString(); } catch(Exception ignored) {}
        }
        return s;
    }
}
