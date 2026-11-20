package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import com.easyjob.mapper.AdminAgentMetricsMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import java.time.*;
import java.util.*;
import com.fasterxml.jackson.databind.JsonNode;
import java.sql.Timestamp;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Usage metadata only. Provider-measured tokens are never substituted with budget reservations. */
@Service @RequiredArgsConstructor
public class AdminAgentMetricsService {
    private final AdminAgentMetricsMapper store;
    private final AdminConsoleService admin;
    private final ObjectMapper json;
    static long percentile(List<Long> values,double fraction){if(values.isEmpty())return 0;ArrayList<Long> sorted=new ArrayList<>(values);Collections.sort(sorted);return sorted.get(Math.max(0,(int)Math.ceil(fraction*sorted.size())-1));}
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> report(Long actor,int days,String source){
        admin.requirePermission(actor,"metrics.read");
        if(!List.of(7,30,90).contains(days) || source==null || !Set.of("business","evaluation","all").contains(source))throw new BusinessException(400,"指标筛选无效");
        LocalDate to=LocalDate.now(ZoneId.of("Asia/Shanghai"));LocalDate from=to.minusDays(days-1);
        Timestamp start=java.sql.Timestamp.valueOf(from.atStartOfDay());
        Timestamp end=java.sql.Timestamp.valueOf(to.plusDays(1).atStartOfDay());
        List<Map<String, Object>> states=store.countStates(start,end,source);
        List<Map<String, Object>> rows=store.findMetrics(start,end,source);
        long total=states.stream().mapToLong(r->((Number)r.get("count")).longValue()).sum(),finished=0,succeeded=0,incomplete=0;
        for(Map<String, Object> state:states){long count=((Number)state.get("count")).longValue();if("succeeded".equals(state.get("status"))){succeeded+=count;incomplete+=Math.min(count,Math.max(0,((Number)state.getOrDefault("incomplete",0L)).longValue()));}if(Set.of("succeeded","failed","cancelled","expired").contains(state.get("status")))finished+=count;}
        long executionSucceeded=succeeded;
        succeeded-=incomplete;
        long calls=0,errors=0,input=0,output=0,withMetrics=0,complete=0;ArrayList<Long> durations=new ArrayList<Long>();
        for(Map<String, Object> row:rows){try{JsonNode m=json.readTree(String.valueOf(row.get("metrics")));if(m==null || !m.isObject())continue;withMetrics++;calls+=Math.max(0,m.path("llm_calls").asLong());errors+=Math.max(0,m.path("failed_llm_calls").asLong());input+=Math.max(0,m.path("measured_input_tokens").asLong());output+=Math.max(0,m.path("measured_output_tokens").asLong());if(m.path("token_usage_complete").asBoolean())complete++;long duration=m.path("active_duration_ms").asLong();if(duration>0 && Set.of("succeeded","failed","cancelled","expired").contains(row.get("status")))durations.add(duration);}catch(Exception ignored){/* Legacy rows have no usable metrics. */}}
        ArrayList<Long> firstAnswers=new ArrayList<Long>();
        for(Map<String, Object> row:rows){try{JsonNode d=json.readTree(String.valueOf(row.get("delivery")));if(d!=null && d.path("first_answer_ms").isIntegralNumber()){long ms=d.path("first_answer_ms").asLong();if(ms>=0 && ms<=3600000)firstAnswers.add(ms);}}catch(Exception ignored){/* Missing browser samples remain unknown. */}}
        List<Map<String, Object>> stages=store.findStages(start,end,source);
        List<Map<String, Object>> dailyRows=store.countDaily(start,end,source);
        ArrayList<Map<String, Object>> daily=new ArrayList<Map<String,Object>>();for(LocalDate day=from;!day.isAfter(to);day=day.plusDays(1)){String key=day.toString();Map<String, Object> row=dailyRows.stream().filter(r->key.equals(r.get("day"))).findFirst().orElse(Map.of("count",0L,"failed",0L));daily.add(Map.of("date",key,"count",row.get("count"),"failed",row.get("failed")));}
        LinkedHashMap<String, Object> result=new LinkedHashMap<String,Object>();result.put("from",from.toString());result.put("to",to.toString());result.put("source",source);result.put("totalRuns",total);result.put("finishedRuns",finished);result.put("succeededRuns",succeeded);result.put("executionSucceededRuns",executionSucceeded);result.put("incompleteRuns",incomplete);result.put("successRate",finished==0?null:succeeded*100.0/finished);result.put("sampledRuns",rows.size());result.put("sampleLimit",10000);result.put("runsWithMetrics",withMetrics);result.put("completeUsageRuns",complete);result.put("llmCalls",calls);result.put("failedLlmCalls",errors);result.put("measuredInputTokens",input);result.put("measuredOutputTokens",output);result.put("latencySamples",durations.size());result.put("activeP50Ms",durations.isEmpty()?null:percentile(durations,.5));result.put("activeP95Ms",durations.isEmpty()?null:percentile(durations,.95));result.put("states",states);result.put("daily",daily);result.put("scope","时长与Token统计使用周期内最近10000次运行；活跃时长排除审批等待，Token为供应商实测部分，不含embedding、rerank及后台记忆处理；不是费用估算。交付完成率以已结束运行为分母，排除明确未完成的交付，失败、取消与过期计入未成功；不代表回答准确率或人工任务完成率。");result.put("firstAnswerSamples",firstAnswers.size());result.put("firstAnswerP50Ms",firstAnswers.isEmpty()?null:percentile(firstAnswers,.5));result.put("firstAnswerP95Ms",firstAnswers.isEmpty()?null:percentile(firstAnswers,.95));result.put("stages",stages);return result;
    }
}
