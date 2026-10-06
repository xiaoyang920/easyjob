package com.easyjob.service;

import cn.hutool.core.bean.BeanUtil;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.dto.ArticleCreateDTO;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.UserMapper;
import com.easyjob.utils.HtmlContentSanitizer;
import com.easyjob.vo.ArticleDetailVO;
import com.easyjob.vo.PageVO;
import com.easyjob.vo.TagVO;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.jsoup.Jsoup;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.Statement;
import java.util.*;

/** Immutable author snapshots, with article_info as the approved public projection. */
@Service @RequiredArgsConstructor
public class ArticleRevisionService {
    public static final int DRAFT=0, PENDING=1, APPROVED=2, REJECTED=3, WITHDRAWN=4, SUPERSEDED=5;
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final ArticleMapper articles;
    private final UserMapper users;
    private final ArticleTagService tags;
    private final ArticleAccessService access;
    private final ArticleIndexPublisher index;
    private final RedisComponent redis;
    private final com.easyjob.service.impl.NotificationServiceImpl notifications;

    private static long number(Map<String,Object> row,String key){return ((Number)row.get(key)).longValue();}
    private Map<String,Object> article(long aid,Long uid,boolean admin) {
        if(admin && !access.isAdmin(uid)) throw new BusinessException(403,"只有管理员可以审核文章");
        var rows=jdbc.queryForList("SELECT * FROM article_info WHERE article_id=? AND deleted=0 FOR UPDATE",aid);
        if(rows.isEmpty() || (!admin && !Objects.equals(number(rows.getFirst(),"user_id"),uid)))
            throw new BusinessException(404,"文章不存在或无权操作");
        return rows.getFirst();
    }
    private Map<String,Object> revision(long rid) {
        var rows=jdbc.queryForList("SELECT * FROM article_revision WHERE revision_id=? FOR UPDATE",rid);
        if(rows.isEmpty()) throw new BusinessException(404,"版本不存在");
        return rows.getFirst();
    }
    private long revisionArticle(long rid) {
        var rows=jdbc.queryForList("SELECT article_id FROM article_revision WHERE revision_id=?",rid);
        if(rows.isEmpty())throw new BusinessException(404,"版本不存在");
        return number(rows.getFirst(),"article_id");
    }
    private void expected(Map<String,Object> a,String expected) {
        long id;
        try {id=Long.parseLong(expected);} catch(Exception e){throw new BusinessException(400,"请重新打开编辑器获取当前版本");}
        if(id!=number(a,"latest_revision_id")) throw new BusinessException(409,"文章版本已变化，请刷新后重试");
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
        if(dto.getSummary()!=null && dto.getSummary().length()>500) throw new BusinessException(400,"摘要不能超过500字");
        if(dto.getContent()==null || dto.getContent().length()>300000) throw new BusinessException(400,"正文为空或过长");
        if(dto.getContentType()==null || (dto.getContentType()!=1 && dto.getContentType()!=2)) throw new BusinessException(400,"正文格式无效");
        String content=dto.getContentType()==1?HtmlContentSanitizer.clean(dto.getContent(),true):dto.getContent();
        if(submitting && (dto.getContentType()==1?Jsoup.parse(content).text().isBlank():content.isBlank()))
            throw new BusinessException(400,"请输入文章正文");
        Long category=null;
        if(dto.getCategoryId()!=null && !dto.getCategoryId().isBlank()) {
            try{category=Long.valueOf(dto.getCategoryId());}catch(Exception e){throw new BusinessException(400,"分类无效");}
            if(jdbc.queryForObject("SELECT COUNT(*) FROM category WHERE category_id=? AND status=1",Integer.class,category)!=1)
                throw new BusinessException(400,"请选择有效分类");
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
        if(p.get("categoryId")!=null){var names=jdbc.queryForList("SELECT category_name FROM category WHERE category_id=?",p.get("categoryId"));p.put("categoryName",names.isEmpty()?"分类已删除":names.getFirst().get("category_name"));}
        return p;
    }
    private long append(Map<String,Object> a,Map<String,Object> p,int state) {
        long aid=number(a,"article_id");
        int version=jdbc.queryForObject("SELECT COALESCE(MAX(version_no),0)+1 FROM article_revision WHERE article_id=?",Integer.class,aid);
        String serialized=encode(new TreeMap<>(p));var key=new GeneratedKeyHolder();
        jdbc.update(connection->{var statement=connection.prepareStatement("INSERT INTO article_revision(article_id,version_no,author_id,base_revision_id,state,payload,content_hash,submitted_at) VALUES(?,?,?,?,?,?,?,IF(?=1,NOW(3),NULL))",Statement.RETURN_GENERATED_KEYS);
            statement.setLong(1,aid);statement.setInt(2,version);statement.setLong(3,number(a,"user_id"));
            statement.setLong(4,number(a,"published_revision_id"));statement.setInt(5,state);statement.setString(6,serialized);
            statement.setString(7,hash(serialized));statement.setInt(8,state);return statement;},key);
        long id=Objects.requireNonNull(key.getKey()).longValue();
        jdbc.update("UPDATE article_info SET latest_revision_id=? WHERE article_id=?",id,aid);a.put("latest_revision_id",id);
        if(state==PENDING) log(a,id,number(a,"user_id"),"submit","");
        return id;
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
        if(published){jdbc.update("UPDATE article_info SET published_revision_id=? WHERE article_id=?",id,number(a,"article_id"));a.put("published_revision_id",id);}
    }
    private void log(Map<String,Object> a,long rid,long actor,String action,String reason) {
        jdbc.update("INSERT INTO article_review_log(article_id,revision_id,actor_id,action,reason,content_hash) SELECT ?,revision_id,?,?,?,content_hash FROM article_revision WHERE revision_id=?",number(a,"article_id"),actor,action,reason,rid);
    }
    private void invalidate(Map<String,Object> a) {
        long aid=number(a,"article_id"),uid=number(a,"user_id");
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization(){@Override public void afterCommit(){redis.deleteArticleDetail(aid);redis.deleteUserSpaceVO(uid);}});
    }
    @Transactional public Map<String,Object> save(Long uid,long aid,ArticleCreateDTO dto) {
        var a=article(aid,uid,false);expected(a,dto.getExpectedRevisionId());
        if(number(a,"status")==2)throw new BusinessException(409,"下架文章不能编辑，请联系管理员");
        var p=payload(dto,Integer.valueOf(1).equals(dto.getStatus()));
        if(number(a,"latest_revision_id")!=0 && number(revision(number(a,"latest_revision_id")),"state")==PENDING)
            throw new BusinessException(409,"当前版本审核中，请先撤回再编辑");
        snapshotLegacy(a);
        jdbc.update("UPDATE article_revision SET state=5 WHERE revision_id=? AND state=0",number(a,"latest_revision_id"));
        long id=append(a,p,Integer.valueOf(1).equals(dto.getStatus())?PENDING:DRAFT);
        if(number(a,"status")==0) projection(a,p,false);
        return metadata(revision(id));
    }
    private void projection(Map<String,Object> a,Map<String,Object> p,boolean publish) {
        long aid=number(a,"article_id");
        jdbc.update("UPDATE article_info SET title=?,summary=?,content=?,content_type=?,category_id=?,cover_image=?,is_original=?,tags=?,update_time=NOW(3) WHERE article_id=?",p.get("title"),p.get("summary"),p.get("content"),p.get("contentType"),p.get("categoryId"),p.get("coverImage"),p.get("isOriginal"),String.join(",",dto(p).getTagNames()),aid);
        if(publish) tags.handleArticleTags(aid,dto(p).getTagNames());
        invalidate(a);
    }
    @Transactional public Map<String,Object> submit(Long uid,long aid,String expected) {
        var a=article(aid,uid,false);expected(a,expected);
        if(number(a,"status")==2)throw new BusinessException(409,"下架文章不能提交审核");
        snapshotLegacy(a);var head=revision(number(a,"latest_revision_id"));
        if(number(head,"state")==PENDING)return metadata(head);
        if(number(head,"state")==APPROVED)throw new BusinessException(409,"请先保存修改版本再提交审核");
        var p=payload(dto(decode(head.get("payload"))),true);
        long id=append(a,p,PENDING);return metadata(revision(id));
    }
    @Transactional public void withdraw(Long uid,long aid,long rid) {
        var a=article(aid,uid,false);var r=revision(rid);
        if(number(a,"latest_revision_id")!=rid || number(r,"article_id")!=aid || number(r,"state")!=PENDING)
            throw new BusinessException(409,"该版本已处理，请刷新后重试");
        jdbc.update("UPDATE article_revision SET state=4 WHERE revision_id=?",rid);log(a,rid,uid,"withdraw","");
    }
    @Transactional public void discard(Long uid,long aid,long rid) {
        var a=article(aid,uid,false);var r=revision(rid);
        if(number(a,"published_revision_id")==0 || number(a,"latest_revision_id")!=rid || number(r,"article_id")!=aid || !List.of(0L,3L,4L).contains(number(r,"state")))
            throw new BusinessException(409,"只能丢弃未提交的修改版本");
        jdbc.update("UPDATE article_revision SET state=5 WHERE revision_id=?",rid);
        jdbc.update("UPDATE article_info SET latest_revision_id=published_revision_id WHERE article_id=?",aid);log(a,rid,uid,"discard","");
    }
    private Map<String,Object> metadata(Map<String,Object> r) {
        var result=new LinkedHashMap<String,Object>();result.put("revisionId",r.get("revision_id").toString());
        result.put("version",r.get("version_no"));result.put("state",r.get("state"));result.put("reason",r.get("review_reason"));
        result.put("createdAt",r.get("created_at"));result.put("submittedAt",r.get("submitted_at"));result.put("reviewedAt",r.get("reviewed_at"));return result;
    }
    @Transactional public ArticleDetailVO editable(Long uid,long aid) {
        var a=article(aid,uid,false);if(number(a,"status")==2)throw new BusinessException(409,"文章已下架，暂时无法编辑");
        var detail=articles.selectArticleAndUser(aid);detail.setTags(tags.getTagsByArticleId(aid));
        long head=number(a,"latest_revision_id");detail.setRevisionId(Long.toString(head));detail.setHasPublishedVersion(number(a,"status")==1);
        detail.setRevisionState(DRAFT);detail.setReviewReason("");
        if(head!=0){var r=revision(head);var p=decode(r.get("payload"));
            BeanUtil.copyProperties(dto(p),detail,"tags","status","expectedRevisionId");
            detail.setTags(dto(p).getTagNames().stream().map(name->{var tag=new TagVO();tag.setTagName(name);return tag;}).toList());
            detail.setRevisionState((int)number(r,"state"));detail.setReviewReason(r.get("review_reason").toString());}
        return detail;
    }
    @Transactional public List<Map<String,Object>> history(Long uid,long aid) {
        var a=article(aid,uid,false);
        return jdbc.queryForList("SELECT * FROM article_revision WHERE article_id=? ORDER BY version_no DESC LIMIT 100",aid).stream().map(this::metadata).toList();
    }
    @Transactional public Map<String,Object> authorDetail(Long uid,long aid,long rid) {
        article(aid,uid,false);var r=revision(rid);
        if(number(r,"article_id")!=aid)throw new BusinessException(404,"版本不存在");
        var result=metadata(r);result.put("payload",decode(r.get("payload")));return result;
    }
    @Transactional public Map<String,Object> restore(Long uid,long aid,long rid,String expected) {
        article(aid,uid,false);var r=revision(rid);
        if(number(r,"article_id")!=aid)throw new BusinessException(404,"版本不存在");
        var request=dto(decode(r.get("payload")));request.setStatus(0);request.setExpectedRevisionId(expected);
        return save(uid,aid,request);
    }
    public PageVO<Map<String,Object>> work(Long uid,Integer state,int page,int size) {
        bounds(page,size);if(state!=null && !List.of(0,1,3,4).contains(state))throw new BusinessException(400,"版本状态无效");
        String from="FROM article_info a LEFT JOIN article_revision r ON r.revision_id=a.latest_revision_id WHERE a.user_id=? AND a.deleted=0 AND (r.state IN(0,1,3,4) OR (a.status=0 AND r.revision_id IS NULL))";
        var args=new ArrayList<Object>();args.add(uid);if(state!=null){from+=" AND COALESCE(r.state,0)=?";args.add(state);}
        long total=jdbc.queryForObject("SELECT COUNT(*) "+from,Long.class,args.toArray());args.add(size);args.add((page-1)*size);
        var rows=jdbc.queryForList("SELECT CAST(a.article_id AS CHAR) AS articleId,CAST(a.latest_revision_id AS CHAR) AS revisionId,a.status AS articleStatus,COALESCE(r.state,0) AS revisionState,r.version_no AS version,r.review_reason AS reviewReason,COALESCE(JSON_UNQUOTE(JSON_EXTRACT(r.payload,'$.title')),a.title) AS title,COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(r.payload,'$.summary')),'null'),a.summary) AS summary,COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(r.payload,'$.coverImage')),'null'),a.cover_image) AS coverImage,COALESCE(r.created_at,a.update_time) AS updateTime "+from+" ORDER BY COALESCE(r.created_at,a.update_time) DESC,a.article_id DESC LIMIT ? OFFSET ?",args.toArray());
        return new PageVO<>(rows,total,(long)size,(long)page,(total+size-1)/size);
    }
    static void bounds(int page,int size){if(page<1 || page>10000 || size<1 || size>100)throw new BusinessException(400,"分页参数无效");}
    public PageVO<Map<String,Object>> queue(Long uid,Integer state,int page,int size) {
        if(!access.isAdmin(uid))throw new BusinessException(403,"只有管理员可以审核文章");bounds(page,size);
        if(state==null)state=PENDING;if(!List.of(1,2,3,4).contains(state))throw new BusinessException(400,"审核状态无效");
        String from="FROM article_revision r JOIN article_info a ON a.article_id=r.article_id LEFT JOIN user_info u ON u.user_id=r.author_id WHERE a.deleted=0 AND r.state=?";
        long total=jdbc.queryForObject("SELECT COUNT(*) "+from,Long.class,state);
        var rows=jdbc.queryForList("SELECT CAST(r.revision_id AS CHAR) AS revisionId,CAST(r.article_id AS CHAR) AS articleId,r.version_no AS version,r.state,JSON_UNQUOTE(JSON_EXTRACT(r.payload,'$.title')) AS title,u.nick_name AS authorName,r.submitted_at AS submittedAt,r.review_reason AS reason "+from+" ORDER BY r.submitted_at,r.revision_id LIMIT ? OFFSET ?",state,size,(page-1)*size);
        return new PageVO<>(rows,total,(long)size,(long)page,(total+size-1)/size);
    }
    @Transactional public Map<String,Object> reviewDetail(Long uid,long rid) {
        if(!access.isAdmin(uid))throw new BusinessException(403,"只有管理员可以审核文章");
        // Look up the relation first, then always acquire locks in article -> revision order.
        var a=article(revisionArticle(rid),uid,true);var r=revision(rid);
        var result=metadata(r);result.put("articleId",r.get("article_id").toString());result.put("payload",displayPayload(decode(r.get("payload"))));
        long base=number(r,"base_revision_id");
        result.put("publicPayload",base!=0?displayPayload(decode(revision(base).get("payload"))):null);
        result.put("hasPublishedVersion",base!=0);result.put("contentHash",r.get("content_hash"));
        result.put("logs",jdbc.queryForList("SELECT CAST(id AS CHAR) AS id,action,reason,created_at AS createdAt,CAST(actor_id AS CHAR) AS actorId FROM article_review_log WHERE article_id=? ORDER BY id DESC LIMIT 100",number(a,"article_id")));return result;
    }
    @Transactional public void review(Long uid,long rid,String decision,String reason) {
        if(!access.isAdmin(uid))throw new BusinessException(403,"只有管理员可以审核文章");
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
            jdbc.update("UPDATE article_info SET status=1,published_revision_id=?,publish_time=COALESCE(publish_time,NOW()) WHERE article_id=?",rid,number(a,"article_id"));
            index.publish(number(a,"article_id"),"UPDATE",RabbitMqConstants.ROUTING_KEY_UPDATE);
        }
        jdbc.update("UPDATE article_revision SET state=?,review_reason=?,reviewer_id=?,reviewed_at=NOW(3) WHERE revision_id=?",decision.equals("approve")?APPROVED:REJECTED,reason,uid,rid);
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
