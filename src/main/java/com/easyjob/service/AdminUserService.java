package com.easyjob.service;

import com.alibaba.fastjson2.JSON;
import com.easyjob.component.RedisComponent;
import com.easyjob.config.ArticleWebSocketHandler;
import com.easyjob.config.ChatWebSocketHandler;
import com.easyjob.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import com.easyjob.mapper.AdminUserMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.util.*;

/** Explicit management fields; account credentials are never read or returned here. */
@Service @RequiredArgsConstructor @Slf4j
public class AdminUserService {
    private final AdminUserMapper store;
    private final AdminConsoleService admin;
    private final ReadingGrowthService growth;
    private final RedisComponent redis;
    private final ArticleWebSocketHandler articleSockets;
    private final ChatWebSocketHandler chatSockets;
    public record Profile(String nickName, String personIntroduction, Integer role, Integer status) {}
    public record Update(Profile expectedProfile, String nickName, String personIntroduction, Integer role,
                         Integer status, Long readingSeconds, String expectedReadingMillis, String reason) {}

    public Map<String,Object> detail(Long actor, Long id) {
        admin.requireAdmin(actor); validateId(id);
        var rows=store.findProfile(id);
        if(rows.isEmpty()) throw new BusinessException(404,"用户不存在");
        var result=new LinkedHashMap<>(rows.getFirst());
        var progress=store.findProgress(id);
        long millis=progress.isEmpty()?0:((Number)progress.getFirst().get("total_millis")).longValue();
        int earned=progress.isEmpty()?0:((Number)progress.getFirst().get("earned_level")).intValue();
        var rules=growth.rules();
        result.put("readingMillis",Long.toString(millis)); result.put("readingSeconds",millis/1000);
        result.put("readingLevel",ReadingGrowthService.levelFor(millis/1000,earned,rules)); result.put("rules",rules);
        return result;
    }

    @Transactional public void update(Long actor, Long id, Update body) {
        admin.requireAdmin(actor); validateId(id); validate(body);
        // Stable ordering also prevents crossed administrator edits from taking inverse locks.
        var locked=store.lockActorAndUser(actor,id);
        var operator=locked.stream().filter(r->actor.toString().equals(r.get("userId"))).findFirst().orElse(null);
        if(operator==null || number(operator,"role")!=2 || number(operator,"status")!=1)
            throw new BusinessException(403,"管理员权限已变化，请重新登录");
        var current=locked.stream().filter(r->id.toString().equals(r.get("userId"))).findFirst()
                .orElseThrow(()->new BusinessException(404,"用户不存在"));
        Profile before=profile(current);
        if(!before.equals(body.expectedProfile())) throw new BusinessException(409,"用户资料已变化，请重新加载后再修改");
        if(actor.equals(id) && (body.role()!=2 || body.status()!=1))
            throw new BusinessException(409,"不能取消自己的管理员身份或禁用自己的账号");
        Profile after=new Profile(body.nickName().strip(),body.personIntroduction(),body.role(),body.status());
        boolean authChanged=!before.role().equals(after.role()) || !before.status().equals(after.status());
        var oldValues=new LinkedHashMap<String,Object>(); oldValues.put("profile",before);
        var newValues=new LinkedHashMap<String,Object>(); newValues.put("profile",after);
        boolean readingChanged=false;
        if(body.readingSeconds()!=null) {
            store.ensureProgress(id);
            var progress=store.lockProgress(id);
            long millis=((Number)progress.get("total_millis")).longValue();
            if(!Long.toString(millis).equals(body.expectedReadingMillis()))
                throw new BusinessException(409,"阅读时长已变化，请重新加载后再校正");
            int oldLevel=((Number)progress.get("earned_level")).intValue();
            int newLevel=ReadingGrowthService.levelFor(body.readingSeconds(),0,growth.rules());
            readingChanged=millis!=body.readingSeconds()*1000 || oldLevel!=newLevel;
            oldValues.put("readingMillis",Long.toString(millis)); oldValues.put("readingLevel",oldLevel);
            newValues.put("readingMillis",Long.toString(body.readingSeconds()*1000)); newValues.put("readingLevel",newLevel);
            if(readingChanged) store.correctProgress(body.readingSeconds()*1000,newLevel,id);
        }
        if(before.equals(after) && !readingChanged) return;
        if(!before.equals(after)) store.updateProfile(after.nickName(),after.personIntroduction(),after.role(),after.status(),authChanged?1:0,id);
        String oldLabel=label(before),newLabel=label(after);
        if(readingChanged) {oldLabel+=" · 校正前 "+oldValues.get("readingMillis")+"ms";newLabel+=" · 校正后 "+newValues.get("readingMillis")+"ms";}
        store.insertAudit(actor,id,shorten(oldLabel),shorten(newLabel),body.reason().strip(),JSON.toJSONString(Map.of("before",oldValues,"after",newValues)));
        boolean nameChanged=!Objects.equals(before.nickName(),after.nickName());
        var articles=nameChanged?store.findArticleIds(id):List.<Long>of();
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() {
                // The SQL change and auth version are committed even if cache invalidation is unavailable.
                try {redis.deleteUserSpaceVO(id);for(Long aid:articles) redis.deleteArticleDetail(aid);}
                catch(RuntimeException e){log.error("User {} cache invalidation failed after admin edit",id,e);}
                if(authChanged){articleSockets.disconnectUser(id);chatSockets.disconnectUser(id);}
            }
        });
    }
    private static Profile profile(Map<String,Object> r){return new Profile((String)r.get("nickName"),(String)r.get("personIntroduction"),number(r,"role"),number(r,"status"));}
    private static int number(Map<String,Object> r,String key){return ((Number)r.get(key)).intValue();}
    private static String label(Profile p){return p.nickName()+" · "+(switch(p.role()){case 2->"管理员";case 3->"审核员";case 4->"运营员";default->"普通用户";})+" · "+(p.status()==1?"正常":"禁用");}
    private static String shorten(String s){return s.length()>128?s.substring(0,128):s;}
    private static void validateId(Long id){if(id==null || id<=0)throw new BusinessException(400,"用户ID无效");}
    private static void validate(Update b){
        if(b==null || b.expectedProfile()==null || b.nickName()==null || b.nickName().strip().isEmpty() || b.nickName().strip().length()>20
                || b.personIntroduction()!=null && b.personIntroduction().length()>200)
            throw new BusinessException(400,"昵称需为1至20字，简介不能超过200字");
        if(b.role()==null || !Set.of(1,2,3,4).contains(b.role()) || b.status()==null || b.status()!=0 && b.status()!=1)
            throw new BusinessException(400,"角色或账号状态无效");
        if(b.reason()==null || b.reason().strip().isEmpty() || b.reason().strip().length()>300)
            throw new BusinessException(400,"请填写1至300字的修改原因");
        if(b.readingSeconds()!=null && (b.readingSeconds()<0 || b.readingSeconds()>315360000L || b.expectedReadingMillis()==null || !b.expectedReadingMillis().matches("[0-9]{1,18}")))
            throw new BusinessException(400,"阅读时长校正参数无效");
    }
}
