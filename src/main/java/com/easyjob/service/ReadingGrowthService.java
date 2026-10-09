package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;

/** Server elapsed time, a single active session per user, and permanent earned levels. */
@Service
public class ReadingGrowthService {
    private final JdbcTemplate jdbc;
    private final Clock clock;
    @Autowired public ReadingGrowthService(JdbcTemplate jdbc) { this(jdbc, Clock.systemUTC()); }
    ReadingGrowthService(JdbcTemplate jdbc, Clock clock) { this.jdbc = jdbc; this.clock = clock; }

    public List<Map<String,Object>> rules() {
        return jdbc.queryForList("SELECT level,min_seconds AS minSeconds FROM reading_level_rule ORDER BY level");
    }
    public static int levelFor(long seconds, int earned, List<Map<String,Object>> rules) {
        int level = earned;
        for (var rule : rules) if (seconds >= ((Number)rule.get("minSeconds")).longValue())
            level = Math.max(level, ((Number)rule.get("level")).intValue());
        return level;
    }
    public Map<String,Object> summary(Long uid) {
        var rows = uid == null ? List.<Map<String,Object>>of() : jdbc.queryForList(
                "SELECT total_millis,earned_level FROM user_reading_progress WHERE user_id=?", uid);
        long millis=rows.isEmpty()?0:((Number)rows.getFirst().get("total_millis")).longValue();
        int earned=rows.isEmpty()?0:((Number)rows.getFirst().get("earned_level")).intValue();
        var result=summary(millis,earned);
        int computed=((Number)result.get("level")).intValue();
        if(!rows.isEmpty() && computed>earned)
            jdbc.update("UPDATE user_reading_progress SET earned_level=GREATEST(earned_level,?) WHERE user_id=? AND total_millis=? AND earned_level=?",computed,uid,millis,earned);
        return result;
    }
    private Map<String,Object> summary(long millis, int earned) {
        var rules = rules(); long seconds = millis / 1000;
        int level = levelFor(seconds, earned, rules);
        var result = new LinkedHashMap<String,Object>();
        result.put("totalSeconds", seconds); result.put("level", level); result.put("rules", rules);
        var next = rules.stream().filter(r -> ((Number)r.get("level")).intValue() > level).findFirst();
        result.put("nextLevel", next.map(r -> r.get("level")).orElse(null));
        result.put("secondsToNext", next.map(r -> Math.max(0, ((Number)r.get("minSeconds")).longValue()-seconds)).orElse(0L));
        return result;
    }
    private Map<String,Object> lockProgress(Long uid) {
        if (uid == null) throw new BusinessException(401,"请登录后累计阅读等级");
        // Acquire the primary-key write lock directly. INSERT IGNORE on an existing
        // row takes shared locks that concurrent heartbeats could then deadlock upgrading.
        jdbc.update("INSERT INTO user_reading_progress(user_id) VALUES (?) ON DUPLICATE KEY UPDATE user_id=user_id",uid);
        return jdbc.queryForMap("SELECT * FROM user_reading_progress WHERE user_id=? FOR UPDATE",uid);
    }
    private void assertReadable(Long aid, Long uid, int level) {
        var rows=jdbc.queryForList("SELECT user_id,status,deleted,required_level FROM article_info WHERE article_id=?",aid);
        if(rows.isEmpty() || ((Number)rows.getFirst().get("status")).intValue()!=1 || ((Number)rows.getFirst().get("deleted")).intValue()!=0)
            throw new BusinessException(404,"文章不存在或不可访问");
        var article=rows.getFirst();
        if (((Number)article.get("user_id")).longValue()==uid)
            throw new BusinessException(409,"阅读自己的文章不累计成长时间");
        // Administrative access does not generate growth from otherwise inaccessible content.
        if(level<((Number)article.get("required_level")).intValue())
            throw new BusinessException(403,"尚未达到文章阅读等级");
    }
    @Transactional public Map<String,Object> start(Long aid,Long uid, boolean active) {
        if(aid==null || aid<=0) throw new BusinessException(400,"文章ID无效");
        var p=lockProgress(uid);
        long millis=((Number)p.get("total_millis")).longValue();
        int level=levelFor(millis/1000,((Number)p.get("earned_level")).intValue(),rules());
        assertReadable(aid,uid,level);
        String sid=UUID.randomUUID().toString();
        var now=Timestamp.from(clock.instant());
        jdbc.update("INSERT INTO reading_session(session_id,user_id,article_id,last_heartbeat,active) VALUES (?,?,?,?,?)",sid,uid,aid,now,active);
        jdbc.update("UPDATE user_reading_progress SET active_session=?,earned_level=?,updated_at=? WHERE user_id=?",sid,level,now,uid);
        var result=summary(millis,level); result.put("sessionId",sid); result.put("sequence",0L); return result;
    }
    public static long creditMillis(Instant previous,Instant now,boolean wasActive) {
        long elapsed=Duration.between(previous,now).toMillis();
        // A closed/disconnected tab cannot claim the entire unattended interval.
        return wasActive && elapsed>0 && elapsed<=45000 ? Math.min(elapsed,30000) : 0;
    }
    @Transactional public Map<String,Object> heartbeat(Long uid,String sid,long sequence,boolean active) {
        if(sid==null || !sid.matches("[a-f0-9-]{36}") || sequence<1) throw new BusinessException(400,"阅读心跳无效");
        var p=lockProgress(uid);
        if(!sid.equals(p.get("active_session"))) throw new BusinessException(409,"阅读计时已转移到其他页面");
        var rows=jdbc.query("SELECT article_id,last_sequence,last_heartbeat,active FROM reading_session WHERE session_id=? AND user_id=?",(rs,n)->{
            var row=new HashMap<String,Object>(); row.put("article_id",rs.getLong("article_id"));
            row.put("last_sequence",rs.getLong("last_sequence")); row.put("last_heartbeat",rs.getTimestamp("last_heartbeat"));
            row.put("active",rs.getBoolean("active")); return row;
        },sid,uid);
        if(rows.isEmpty()) throw new BusinessException(404,"阅读会话不存在");
        var session=rows.getFirst(); long millis=((Number)p.get("total_millis")).longValue();
        int earned=((Number)p.get("earned_level")).intValue();
        if(sequence<=((Number)session.get("last_sequence")).longValue()) {
            var result=summary(millis,earned); result.put("creditedSeconds",0); return result;
        }
        int level=levelFor(millis/1000,earned,rules());
        assertReadable(((Number)session.get("article_id")).longValue(),uid,level);
        Instant now=clock.instant();
        Object previousActive=session.get("active");
        long credit=creditMillis(((Timestamp)session.get("last_heartbeat")).toInstant(),now,
                previousActive instanceof Boolean b?b:((Number)previousActive).intValue()==1);
        // Attribute an interval to its ending Shanghai day; totals remain exact across midnight.
        var day=now.atZone(ZoneId.of("Asia/Shanghai")).toLocalDate();
        millis+=credit; earned=levelFor(millis/1000,earned,rules());
        jdbc.update("UPDATE reading_session SET last_sequence=?,last_heartbeat=?,active=?,credited_millis=credited_millis+? WHERE session_id=?",sequence,Timestamp.from(now),active,credit,sid);
        jdbc.update("UPDATE user_reading_progress SET total_millis=?,earned_level=?,updated_at=? WHERE user_id=?",millis,earned,Timestamp.from(now),uid);
        if(credit>0) jdbc.update("INSERT INTO user_reading_daily(user_id,read_day,total_millis) VALUES (?,?,?) ON DUPLICATE KEY UPDATE total_millis=total_millis+?",uid,day,credit,credit);
        var result=summary(millis,earned); result.put("creditedSeconds",credit/1000); return result;
    }
}
