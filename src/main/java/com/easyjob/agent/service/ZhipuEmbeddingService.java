package com.easyjob.agent.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.ai.embedding.EmbeddingResponse;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

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
    
    /**
     * 获取文本的向量表示
     */
    public List<Double> embed(String text) {
        EmbeddingResponse response = embeddingModel.embedForResponse(List.of(text));
        float[] embedding = response.getResult().getOutput();
        
        // float[] 转 List<Double>
        List<Double> vector = new ArrayList<>(embedding.length);
        for (float f : embedding) {
            vector.add((double) f);
        }
        return vector;
    }
    
    /**
     * 批量获取向量
     */
    public List<List<Double>> embedBatch(List<String> texts) {
        EmbeddingResponse response = embeddingModel.embedForResponse(texts);
        
        return response.getResults().stream()
                .map(result -> {
                    float[] embedding = result.getOutput();
                    List<Double> vector = new ArrayList<>(embedding.length);
                    for (float f : embedding) {
                        vector.add((double) f);
                    }
                    return vector;
                })
                .toList();
    }
}
