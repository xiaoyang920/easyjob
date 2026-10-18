package com.easyjob.agent.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.ai.embedding.EmbeddingResponse;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.time.Duration;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import com.alibaba.fastjson2.JSON;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * Embedding服务
 * 
 * 使用 Spring AI 智谱 Embedding
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ZhipuEmbeddingService {
    
    private final EmbeddingModel embeddingModel;
    @Autowired(required = false) private StringRedisTemplate cache;
    @Value("${spring.ai.zhipuai.embedding.options.model:embedding-3}") private String model = "embedding-3";
    @Value("${spring.ai.zhipuai.embedding.options.dimensions:2048}") private int dimensions = 2048;

    private String key(String text) {
        try {
            String hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));
            return "ej:embedding:v1:" + model + ":" + dimensions + ":" + hash;
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }

    private boolean valid(List<Double> vector) {
        return vector != null && vector.size() == dimensions && vector.stream().allMatch(v -> v != null && Double.isFinite(v));
    }
    
    /**
     * 获取文本的向量表示
     */
    public List<Double> embed(String text) {
        return embedBatch(List.of(text)).getFirst();
    }
    
    /**
     * 批量获取向量
     */
    public List<List<Double>> embedBatch(List<String> texts) {
        if (texts.isEmpty()) return List.of();
        Map<String, List<Double>> found = new LinkedHashMap<>();
        List<String> distinct = texts.stream().distinct().toList();
        if (cache != null) try {
            List<String> values = cache.opsForValue().multiGet(distinct.stream().map(this::key).toList());
            if (values != null) for (int i=0; i<distinct.size(); i++) {
                if (values.get(i) == null) continue;
                try {
                    var vector = JSON.parseArray(values.get(i), Double.class);
                    if (valid(vector)) found.put(distinct.get(i), List.copyOf(vector));
                } catch (RuntimeException ignored) { /* Corrupt cache entries are recomputed. */ }
            }
        } catch (RuntimeException exception) { log.warn("向量缓存读取失败，直接计算: {}", exception.getClass().getSimpleName()); }
        List<String> missing = distinct.stream().filter(text -> !found.containsKey(text)).toList();
        if (!missing.isEmpty()) {
            EmbeddingResponse response = embeddingModel.embedForResponse(missing);
            if (response.getResults().size() != missing.size()) throw new IllegalStateException("向量返回数量不一致");
            boolean[] seen = new boolean[missing.size()];
            for (var result : response.getResults()) {
                int index = result.getIndex();
                if (index < 0 || index >= missing.size() || seen[index]) throw new IllegalStateException("向量返回索引无效或重复");
                seen[index] = true;
                List<Double> vector = new ArrayList<>();
                for (float value : result.getOutput()) vector.add((double)value);
                if (!valid(vector)) throw new IllegalStateException("向量维度或数值无效");
                found.put(missing.get(index), List.copyOf(vector));
            }
            if (cache != null) try {
                for (String text : missing) cache.opsForValue().set(key(text), JSON.toJSONString(found.get(text)), Duration.ofDays(7));
            } catch (RuntimeException exception) { log.warn("向量缓存写入失败: {}", exception.getClass().getSimpleName()); }
        }
        return texts.stream().map(found::get).toList();
    }
}
