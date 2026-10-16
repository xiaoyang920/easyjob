package com.easyjob.service;

import cn.hutool.core.bean.BeanUtil;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.dto.ArticleCreateDTO;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.entity.ArticleRevisionInsert;
import com.easyjob.entity.PublishedArticleProjection;
import com.easyjob.mapper.UserMapper;
import com.easyjob.utils.HtmlContentSanitizer;
import com.easyjob.vo.ArticleDetailVO;
import com.easyjob.vo.PageVO;
import com.easyjob.vo.TagVO;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.jsoup.Jsoup;
import com.easyjob.mapper.ArticleRevisionMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Working drafts and frozen review snapshots; article_info is the published projection. */
@Service @RequiredArgsConstructor
public class ArticleRevisionService {
    public static final int DRAFT=0, PENDING=1, APPROVED=2, REJECTED=3, WITHDRAWN=4, SUPERSEDED=5;
    private final ArticleRevisionMapper store;
    private final ObjectMapper json;
    private final ArticleMapper articles;
    private final UserMapper users;
    private final ArticleTagService tags;
    private final ArticleAccessService access;
    private final ArticleIndexPublisher index;
    private final RedisComponent redis;
    private final com.easyjob.service.impl.NotificationServiceImpl notifications;

    private static long number(Map<String,Object> row,String key){return ((Number)row.get(key)).longValue();}
    private void lockOwner(long uid) {
        if(store.lockOwner(uid).isEmpty())
            throw new BusinessException(404,"作者不存在");
    }
    private Map<String,Object> article(long aid,Long uid,boolean admin) {
        if(admin && !access.isAdmin(uid) && !access.hasPermission(uid,"reviews.read")) throw new BusinessException(403,"只有管理员可以审核文章");
        // An unpublished article has no info row. Always lock owner -> info -> revision,
        // including first publication, so creation and review cannot race on a missing row.
        var owners=store.findOwners(aid);
        if(owners.isEmpty() || (!admin && !Objects.equals(number(owners.getFirst(),"user_id"),uid)))
            throw new BusinessException(404,"文章不存在或无权操作");
        long owner=number(owners.getFirst(),"user_id");lockOwner(owner);
        var rows=store.lockPublishedArticle(aid);
        if(!rows.isEmpty() && (Boolean.TRUE.equals(rows.getFirst().get("deleted")) || rows.getFirst().get("deleted") instanceof Number n && n.intValue()!=0))throw new BusinessException(404,"文章已删除");
        var heads=store.lockCurrentRevision(aid);
        Map<String,Object> a;
        if(!rows.isEmpty())a=new HashMap<>(rows.getFirst());
        else {
            if(heads.isEmpty() || number(heads.getFirst(),"author_id")!=owner)throw new BusinessException(404,"草稿不存在");
            a=new HashMap<>();a.put("article_id",aid);a.put("user_id",owner);a.put("status",0);
            a.put("latest_revision_id",0L);a.put("published_revision_id",0L);
        }
        if(number(a,"user_id")!=owner)throw new BusinessException(404,"文章不存在");
        a.put("has_info",!rows.isEmpty());
        if(!heads.isEmpty() && !a.containsKey("required_level"))a.put("required_level",heads.getFirst().get("required_level"));
        if(!heads.isEmpty())a.put("latest_revision_id",number(heads.getFirst(),"revision_id"));
        return a;
    }
    private Map<String,Object> revision(long rid) {
        var rows=store.lockRevision(rid);
        if(rows.isEmpty()) throw new BusinessException(404,"版本不存在");
        return rows.getFirst();
    }
    private long revisionArticle(long rid) {
        var rows=store.findRevisionArticle(rid);
        if(rows.isEmpty())throw new BusinessException(404,"版本不存在");
        return number(rows.getFirst(),"article_id");
    }
    private void expected(Map<String,Object> a,String expected) {
        long id;
        try {id=Long.parseLong(expected);} catch(Exception e){throw new BusinessException(400,"请重新打开编辑器获取当前版本");}
        if(id!=number(a,"latest_revision_id")) throw new BusinessException(409,"文章版本已变化，请刷新后重试");
    }
    private void expectedLock(Map<String,Object> r,Long expected) {
        if(expected==null || expected!=number(r,"lock_version"))
            throw new BusinessException(409,"草稿内容已变化，请重新读取后再保存");
    }
    private Map<String,Object> decode(Object value) {
        try {return json.readValue(value.toString(),new TypeReference<LinkedHashMap<String,Object>>(){});}
        catch(Exception e){throw new IllegalStateException("Invalid article revision payload",e);}
    }
    private String encode(Map<String,Object> value) {
        try{return json.writeValueAsString(value);}catch(Exception e){throw new IllegalStateException(e);}
    }
    public static String hash(String payload) {
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(payload.getBytes(StandardCharsets.UTF_8)));}
        catch(Exception e){throw new IllegalStateException(e);}
    }
    private Map<String,Object> payload(ArticleCreateDTO dto,boolean submitting) {
        if(!dto.isTitleValid()) throw new BusinessException(400,"标题需为1至100字");
        if(dto.getSummary()!=null && dto.getSummary().codePointCount(0,dto.getSummary().length())>500) throw new BusinessException(400,"摘要不能超过500字");
        if(dto.getContent()==null || dto.getContent().length()>300000) throw new BusinessException(400,"正文为空或过长");
        if(dto.getContentType()==null || (dto.getContentType()!=1 && dto.getContentType()!=2)) throw new BusinessException(400,"正文格式无效");
        String content=dto.getContentType()==1?HtmlContentSanitizer.clean(dto.getContent(),true):dto.getContent();
        if(submitting && (dto.getContentType()==1?Jsoup.parse(content).text().isBlank():content.isBlank()))
            throw new BusinessException(400,"请输入文章正文");
        Long category=null;
        if(dto.getCategoryId()!=null && !dto.getCategoryId().isBlank()) {
            try{category=Long.valueOf(dto.getCategoryId());}catch(Exception e){throw new BusinessException(400,"分类无效");}
            category=CategoryRouting.resolve(store,category);
            var selected=store.lockCategory(category);
            if(selected.isEmpty() || number(selected.getFirst(),"status")!=1)
                throw new BusinessException(400,"请选择有效分类");
            long parent=number(selected.getFirst(),"parent_id");
            if(parent>0){var parents=store.lockParentCategory(parent);if(parents.isEmpty() || number(parents.getFirst(),"status")!=1)throw new BusinessException(400,"请选择有效分类");}
        } else if(submitting) throw new BusinessException(400,"提交审核前请选择分类");
        var names=dto.getTagNames()==null?(dto.getTags()==null?List.<String>of():Arrays.asList(dto.getTags().split(","))):dto.getTagNames();
        if(names.size()>10 || names.stream().anyMatch(s->s==null || s.strip().isEmpty() || s.length()>30))
            throw new BusinessException(400,"最多10个标签，每个标签1至30字");
        if(dto.getIsOriginal()==null || (dto.getIsOriginal()!=0 && dto.getIsOriginal()!=1)) throw new BusinessException(400,"原创标识无效");
        if(dto.getCoverImage()!=null && dto.getCoverImage().length()>500) throw new BusinessException(400,"封面地址过长");
        var result=new LinkedHashMap<String,Object>();
        result.put("title",dto.getTitle().strip());result.put("summary",dto.getSummary());result.put("content",content);
        result.put("contentType",dto.getContentType());result.put("categoryId",category==null?null:category.toString());
        result.put("coverImage",dto.getCoverImage());result.put("isOriginal",dto.getIsOriginal());
        result.put("tagNames",names.stream().map(String::strip).distinct().toList());
        return result;
    }
    private ArticleCreateDTO dto(Map<String,Object> p) {return json.convertValue(p,ArticleCreateDTO.class);}
    private Map<String,Object> displayPayload(Map<String,Object> p) {
        if(p.get("categoryId")!=null)p.put("categoryId",CategoryRouting.resolve(store,Long.valueOf(p.get("categoryId").toString())).toString());
        if(p.get("categoryId")!=null){var names=store.findCategoryName(Long.valueOf(p.get("categoryId").toString()));p.put("categoryName",names.isEmpty()?"分类已删除":names.getFirst().get("category_name"));}
        return p;
    }
    private long append(Map<String,Object> a,Map<String,Object> p,int state) {
        long aid=number(a,"article_id");
        int version=store.nextVersion(aid);
        String serialized=encode(new TreeMap<>(p));
        store.clearCurrentRevision(aid);
        var row=ArticleRevisionInsert.builder()
            .clientRequestId((String)a.get("client_request_id"))
            .articleId(aid).version(version).authorId(number(a,"user_id"))
            .baseRevisionId(number(a,"published_revision_id")).state(state)
            .payload(serialized).contentHash(hash(serialized))
            .requiredLevel(((Number)a.getOrDefault("required_level",0)).intValue()).build();
        store.insertRevision(row);
        long id=Objects.requireNonNull(row.getRevisionId());
        store.updateLatestRevision(id,aid);a.put("latest_revision_id",id);
        if(state==PENDING) log(a,id,number(a,"user_id"),"submit","");
        return id;
    }
    @Transactional public Map<String,Object> create(Long uid,long aid,ArticleCreateDTO dto) {
        lockOwner(uid);
        String requestId=dto.getClientRequestId();
        if(requestId!=null){
            try{if(!java.util.UUID.fromString(requestId).toString().equalsIgnoreCase(requestId))throw new IllegalArgumentException();}
            catch(IllegalArgumentException invalid){throw new BusinessException(400,"草稿请求标识无效");}
            var previous=store.findCreateRequest(uid,requestId);
            if(!previous.isEmpty()){
                var r=previous.getFirst();long existing=number(r,"article_id");
                if(number(r,"deleted")!=0 || number(r,"is_current")!=1)
                    throw new BusinessException(409,"这次保存已完成，请从草稿箱打开当前内容");
                boolean submitting=Integer.valueOf(1).equals(dto.getStatus());
                String contentHash=hash(encode(new TreeMap<>(payload(dto,submitting))));
                Map<String,Object> result;
                if(number(r,"state")==DRAFT && number(r,"lock_version")==0){
                    dto.setExpectedRevisionId(r.get("revision_id").toString());dto.setExpectedLockVersion(0L);
                    result=save(uid,existing,dto);
                }else if(contentHash.equals(r.get("content_hash")) &&
                         (number(r,"state")==DRAFT && !submitting || number(r,"state")==PENDING && submitting)){
                    result=metadata(r);
                }else throw new BusinessException(409,"首次保存已完成或草稿已变化，请从草稿箱继续编辑");
                result.put("articleId",Long.toString(existing));return result;
            }
        }
        if(!store.findExistingIdentity(aid).isEmpty())
            throw new BusinessException(409,"文章标识已存在");
        var a=new HashMap<String,Object>();a.put("article_id",aid);a.put("user_id",uid);
        a.put("client_request_id",requestId);
        a.put("published_revision_id",0L);a.put("latest_revision_id",0L);a.put("status",0);
        boolean submitting=Integer.valueOf(1).equals(dto.getStatus());
        var result=metadata(revision(append(a,payload(dto,submitting),submitting?PENDING:DRAFT)));
        result.put("articleId",Long.toString(aid));return result;
    }
    private Map<String,Object> legacyPayload(long aid) {
        var detail=articles.selectArticleAndUser(aid);if(detail==null) throw new BusinessException(404,"文章不存在");
        var dto=BeanUtil.copyProperties(detail,ArticleCreateDTO.class,"tags");
        dto.setTagNames(tags.getTagsByArticleId(aid).stream().map(TagVO::getTagName).toList());
        var p=new LinkedHashMap<String,Object>();
        p.put("title",dto.getTitle());p.put("summary",dto.getSummary());p.put("content",dto.getContent());p.put("contentType",dto.getContentType());
        p.put("categoryId",dto.getCategoryId());p.put("coverImage",dto.getCoverImage());p.put("isOriginal",dto.getIsOriginal());p.put("tagNames",dto.getTagNames());return p;
    }
    private void snapshotLegacy(Map<String,Object> a) {
        if(number(a,"latest_revision_id")!=0)return;
        boolean published=number(a,"status")!=0;
        long id=append(a,legacyPayload(number(a,"article_id")),published?APPROVED:DRAFT);
        if(published){store.updatePublishedRevision(id,number(a,"article_id"));a.put("published_revision_id",id);}
    }
    private void log(Map<String,Object> a,long rid,long actor,String action,String reason) {
        store.insertReviewLog(number(a,"article_id"),actor,action,reason,rid);
    }
    private void invalidate(Map<String,Object> a) {
        long aid=number(a,"article_id"),uid=number(a,"user_id");
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization(){@Override public void afterCommit(){redis.deleteArticleDetail(aid);redis.deleteUserSpaceVO(uid);}});
    }
    @Transactional public Map<String,Object> save(Long uid,long aid,ArticleCreateDTO dto) {
        var a=article(aid,uid,false);expected(a,dto.getExpectedRevisionId());
        if(number(a,"status")==2)throw new BusinessException(409,"下架文章不能编辑，请联系管理员");
        boolean submitting=Integer.valueOf(1).equals(dto.getStatus());var p=payload(dto,submitting);
        if(number(a,"latest_revision_id")!=0) {
            var current=revision(number(a,"latest_revision_id"));
            if(number(current,"state")==PENDING)throw new BusinessException(409,"当前版本审核中，请先撤回再编辑");
            expectedLock(current,dto.getExpectedLockVersion());
        }
        snapshotLegacy(a);
        var current=revision(number(a,"latest_revision_id"));long id;
        if(number(current,"state")==DRAFT) {
            id=number(current,"revision_id");String serialized=encode(new TreeMap<>(p));
            if(submitting || !hash(serialized).equals(current.get("content_hash"))) {
                store.saveWorkingRevision(serialized,hash(serialized),submitting?PENDING:DRAFT,submitting?1:0,id);
                if(submitting)log(a,id,uid,"submit","");
            }
        } else id=append(a,p,submitting?PENDING:DRAFT);
        return metadata(revision(id));
    }
    private void projection(Map<String,Object> a,Map<String,Object> p,boolean publish) {
        long aid=number(a,"article_id");
        var content=dto(p);
        var projection=PublishedArticleProjection.builder()
            .articleId(aid).userId(number(a,"user_id")).revisionId(number(a,"latest_revision_id"))
            .title(content.getTitle()).summary(content.getSummary()).content(content.getContent())
            .contentType(content.getContentType())
            .categoryId(content.getCategoryId()==null?null:Long.valueOf(content.getCategoryId()))
            .coverImage(content.getCoverImage()).isOriginal(content.getIsOriginal())
            .tags(String.join(",",content.getTagNames()))
            .requiredLevel(((Number)a.getOrDefault("required_level",0)).intValue()).build();
        if(!Boolean.TRUE.equals(a.get("has_info")))store.insertPublishedProjection(projection);
        store.updatePublishedProjection(projection);
        if(publish) tags.handleArticleTags(aid,dto(p).getTagNames());
        invalidate(a);
    }
    @Transactional public Map<String,Object> submit(Long uid,long aid,String expected) {return submit(uid,aid,expected,null);}
    @Transactional public Map<String,Object> submit(Long uid,long aid,String expected,Long lockVersion) {
        var a=article(aid,uid,false);expected(a,expected);
        if(number(a,"status")==2)throw new BusinessException(409,"下架文章不能提交审核");
        snapshotLegacy(a);var head=revision(number(a,"latest_revision_id"));
        if(number(head,"state")==PENDING)return metadata(head);
        if(number(head,"state")==APPROVED)throw new BusinessException(409,"请先保存修改版本再提交审核");
        expectedLock(head,lockVersion);
        var p=payload(dto(decode(head.get("payload"))),true);
        long id;
        if(number(head,"state")==DRAFT) {
            id=number(head,"revision_id");String serialized=encode(new TreeMap<>(p));
            store.submitWorkingRevision(serialized,hash(serialized),id);
            log(a,id,uid,"submit","");
        } else id=append(a,p,PENDING);
        return metadata(revision(id));
    }
    @Transactional public void withdraw(Long uid,long aid,long rid) {
        var a=article(aid,uid,false);var r=revision(rid);
        if(number(a,"latest_revision_id")!=rid || number(r,"article_id")!=aid || number(r,"state")!=PENDING)
            throw new BusinessException(409,"该版本已处理，请刷新后重试");
        store.withdrawRevision(rid);log(a,rid,uid,"withdraw","");
    }
    @Transactional public void discard(Long uid,long aid,long rid) {
        var a=article(aid,uid,false);var r=revision(rid);
        if(number(a,"published_revision_id")==0 || number(a,"latest_revision_id")!=rid || number(r,"article_id")!=aid || !List.of(0L,3L,4L).contains(number(r,"state")))
            throw new BusinessException(409,"只能丢弃未提交的修改版本");
        store.supersedeRevision(rid);
        store.clearCurrentRevision(aid);
        store.setCurrentRevision(number(a,"published_revision_id"));
        store.restorePublishedHead(aid);log(a,rid,uid,"discard","");
    }
    @Transactional public void delete(Long uid,long aid) {
        var a=article(aid,uid,false);
        if(number(a,"latest_revision_id")!=0)log(a,number(a,"latest_revision_id"),uid,"delete","");
        tags.removeArticleTags(aid);
        store.deleteRevisions(aid);
        store.deletePublishedArticle(aid);
        if(number(a,"status")==1)users.changeArticleCount(uid,-1);
        if(number(a,"published_revision_id")!=0 || number(a,"status")!=0)
            index.publish(aid,"DELETE",RabbitMqConstants.ROUTING_KEY_DELETE);
        invalidate(a);
    }
    private Map<String,Object> metadata(Map<String,Object> r) {
        var result=new LinkedHashMap<String,Object>();result.put("revisionId",r.get("revision_id").toString());
        result.put("version",r.get("version_no"));result.put("state",r.get("state"));result.put("reason",r.get("review_reason"));
        result.put("lockVersion",r.get("lock_version"));result.put("updatedAt",r.get("updated_at"));
        result.put("createdAt",r.get("created_at"));result.put("submittedAt",r.get("submitted_at"));result.put("reviewedAt",r.get("reviewed_at"));return result;
    }
    @Transactional public ArticleDetailVO editable(Long uid,long aid) {
        var a=article(aid,uid,false);if(number(a,"status")==2)throw new BusinessException(409,"文章已下架，暂时无法编辑");
        var detail=articles.selectArticleAndUser(aid);
        if(detail==null){detail=new ArticleDetailVO();detail.setArticleId(Long.toString(aid));detail.setUserId(Long.toString(number(a,"user_id")));detail.setStatus(0);}
        detail.setTags(tags.getTagsByArticleId(aid));detail.setLockVersion(0L);
        long head=number(a,"latest_revision_id");detail.setRevisionId(Long.toString(head));detail.setHasPublishedVersion(number(a,"status")==1);
        detail.setRevisionState(DRAFT);detail.setReviewReason("");
        if(head!=0){var r=revision(head);var p=displayPayload(decode(r.get("payload")));
            BeanUtil.copyProperties(dto(p),detail,"tags","status","expectedRevisionId","expectedLockVersion");
            detail.setLockVersion(number(r,"lock_version"));
            detail.setTags(dto(p).getTagNames().stream().map(name->{var tag=new TagVO();tag.setTagName(name);return tag;}).toList());
            detail.setRevisionState((int)number(r,"state"));detail.setReviewReason(r.get("review_reason").toString());}
        return detail;
    }
    @Transactional public List<Map<String,Object>> history(Long uid,long aid) {
        var a=article(aid,uid,false);
        return store.findHistory(aid).stream().map(this::metadata).toList();
    }
    @Transactional public Map<String,Object> authorDetail(Long uid,long aid,long rid) {
        article(aid,uid,false);var r=revision(rid);
        if(number(r,"article_id")!=aid)throw new BusinessException(404,"版本不存在");
        var result=metadata(r);result.put("payload",decode(r.get("payload")));return result;
    }
    @Transactional public Map<String,Object> restore(Long uid,long aid,long rid,String expected) {return restore(uid,aid,rid,expected,null);}
    @Transactional public Map<String,Object> restore(Long uid,long aid,long rid,String expected,Long lockVersion) {
        article(aid,uid,false);var r=revision(rid);
        if(number(r,"article_id")!=aid)throw new BusinessException(404,"版本不存在");
        var request=dto(decode(r.get("payload")));request.setStatus(0);request.setExpectedRevisionId(expected);
        request.setExpectedLockVersion(lockVersion);
        return save(uid,aid,request);
    }
    /** Private author workspace. Never exposed through public article search. */
    public List<Map<String,Object>> ownDrafts(Long uid,String keyword) {
        if(keyword==null)keyword="";
        if(keyword.length()>200)throw new BusinessException(400,"草稿检索词过长");
        String pattern="%"+keyword.strip().replace("!","!!").replace("%","!%").replace("_","!_")+"%";
        return store.findOwnDrafts(uid,pattern);
    }
    @Transactional public Map<String,Object> ownDraft(Long uid,long aid) {
        var a=article(aid,uid,false);
        if(number(a,"status")==2)throw new BusinessException(404,"草稿不可读取");
        long rid=number(a,"latest_revision_id");
        Map<String,Object> p;
        int state=DRAFT;
        if(rid==0){if(number(a,"status")!=0)throw new BusinessException(404,"没有修改草稿");p=legacyPayload(aid);}
        else {var r=revision(rid);state=(int)number(r,"state");if(!List.of(DRAFT,PENDING,REJECTED,WITHDRAWN).contains(state))throw new BusinessException(404,"没有修改草稿");p=decode(r.get("payload"));}
        var result=new LinkedHashMap<String,Object>();
        result.put("articleId",Long.toString(aid));result.put("revisionId",Long.toString(rid));
        result.put("lockVersion",rid==0?0L:number(revision(rid),"lock_version"));result.put("state",state);
        result.put("editable",state!=PENDING);result.put("payload",p);
        return result;
    }
    @Transactional public void updateAgentDraft(Long uid,long aid,String expected,String title,String summary,String html) {
        updateAgentDraft(uid,aid,expected,null,title,summary,html);
    }
    @Transactional public void updateAgentDraft(Long uid,long aid,String expected,Long lockVersion,String title,String summary,String html) {
        var source=ownDraft(uid,aid);
        if(!Boolean.TRUE.equals(source.get("editable")))throw new BusinessException(409,"当前版本审核中，请先撤回");
        @SuppressWarnings("unchecked") var p=(Map<String,Object>)source.get("payload");
        var request=dto(p);request.setTitle(title);request.setSummary(summary);request.setContent(html);
        request.setContentType(1);request.setStatus(0);request.setExpectedRevisionId(expected);
        request.setExpectedLockVersion(lockVersion);
        save(uid,aid,request);
    }
    public PageVO<Map<String,Object>> work(Long uid,Integer state,int page,int size) {
        bounds(page,size);if(state!=null && !List.of(0,1,3,4).contains(state))throw new BusinessException(400,"版本状态无效");
        long total=store.countWorkspace(uid,state);
        var rows=store.findWorkspace(uid,state,size,(page-1)*size);
        return new PageVO<>(rows,total,(long)size,(long)page,(total+size-1)/size);
    }
    static void bounds(int page,int size){if(page<1 || page>10000 || size<1 || size>100)throw new BusinessException(400,"分页参数无效");}
    public PageVO<Map<String,Object>> queue(Long uid,Integer state,int page,int size) {
        if(!access.isAdmin(uid) && !access.hasPermission(uid,"reviews.read"))throw new BusinessException(403,"没有文章审核权限");bounds(page,size);
        if(state==null)state=PENDING;if(!List.of(1,2,3,4).contains(state))throw new BusinessException(400,"审核状态无效");
        long total=store.countReviewQueue(state);
        var rows=store.findReviewQueue(state,size,(page-1)*size);
        return new PageVO<>(rows,total,(long)size,(long)page,(total+size-1)/size);
    }
    @Transactional public Map<String,Object> reviewDetail(Long uid,long rid) {
        if(!access.isAdmin(uid) && !access.hasPermission(uid,"reviews.read"))throw new BusinessException(403,"没有文章审核权限");
        // Look up the relation first, then always acquire locks in article -> revision order.
        var a=article(revisionArticle(rid),uid,true);var r=revision(rid);
        var result=metadata(r);result.put("articleId",r.get("article_id").toString());result.put("payload",displayPayload(decode(r.get("payload"))));
        long base=number(r,"base_revision_id");
        result.put("publicPayload",base!=0?displayPayload(decode(revision(base).get("payload"))):null);
        result.put("hasPublishedVersion",base!=0);result.put("contentHash",r.get("content_hash"));
        result.put("logs",store.findReviewLogs(number(a,"article_id")));return result;
    }
    @Transactional public void review(Long uid,long rid,String decision,String reason) {
        if(!access.isAdmin(uid) && !access.hasPermission(uid,"reviews.manage"))throw new BusinessException(403,"没有文章审核权限");
        if(!List.of("approve","reject").contains(decision==null?"":decision))throw new BusinessException(400,"审核操作无效");
        reason=reason==null?"":reason.strip();if(reason.length()>1000 || (decision.equals("reject") && reason.isEmpty()))throw new BusinessException(400,"驳回需填写原因，最多1000字");
        var a=article(revisionArticle(rid),uid,true);var r=revision(rid);
        if(number(r,"state")!=PENDING || number(a,"latest_revision_id")!=rid)throw new BusinessException(409,"该版本已处理或已撤回，请刷新");
        if(decision.equals("approve")) {
            if(number(a,"status")==2)throw new BusinessException(409,"文章已下架，请先处理下架状态");
            if(number(r,"base_revision_id")!=number(a,"published_revision_id"))throw new BusinessException(409,"公开版本已变化，请重新提交审核");
            var stored=decode(r.get("payload"));
            if(!hash(encode(new TreeMap<>(stored))).equals(r.get("content_hash")))throw new BusinessException(409,"审核内容校验失败，请重新提交");
            var p=payload(dto(stored),true);projection(a,p,true);
            if(number(a,"status")==0)users.changeArticleCount(number(a,"user_id"),1);
            store.publishRevision(rid,number(a,"article_id"));
            index.publish(number(a,"article_id"),"UPDATE",RabbitMqConstants.ROUTING_KEY_UPDATE);
        }
        store.reviewRevision(decision.equals("approve")?APPROVED:REJECTED,reason,uid,rid);
        log(a,rid,uid,decision,reason);
        var reviewer=users.selectById(uid);
        String preview=reason;
        if(preview.codePointCount(0,preview.length())>200)
            preview=preview.substring(0,preview.offsetByCodePoints(0,197))+"…";
        notifications.send(com.easyjob.dto.NotificationMessage.builder()
            .userId(number(a,"user_id")).senderId(uid)
            .senderNickname(reviewer==null?"管理员":reviewer.getNickName())
            .senderAvatar(reviewer==null?null:reviewer.getAvatar())
            .type(decision.equals("approve")?com.easyjob.enums.NotificationTypeEnum.REVIEW_APPROVED.getCode():com.easyjob.enums.NotificationTypeEnum.REVIEW_REJECTED.getCode())
            .articleId(number(a,"article_id")).articleTitle(String.valueOf(decode(r.get("payload")).get("title")))
            .targetId(rid).targetPreview(preview.isEmpty()?null:preview)
            .content("审核"+(decision.equals("approve")?"通过":"驳回")+"了你的文章（V"+number(r,"version_no")+"）")
            .build());
    }
}
