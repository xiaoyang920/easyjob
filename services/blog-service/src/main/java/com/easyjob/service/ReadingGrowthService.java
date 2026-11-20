package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import org.springframework.beans.factory.annotation.Autowired;
import com.easyjob.mapper.ReadingGrowthMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/** Server elapsed time, a single active session per user, and permanent earned levels. */
@Service
public class ReadingGrowthService {
    private final ReadingGrowthMapper store;
    private final Clock clock;
    @Autowired public ReadingGrowthService(ReadingGrowthMapper store) { this(store, Clock.systemUTC()); }
    ReadingGrowthService(ReadingGrowthMapper store, Clock clock) { this.store = store; this.clock = clock; }

    public List<Map<String,Object>> rules() {
        return store.findRules();
    }
    public static int levelFor(long seconds, int earned, List<Map<String,Object>> rules) {
        int level = earned;
        for (Map<String, Object> rule : rules) if (seconds >= ((Number)rule.get("minSeconds")).longValue())
            level = Math.max(level, ((Number)rule.get("level")).intValue());
        return level;
    }
    public Map<String,Object> summary(Long uid) {
        List<Map<String, Object>> rows = uid == null ? List.<Map<String,Object>>of() : store.findProgress(uid);
        long millis=rows.isEmpty()?0:((Number)rows.getFirst().get("total_millis")).longValue();
        int earned=rows.isEmpty()?0:((Number)rows.getFirst().get("earned_level")).intValue();
        long purchased=rows.isEmpty()?0:((Number)rows.getFirst().getOrDefault("purchased_millis",0L)).longValue();
        Map<String, Object> result=summary(millis+purchased,earned);
        result.put("naturalSeconds",millis/1000);result.put("purchasedSeconds",purchased/1000);
        int computed=((Number)result.get("level")).intValue();
        if(!rows.isEmpty() && computed>earned)
            store.promoteEarnedLevel(computed,uid,millis,earned);
        return result;
    }
    private Map<String,Object> summary(long millis, int earned) {
        List<Map<String, Object>> rules = rules(); long seconds = millis / 1000;
        int level = levelFor(seconds, earned, rules);
        LinkedHashMap<String, Object> result = new LinkedHashMap<String,Object>();
        result.put("totalSeconds", seconds); result.put("level", level); result.put("rules", rules);
        Optional<Map<String, Object>> next = rules.stream().filter(r -> ((Number)r.get("level")).intValue() > level).findFirst();
        result.put("nextLevel", next.map(r -> r.get("level")).orElse(null));
        result.put("secondsToNext", next.map(r -> Math.max(0, ((Number)r.get("minSeconds")).longValue()-seconds)).orElse(0L));
        return result;
    }
    private long purchased(Map<String,Object> progress){return ((Number)progress.getOrDefault("purchased_millis",0L)).longValue();}
    private Map<String,Object> summary(long millis,int earned,long purchased){Map<String, Object> result=summary(millis+purchased,earned);result.put("naturalSeconds",millis/1000);result.put("purchasedSeconds",purchased/1000);return result;}
    private Map<String,Object> lockProgress(Long uid) {
        if (uid == null) throw new BusinessException(401,"请登录后累计阅读等级");
        // Acquire the primary-key write lock directly. INSERT IGNORE on an existing
        // row takes shared locks that concurrent heartbeats could then deadlock upgrading.
        store.ensureProgress(uid);
        return store.lockProgress(uid);
    }
    private void assertReadable(Long aid, Long uid, int level) {
        List<Map<String, Object>> rows=store.findReadableArticle(aid);
        if(rows.isEmpty() || ((Number)rows.getFirst().get("status")).intValue()!=1 || ((Number)rows.getFirst().get("deleted")).intValue()!=0)
            throw new BusinessException(404,"文章不存在或不可访问");
        Map<String, Object> article=rows.getFirst();
        if (((Number)article.get("user_id")).longValue()==uid)
            throw new BusinessException(409,"阅读自己的文章不累计成长时间");
        // Administrative access does not generate growth from otherwise inaccessible content.
        if(level<((Number)article.get("required_level")).intValue())
            throw new BusinessException(403,"尚未达到文章阅读等级");
    }
    @Transactional public Map<String,Object> start(Long aid,Long uid, boolean active) {
        if(aid==null || aid<=0) throw new BusinessException(400,"文章ID无效");
        Map<String, Object> p=lockProgress(uid);
        long millis=((Number)p.get("total_millis")).longValue();
        int level=levelFor((millis+purchased(p))/1000,((Number)p.get("earned_level")).intValue(),rules());
        assertReadable(aid,uid,level);
        String sid=UUID.randomUUID().toString();
        Timestamp now=Timestamp.from(clock.instant());
        store.insertSession(sid,uid,aid,now,active);
        store.activateSession(sid,level,now,uid);
        Map<String, Object> result=summary(millis,level,purchased(p)); result.put("sessionId",sid); result.put("sequence",0L); return result;
    }
    public static long creditMillis(Instant previous,Instant now,boolean wasActive) {
        long elapsed=Duration.between(previous,now).toMillis();
        // A closed/disconnected tab cannot claim the entire unattended interval.
        return wasActive && elapsed>0 && elapsed<=45000 ? Math.min(elapsed,30000) : 0;
    }
    @Transactional public Map<String,Object> heartbeat(Long uid,String sid,long sequence,boolean active) {
        if(sid==null || !sid.matches("[a-f0-9-]{36}") || sequence<1) throw new BusinessException(400,"阅读心跳无效");
        Map<String, Object> p=lockProgress(uid);
        if(!sid.equals(p.get("active_session"))) throw new BusinessException(409,"阅读计时已转移到其他页面");
        List<Map<String, Object>> rows=store.findSession(sid,uid);
        if(rows.isEmpty()) throw new BusinessException(404,"阅读会话不存在");
        Map<String, Object> session=rows.getFirst(); long millis=((Number)p.get("total_millis")).longValue();
        int earned=((Number)p.get("earned_level")).intValue();
        if(sequence<=((Number)session.get("last_sequence")).longValue()) {
            Map<String, Object> result=summary(millis,earned,purchased(p)); result.put("creditedSeconds",0); return result;
        }
        int level=levelFor((millis+purchased(p))/1000,earned,rules());
        assertReadable(((Number)session.get("article_id")).longValue(),uid,level);
        Instant now=clock.instant();
        Object previousActive=session.get("active");
        long credit=creditMillis(((Timestamp)session.get("last_heartbeat")).toInstant(),now,
                previousActive instanceof Boolean b?b:((Number)previousActive).intValue()==1);
        // Attribute an interval to its ending Shanghai day; totals remain exact across midnight.
        LocalDate day=now.atZone(ZoneId.of("Asia/Shanghai")).toLocalDate();
        millis+=credit; earned=levelFor((millis+purchased(p))/1000,earned,rules());
        store.heartbeatSession(sequence,Timestamp.from(now),active,credit,sid);
        store.updateProgress(millis,earned,Timestamp.from(now),uid);
        if(credit>0) store.creditDay(uid,day,credit,credit);
        Map<String, Object> result=summary(millis,earned,purchased(p)); result.put("creditedSeconds",credit/1000); return result;
    }
}
