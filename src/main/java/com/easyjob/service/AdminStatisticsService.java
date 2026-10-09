package com.easyjob.service;

import com.alibaba.excel.EasyExcel;
import com.easyjob.exception.BusinessException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import java.io.ByteArrayOutputStream;
import java.sql.Timestamp;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;

/** Aggregates only: no user contacts, article body, or invented historical view counts. */
@Service
public class AdminStatisticsService {
    private final JdbcTemplate jdbc;
    private final AdminConsoleService admin;
    private final Clock clock;
    @Autowired public AdminStatisticsService(JdbcTemplate jdbc,AdminConsoleService admin){this(jdbc,admin,Clock.system(ZoneId.of("Asia/Shanghai")));}
    AdminStatisticsService(JdbcTemplate jdbc,AdminConsoleService admin,Clock clock){this.jdbc=jdbc;this.admin=admin;this.clock=clock;}
    public record Daily(String date,long newUsers,long newArticles,long readingMillis,long readingUsers) {
        public double readingSeconds(){return readingMillis/1000.0;}
    }
    public record Distribution(String name,long count) {}
    public record Report(int days,String from,String to,String generatedAt,List<Daily> daily,
                         List<Distribution> articles,List<Distribution> levels,long periodNewUsers,
                         long periodNewArticles,double periodReadingSeconds,long periodReadingUsers,String source) {}

    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Report statistics(Long actor,int days) {
        return statistics(actor,days,"business");
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Report statistics(Long actor,int days,String source) {
        admin.requirePermission(actor,"statistics.read");
        if(source==null || !List.of("business","evaluation","all").contains(source))throw new BusinessException(400,"数据来源无效");
        String filter=source.equals("all")?"":" AND data_source='"+source+"'";
        String userFilter=source.equals("all")?"":" AND u.data_source='"+source+"'";
        if(days!=7 && days!=30 && days!=90)throw new BusinessException(400,"统计范围仅支持7、30或90天");
        LocalDate to=LocalDate.now(clock),from=to.minusDays(days-1);
        Timestamp start=Timestamp.valueOf(from.atStartOfDay()),end=Timestamp.valueOf(to.plusDays(1).atStartOfDay());
        var users=index(jdbc.queryForList("SELECT CAST(DATE(join_time) AS CHAR) AS day,COUNT(*) AS amount FROM user_info WHERE join_time>=? AND join_time<?"+filter+" GROUP BY day",start,end));
        var publications=index(jdbc.queryForList("SELECT CAST(DATE(publish_time) AS CHAR) AS day,COUNT(*) AS amount FROM article_info WHERE deleted=0 AND status IN (1,2) AND publish_time>=? AND publish_time<?"+filter+" GROUP BY day",start,end));
        var reading=index(jdbc.queryForList("SELECT CAST(d.read_day AS CHAR) AS day,SUM(d.total_millis) AS millis,COUNT(*) AS readers FROM user_reading_daily d JOIN user_info u ON u.user_id=d.user_id WHERE d.read_day>=? AND d.read_day<? AND d.total_millis>0"+userFilter+" GROUP BY d.read_day",java.sql.Date.valueOf(from),java.sql.Date.valueOf(to.plusDays(1))));
        var daily=new ArrayList<Daily>(days);
        long newUsers=0,newArticles=0,millis=0;
        for(LocalDate date=from;!date.isAfter(to);date=date.plusDays(1)) {
            String day=date.toString();long u=value(users.get(day),"amount"),a=value(publications.get(day),"amount"),m=value(reading.get(day),"millis");
            daily.add(new Daily(day,u,a,m,value(reading.get(day),"readers")));newUsers+=u;newArticles+=a;millis+=m;
        }
        Long distinct=jdbc.queryForObject("SELECT COUNT(DISTINCT d.user_id) FROM user_reading_daily d JOIN user_info u ON u.user_id=d.user_id WHERE d.read_day>=? AND d.read_day<? AND d.total_millis>0"+userFilter,Long.class,java.sql.Date.valueOf(from),java.sql.Date.valueOf(to.plusDays(1)));
        var articleCounts=jdbc.queryForList("SELECT status,COUNT(*) AS amount FROM article_info WHERE deleted=0"+filter+" GROUP BY status");
        var articles=new ArrayList<Distribution>();
        for(int state=0;state<=2;state++) {
            final int current=state;
            long count=articleCounts.stream().filter(r->value(r,"status")==current).mapToLong(r->value(r,"amount")).sum();
            articles.add(new Distribution(switch(state){case 0->"未公开";case 1->"已发布";default->"已下架";},count));
        }
        var levelRows=jdbc.queryForList("SELECT GREATEST(COALESCE(p.earned_level,0),COALESCE((SELECT MAX(level) FROM reading_level_rule WHERE min_seconds<=COALESCE(p.total_millis,0) DIV 1000),0)) AS level,COUNT(*) AS amount FROM user_info u LEFT JOIN user_reading_progress p ON p.user_id=u.user_id WHERE 1=1"+userFilter+" GROUP BY level");
        var configured=jdbc.queryForList("SELECT level FROM reading_level_rule ORDER BY level");
        var levelCounts=new TreeMap<Long,Long>();for(var row:configured)levelCounts.put(value(row,"level"),0L);
        for(var row:levelRows)levelCounts.put(value(row,"level"),value(row,"amount"));
        var levels=levelCounts.entrySet().stream().map(e->new Distribution("L"+e.getKey(),e.getValue())).toList();
        return new Report(days,from.toString(),to.toString(),ZonedDateTime.now(clock).toOffsetDateTime().toString(),List.copyOf(daily),List.copyOf(articles),levels,newUsers,newArticles,millis/1000.0,distinct==null?0:distinct,source);
    }
    private static Map<String,Map<String,Object>> index(List<Map<String,Object>> rows){var map=new HashMap<String,Map<String,Object>>();for(var row:rows)map.put(row.get("day").toString(),row);return map;}
    private static long value(Map<String,Object> row,String name){return row==null || row.get(name)==null?0:((Number)row.get(name)).longValue();}

    /** Bounded report (<100 daily rows), completed before setting the download headers. */
    public byte[] workbook(Report report) {
        var output=new ByteArrayOutputStream();
        try(var writer=EasyExcel.write(output).autoCloseStream(false).build()) {
            var summary=List.<List<Object>>of(
                List.of("起始日期",report.from(),"趋势含起始日与结束日"),List.of("结束日期",report.to(),"Asia/Shanghai"),
                List.of("生成时间",OffsetDateTime.parse(report.generatedAt()).atZoneSameInstant(ZoneId.of("Asia/Shanghai")).format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")),"北京时间；文章和等级分布为生成时的当前快照"),
                List.of("数据范围",sourceLabel(report.source()),"按独立数据来源字段筛选；与账号是否禁用无关"),
                List.of("新增用户",report.periodNewUsers(),"所选来源内，区间内注册的账号，含禁用账号"),
                List.of("首次发布文章",report.periodNewArticles(),"按首次发布时间统计；含目前下架的文章，不含已删除文章"),
                List.of("有效阅读秒数",report.periodReadingSeconds(),"历史每日计时之和；不受管理员成长时长校正影响"),
                List.of("有效阅读用户数",report.periodReadingUsers(),"区间内有有效阅读时长的去重用户，不是每日人数之和"),
                List.of("文章状态分布","当前快照","未公开、已发布、已下架互斥；排除删除文章"),
                List.of("阅读等级分布","当前快照","已获等级与现行时长门槛的较高者，含禁用账号"));
            writer.write(summary,sheet(0,"统计说明",List.of("指标","值","口径")));
            var daily=report.daily().stream().map(r->List.<Object>of(r.date(),r.newUsers(),r.newArticles(),r.readingSeconds(),r.readingUsers())).toList();
            writer.write(daily,sheet(1,"每日趋势",List.of("日期","新增用户","首次发布文章","有效阅读秒数","有效阅读用户数")));
            writer.write(report.articles().stream().map(r->List.<Object>of(r.name(),r.count())).toList(),sheet(2,"文章状态",List.of("状态","文章数")));
            writer.write(report.levels().stream().map(r->List.<Object>of(r.name(),r.count())).toList(),sheet(3,"阅读等级",List.of("等级","用户数")));
        }
        return output.toByteArray();
    }
    private static com.alibaba.excel.write.metadata.WriteSheet sheet(int id,String name,List<String> headers) {
        return EasyExcel.writerSheet(id,name).head(headers.stream().map(List::of).toList())
                .registerWriteHandler(new com.alibaba.excel.write.style.column.LongestMatchColumnWidthStyleStrategy()).build();
    }
    public static String sourceLabel(String source){return switch(source){case "business"->"真实业务";case "evaluation"->"评测样例";default->"全部数据";};}
}
