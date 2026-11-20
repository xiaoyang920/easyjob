package com.easyjob.service;

import com.baomidou.mybatisplus.core.toolkit.IdWorker;
import com.easyjob.config.ChatWebSocketHandler;
import com.easyjob.exception.BusinessException;
import com.easyjob.vo.ConversationVO;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import com.easyjob.mapper.SocialMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.sql.Timestamp;
import java.util.*;
import com.easyjob.service.SocialPolicy.Decision;
import com.easyjob.vo.MessageVO;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;

@Service @RequiredArgsConstructor @lombok.extern.slf4j.Slf4j
public class SocialService {
    private final SocialMapper mapper;
    @org.springframework.beans.factory.annotation.Autowired private com.easyjob.service.impl.NotificationServiceImpl notifications;
    @org.springframework.beans.factory.annotation.Autowired private com.easyjob.component.RedisComponent redis;
    @Value("${easyjob.social.daily-request-limit:20}") private int dailyLimit=20;
    @Value("${easyjob.social.enabled:true}") private boolean enabled=true;
    private static Map<String,Object> args(Object... kv) {
        Map<String,Object> result=new HashMap<>(); for(int i=0;i<kv.length;i+=2)result.put((String)kv[i],kv[i+1]);return result;
    }
    private Map<String,Object> required(Map<String,Object> row){if(row==null)throw new BusinessException(404,"记录不存在");return row;}
    private static long n(Map<String,?> r,String k){Object v=r.get(k);return v instanceof Number num?num.longValue():v instanceof Boolean flag?(flag?1:0):v==null?0:Long.parseLong(v.toString());}
    private static String s(Map<String,?> r,String k){return Objects.toString(r.get(k),"");}
    private static boolean b(Map<String,?> r,String k){Object v=r.get(k);return Boolean.TRUE.equals(v)||v instanceof Number num&&num.intValue()!=0;}
    private static java.time.LocalDateTime time(Map<String,?> r,String k){Object v=r.get(k);return v instanceof Timestamp t?t.toLocalDateTime():v instanceof java.time.LocalDateTime t?t:null;}
    private Map<String,Object> pair(long a,long b){if(a==b || a<=0 || b<=0)throw new BusinessException(400,"请选择其他用户");return args("lo",Math.min(a,b),"hi",Math.max(a,b));}
    private Map<String,Object> lockPair(long a,long b){
        Map<String, Object> p=pair(a,b);mapper.ensurePair(p);
        return required(mapper.lockPair(p));
    }
    private void active(long uid){if(mapper.countActiveUser(args("id",uid))!=1)throw new BusinessException(403,"用户暂不可用");}
    private boolean blocked(long a,long b){return mapper.countBlocks(args("a",a,"b",b))>0;}
    private boolean follows(long a,long b){return mapper.countFollows(args("a",a,"b",b))>0;}
    private boolean mutual(long a,long b){return follows(a,b)&&follows(b,a);}
    private void accepted(Map<String,Object> d,String source){mapper.acceptPair(args("source",source,"lo",n(d,"user_low_id"),"hi",n(d,"user_high_id")));}
    private void ensureEnabled(){if(!enabled)throw new BusinessException(503,"朋友功能暂未开放");}
    private static void afterCommit(Runnable task){Runnable safe=()->{try{task.run();}catch(RuntimeException unavailable){log.warn("Social change saved; realtime refresh unavailable",unavailable);}};if(TransactionSynchronizationManager.isSynchronizationActive())TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization(){@Override public void afterCommit(){safe.run();}});else safe.run();}
    private void changed(long a,long b){afterCommit(()->{for(long uid:new long[]{a,b}){ChatWebSocketHandler.sendToUser(uid,Map.of("type","social_update"));ChatWebSocketHandler.refreshPresence(uid);}});}

    @PostConstruct public void presencePolicy(){ChatWebSocketHandler.presenceAudience=this::presenceAudience;}
    public Set<Long> presenceAudience(long uid){
        HashSet<Long> result=new HashSet<Long>();
        for(Map<String, Object> r:mapper.presenceAudience(args("me",uid)))result.add(n(r,"uid"));return result;
    }
    public Map<String,Object> relationship(long me,long target){
        Map<String, Object> row=required(mapper.findPerson(args("me",me,"target",target)));
        row.put("isFriend",b(row,"isFollowing")&&b(row,"isFollowedBy")&&!b(row,"isBlockedByMe")&&!b(row,"blockedOther")&&n(row,"accountStatus")==1);
        return publicPerson(row);
    }
    public List<Map<String,Object>> relationships(long me,List<Long> ids){
        if(ids.size()>100)throw new BusinessException(400,"每次最多查询100位用户");if(ids.isEmpty())return List.of();
        List<Map<String, Object>> list=mapper.findPeople(args("me",me,"ids",ids));
        for(Map<String, Object> row:list){row.put("isFriend",b(row,"isFollowing")&&b(row,"isFollowedBy")&&!b(row,"isBlockedByMe")&&!b(row,"blockedOther")&&n(row,"accountStatus")==1);publicPerson(row);}return list;
    }
    public Map<String,Object> contacts(long me,String kind,String query,int page,int size){
        ensureEnabled();if(page<1||page>100000||size<1||size>50)throw new BusinessException(400,"分页范围无效");
        if(!Set.of("friends","followers","following","blocked").contains(kind))throw new BusinessException(400,"联系人类型无效");
        Map<String, Object> p=args("me",me,"q","%"+Objects.toString(query,"").replace("!","!!").replace("%","!%").replace("_","!_")+"%","offset",(page-1)*size,"size",size);
        p.put("kind",kind);List<Map<String, Object>> list=mapper.contacts(p);
        long total=mapper.countContacts(p);
        for(Map<String, Object> row:list){row.put("isFriend",b(row,"isFollowing")&&b(row,"isFollowedBy")&&!b(row,"isBlockedByMe")&&!b(row,"blockedOther"));publicPerson(row);}
        return Map.of("records",list,"total",total,"pages",(total+size-1)/size);
    }
    private Map<String,Object> publicPerson(Map<String,Object> row){for(String key:List.of("isFollowing","isFollowedBy","isBlockedByMe"))row.put(key,b(row,key));row.remove("blockedOther");row.remove("allowRequests");row.remove("accountStatus");return row;}
    @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED) public void follow(long me,long target,boolean value){
        active(me);active(target);Map<String, Object> d=lockPair(me,target);
        lockUsers(me,target);
        if(value&&blocked(me,target))throw new BusinessException(403,"暂时无法关注该用户");
        boolean modified=follows(me,target)!=value;
        if(modified){
            if(value)mapper.insertFollow(args("me",me,"target",target));
            else mapper.deleteFollow(args("me",me,"target",target));
            recount(me,target);
        }
        if(mutual(me,target)&&n(d,"conversation_id")>0)accepted(d,"MUTUAL");changed(me,target);
        if(modified){
            invalidateProfiles(me,target);
            if(value&&notifications!=null){Map<String, Object> person=required(mapper.notificationPerson(args("id",me)));notifications.send(com.easyjob.dto.NotificationMessage.builder().userId(target).senderId(me).senderNickname(s(person,"nick_name")).senderAvatar(s(person,"avatar")).type(4).targetId(me).content("关注了你").build());}
        }
    }
    private void recount(long a,long b){for(long uid:new long[]{Math.min(a,b),Math.max(a,b)})mapper.recountFollowers(args("id",uid));}
    private void lockUsers(long a,long b){mapper.lockUsers(pair(a,b));}
    private void invalidateProfiles(long a,long b){afterCommit(()->{try{if(redis!=null){redis.deleteUserSpaceVO(a);redis.deleteUserSpaceVO(b);}}catch(RuntimeException failure){log.warn("Relationship saved; profile cache invalidation unavailable");}});}
    @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED) public void remark(long me,long target,String value){
        active(target);String text=Objects.toString(value,"").strip();if(text.codePointCount(0,text.length())>50)throw new BusinessException(400,"备注最多50字");
        mapper.saveRemark(args("me",me,"target",target,"text",text));changed(me,target);
    }
    @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED) public void block(long me,long target,boolean value){
        active(me);active(target);Map<String, Object> d=lockPair(me,target);
        lockUsers(me,target);
        if(value){mapper.insertBlock(args("me",me,"target",target));
            mapper.deletePairFollows(args("me",me,"target",target));recount(me,target);
            mapper.declinePair(args("target",target,"lo",n(d,"user_low_id"),"hi",n(d,"user_high_id")));
        }else mapper.deleteBlock(args("me",me,"target",target));invalidateProfiles(me,target);changed(me,target);
    }
    public Map<String,Object> settings(long me){return Map.of("enabled",enabled,"allowMessageRequests",mapper.countRequestsDisabled(args("me",me))==0);}
    @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED) public void settings(long me,boolean allow){mapper.saveSettings(args("me",me,"allow",allow?1:0));afterCommit(()->ChatWebSocketHandler.sendToUser(me,Map.of("type","social_update")));}

    @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED) public ConversationVO open(long me,long target){
        active(me);active(target);Map<String, Object> d=lockPair(me,target);
        if(blocked(me,target)&&n(d,"conversation_id")==0)throw new BusinessException(403,"暂时无法向该用户发送消息");
        long cid=n(d,"conversation_id");
        if(cid==0){cid=IdWorker.getId();Map<String, Object> p=args("cid",cid,"me",me,"lo",Math.min(me,target),"hi",Math.max(me,target));
            mapper.createConversation(p);
            for(long uid:new long[]{me,target})mapper.addMember(args("id",IdWorker.getId(),"cid",cid,"uid",uid));
            mapper.attachConversation(p);
        }
        mapper.restoreMember(args("cid",cid,"me",me));return conversation(cid,me);
    }
    public long canonical(long cid){List<Map<String, Object>> alias=mapper.canonicalAliases(args("cid",cid));return alias.isEmpty()?cid:n(alias.getFirst(),"conversation_id");}
    public long other(long cid,long me){return n(required(mapper.otherMember(args("cid",canonical(cid),"me",me))),"user_id");}
    public void lockChat(long cid,long me){
        cid=canonical(cid);if(mapper.countMembership(args("cid",cid,"me",me))!=1)throw new BusinessException(403,"用户不是会话成员");
        lockPair(me,other(cid,me));
    }
    public void admit(long cid,long me,int type,String text){
        long target=other(cid,me);active(me);active(target);Map<String, Object> d=lockPair(me,target);
        Map<String, Object> row=required(mapper.findPerson(args("me",me,"target",target)));
        Decision decision=decision(row,d,me);
        if(!decision.canMessage())throw new BusinessException(403,decision.reason());
        if(!enabled&&!decision.canSendRich())throw new BusinessException(503,"消息请求暂未开放");
        if(decision.canSendRich()){
            if(!"ACCEPTED".equals(s(d,"state")))accepted(d,mutual(me,target)?"MUTUAL":"REPLY");
        }else{
            if(type!=1||text.codePointCount(0,text.length())>300)throw new BusinessException(400,"消息请求只支持一条不超过300字的文字招呼");
            mapper.ensureSettings(args("me",me));
            required(mapper.lockSettings(args("me",me)));
            if(mapper.countRecentRequests(args("me",me))>=dailyLimit)throw new BusinessException(429,"今天的消息请求较多，请稍后再试");
            mapper.requestPair(args("me",me,"lo",Math.min(me,target),"hi",Math.max(me,target)));
        }
        changed(me,target);
    }
    private SocialPolicy.Decision decision(Map<String,Object> person,Map<String,Object> d,long me){return SocialPolicy.decide(new SocialPolicy.Facts(n(person,"accountStatus")==1,b(person,"isBlockedByMe")||b(person,"blockedOther"),b(person,"isFollowing")&&b(person,"isFollowedBy"),s(d,"state"),d.get("initiator_id")==null?null:n(d,"initiator_id"),me,b(person,"allowRequests")));}
    private ConversationVO view(Map<String,Object> r,long me){
        Map<String, Object> d=args("state",s(r,"requestState"),"initiator_id",r.get("initiatorId"));Decision policy=decision(r,d,me);ConversationVO vo=new ConversationVO();
        if(!enabled&&!policy.canSendRich())policy=new SocialPolicy.Decision(false,false,"消息请求暂未开放");
        vo.setConversationId(Long.toString(n(r,"conversationId")));vo.setConversationType(1);vo.setOtherUserId(s(r,"otherUserId"));vo.setOtherUserName(s(r,"otherUserName"));vo.setOtherUserAvatar(s(r,"otherUserAvatar"));vo.setLastMessage(s(r,"lastMessage"));vo.setLastMessageTime(time(r,"lastMessageTime"));vo.setUnreadCount((int)n(r,"unreadCount"));vo.setIsMuted(b(r,"isMuted"));vo.setIsTop(b(r,"isTop"));
        vo.setRemark(s(r,"remark"));vo.setIsFollowing(b(r,"isFollowing"));vo.setIsFollowedBy(b(r,"isFollowedBy"));vo.setIsBlockedByMe(b(r,"isBlockedByMe"));vo.setRequestState(s(r,"requestState"));vo.setRequestIncoming(n(r,"initiatorId")>0&&n(r,"initiatorId")!=me);vo.setRequestUnseen(r.get("viewedAt")==null);vo.setCanMessage(policy.canMessage());vo.setCanSendRich(policy.canSendRich());vo.setSendReason(policy.reason());vo.setLastReadMessageId(Long.toString(n(r,"lastReadMessageId")));return vo;
    }
    public ConversationVO conversation(long cid,long me){return view(required(mapper.conversation(args("me",me,"cid",canonical(cid)))),me);}
    public List<ConversationVO> conversations(long me,boolean requests){
        if(requests&&!enabled)return List.of();
        return mapper.conversations(args("me",me,"requests",requests)).stream().filter(r->!requests||(!b(r,"isBlockedByMe")&&!b(r,"blockedOther")&&n(r,"accountStatus")==1)).map(r->view(r,me)).toList();
    }
    @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED) public ConversationVO handleRequest(long cid,long me,String action){
        lockChat(cid,me);cid=canonical(cid);long target=other(cid,me);Map<String, Object> d=lockPair(me,target);
        if(n(d,"initiator_id")==me||n(d,"initiator_id")==0)throw new BusinessException(403,"只能处理收到的消息请求");
        if("view".equals(action)){mapper.markViewed(args("cid",cid));}
        else if("accept".equals(action)){
            if(blocked(me,target))throw new BusinessException(403,"暂时无法向该用户发送消息");
            if(!"ACCEPTED".equals(s(d,"state"))&&!"PENDING".equals(s(d,"state")))throw new BusinessException(409,"请求状态已改变");
            accepted(d,"EXPLICIT");mapper.restoreConversation(args("cid",cid));
        }else if("decline".equals(action)){
            if(!Set.of("PENDING","DECLINED").contains(s(d,"state")))throw new BusinessException(409,"请求状态已改变");
            mapper.declineRequest(args("cid",cid));
        }else throw new BusinessException(400,"请求操作无效");
        changed(me,target);return conversation(cid,me);
    }
    @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED) public ConversationVO preferences(long cid,long me,Boolean top,Boolean muted){
        lockChat(cid,me);cid=canonical(cid);if(top!=null)mapper.pinConversation(args("v",top?1:0,"cid",cid,"me",me));if(muted!=null)mapper.muteConversation(args("v",muted?1:0,"cid",cid,"me",me));changed(me,other(cid,me));return conversation(cid,me);
    }
    @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED) public Map<String,Object> read(long cid,long me,Long through){
        lockChat(cid,me);cid=canonical(cid);required(mapper.lockConversation(args("cid",cid)));
        if(through!=null){
            if(mapper.countMessage(args("cid",cid,"id",through))!=1)throw new BusinessException(400,"已读消息不属于当前会话");
            mapper.advanceReadCursor(args("cid",cid,"me",me,"id",through));
            mapper.recountUnread(args("cid",cid,"me",me));
        }
        Map<String, Object> row=required(mapper.unreadState(args("cid",cid,"me",me)));
        final long id=cid;afterCommit(()->{HashMap<String, Object> event=new HashMap<String,Object>(row);event.put("type","unread_update");event.put("conversationId",Long.toString(id));ChatWebSocketHandler.sendToUser(me,event);});return row;
    }
    public Map<String,Object> summary(long me){List<ConversationVO> normal=conversations(me,false);List<ConversationVO> pending=conversations(me,true);return Map.of("messageUnread",normal.stream().filter(c->!c.getIsMuted()).mapToInt(ConversationVO::getUnreadCount).sum(),"requestPending",pending.size(),"requestUnseen",pending.stream().filter(ConversationVO::getRequestUnseen).count());}
    public Map<String,Object> article(long aid){
        List<Map<String, Object>> list=mapper.publicArticle(args("id",aid));
        if(list.isEmpty())return Map.of("articleId",Long.toString(aid),"available",false);
        HashMap<String, Object> card=new HashMap<>(list.getFirst());card.put("available",true);return card;
    }
    public void enrichMessages(List<com.easyjob.vo.MessageVO> messages){
        HashSet<Long> aids=new HashSet<Long>();HashSet<String> replyIds=new HashSet<String>();
        for(MessageVO m:messages){if(Objects.equals(m.getMessageType(),3)&&Objects.equals(m.getStatus(),0)){try{aids.add(Long.parseLong(m.getContent()));}catch(NumberFormatException invalid){m.setArticle(Map.of("available",false));}}if(m.getReplyToMessageId()!=null)replyIds.add(m.getReplyToMessageId());}
        HashMap<String, Map<String, Object>> cards=new HashMap<String,Map<String,Object>>();
        if(!aids.isEmpty())for(Map<String, Object> row:mapper.publicArticles(args("ids",aids))){row.put("available",true);cards.put(s(row,"articleId"),row);}
        HashMap<String, Map<String, Object>> replies=new HashMap<String,Map<String,Object>>();
        if(!replyIds.isEmpty())for(Map<String, Object> row:mapper.quotedMessages(args("ids",replyIds)))replies.put(s(row,"id"),row);
        for(MessageVO m:messages){
            if(Objects.equals(m.getMessageType(),3)&&Objects.equals(m.getStatus(),0))m.setArticle(cards.getOrDefault(m.getContent(),Map.of("articleId",m.getContent(),"available",false)));
            Map<String, Object> r=replies.get(m.getReplyToMessageId());
            if(r!=null&&s(r,"cid").equals(m.getConversationId())){int status=(int)n(r,"status");m.setReplyToStatus(status);m.setReplyToSenderName(s(r,"nick_name"));String text=status!=0?"原消息已撤回":n(r,"message_type")==2?"[图片]":n(r,"message_type")==3?"[文章]":s(r,"content");m.setReplyToContent(text.codePointCount(0,text.length())>50?text.substring(0,text.offsetByCodePoints(0,50))+"…":text);}
        }
    }
}
