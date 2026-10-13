package com.easyjob.agent.rpc;

import com.easyjob.rpc.v1.Value;
import java.util.*;

/** Binary values preserve 64-bit IDs; google.protobuf.Struct represents numbers as doubles. */
public final class RpcValues {
    private RpcValues() {}
    public static Value encode(Object value) { return encode(value, 0); }
    private static Value encode(Object value, int depth) {
        if (depth > 32) throw new IllegalArgumentException("RPC nesting exceeds limit");
        var b = Value.newBuilder();
        if (value == null) return b.setNullValue(true).build();
        if (value instanceof Boolean v) return b.setBoolean(v).build();
        if (value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long)
            return b.setInteger(((Number) value).longValue()).build();
        if (value instanceof Number v) {
            if (!Double.isFinite(v.doubleValue())) throw new IllegalArgumentException("Invalid RPC number");
            return b.setDecimal(v.doubleValue()).build();
        }
        if (value instanceof String v) return b.setText(v).build();
        if (value instanceof java.sql.Timestamp v) return b.setText(v.toLocalDateTime().toString()).build();
        if (value instanceof java.time.temporal.TemporalAccessor || value instanceof java.util.Date)
            return b.setText(value.toString()).build();
        if (value instanceof Map<?, ?> map) {
            var object = com.easyjob.rpc.v1.Object.newBuilder();
            map.forEach((key, item) -> object.putFields(key.toString(), encode(item, depth + 1)));
            return b.setObject(object).build();
        }
        if (value instanceof Collection<?> items) {
            var array = com.easyjob.rpc.v1.Array.newBuilder();
            items.forEach(item -> array.addItems(encode(item, depth + 1)));
            return b.setArray(array).build();
        }
        throw new IllegalArgumentException("Unsupported RPC value type");
    }
    public static Object decode(Value value) { return decode(value, 0); }
    private static Object decode(Value value, int depth) {
        if (depth > 32) throw new IllegalArgumentException("RPC nesting exceeds limit");
        return switch (value.getKindCase()) {
            case TEXT -> value.getText();
            case INTEGER -> value.getInteger();
            case DECIMAL -> value.getDecimal();
            case BOOLEAN -> value.getBoolean();
            case NULL_VALUE, KIND_NOT_SET -> null;
            case OBJECT -> {
                Map<String, Object> map = new LinkedHashMap<>();
                value.getObject().getFieldsMap().forEach((key, item) -> map.put(key, decode(item, depth + 1)));
                yield map;
            }
            case ARRAY -> value.getArray().getItemsList().stream().map(item -> decode(item, depth + 1)).toList();
        };
    }
}
