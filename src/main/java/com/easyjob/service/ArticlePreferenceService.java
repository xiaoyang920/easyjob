package com.easyjob.service;

import com.alibaba.fastjson2.JSON;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import java.util.*;

/** Explicit blog topics are read fresh, so profile removal takes effect immediately. */
@Service
public class ArticlePreferenceService {
    private final JdbcTemplate jdbc;
    public ArticlePreferenceService(JdbcTemplate jdbc) { this.jdbc = jdbc; }
    public List<String> topics(Long uid) {
        if (uid == null) return List.of();
        var rows = jdbc.queryForList("SELECT interests,tech_stack FROM user_profile WHERE user_id=?", uid);
        if (rows.isEmpty()) return List.of();
        var result = new LinkedHashMap<String,String>();
        for (String field : List.of("interests", "tech_stack")) {
            Object raw = rows.getFirst().get(field);
            if (raw == null) continue;
            for (String value : JSON.parseArray(raw.toString(), String.class)) {
                if (value == null || value.isBlank() || value.length() > 100) continue;
                String topic = value.trim();
                result.putIfAbsent(topic.toLowerCase(Locale.ROOT), topic);
            }
        }
        return result.values().stream().limit(40).toList();
    }
    public static String titlePattern(String topic) {
        StringBuilder escaped=new StringBuilder();
        for(char c:topic.toCharArray()) {
            if("\\.[]{}()*+-?^$|".indexOf(c)>=0) escaped.append('\\');
            escaped.append(c);
        }
        // Java should match “Java入门”, but not “JavaScript”. Chinese topics
        // retain literal phrase matching. Regex metacharacters are always escaped.
        boolean first=topic.charAt(0)<128 && Character.isLetterOrDigit(topic.charAt(0));
        char last=topic.charAt(topic.length()-1);
        boolean end=last<128 && Character.isLetterOrDigit(last);
        return (first?"(^|[^a-zA-Z0-9_])":"")+escaped+(end?"([^a-zA-Z0-9_]|$)":"");
    }
}
