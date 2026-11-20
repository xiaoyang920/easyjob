package com.easyjob.growth;

import java.util.Map;

/** Numeric/time conversion for database result maps. */
public final class GrowthValues {
    private GrowthValues() {}
    public static long number(Map<String,Object> row,String key){return ((Number)row.getOrDefault(key,0)).longValue();}
    // DATETIME via Connector/J getObject is LocalDateTime; the project's JDBC serverTimezone is Asia/Shanghai.
    public static java.time.Instant instant(Object value){
        if(value instanceof java.sql.Timestamp timestamp)return timestamp.toInstant();
        return ((java.time.LocalDateTime)value).atZone(java.time.ZoneId.of("Asia/Shanghai")).toInstant();
    }
}
