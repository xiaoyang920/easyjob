package com.easyjob.agent;

import com.easyjob.agent.service.ZhipuEmbeddingService;
import org.springframework.ai.embedding.Embedding;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.ai.embedding.EmbeddingResponse;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import java.time.Duration;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@SuppressWarnings("unchecked")
class EmbeddingCacheTests {
    EmbeddingModel model;
    ZhipuEmbeddingService service;
    ValueOperations<String,String> values;
    Map<String,String> stored;
    @BeforeEach void setup() {
        model=mock(EmbeddingModel.class); service=new ZhipuEmbeddingService(model);
        var redis=mock(StringRedisTemplate.class); values=mock(ValueOperations.class); stored=new HashMap<>();
        ReflectionTestUtils.setField(service,"cache",redis); ReflectionTestUtils.setField(service,"dimensions",2);
        when(redis.opsForValue()).thenReturn(values);
        when(values.multiGet(anyCollection())).thenAnswer(call -> ((Collection<String>)call.getArgument(0)).stream().map(stored::get).toList());
        doAnswer(call -> { stored.put(call.getArgument(0),call.getArgument(1)); return null; }).when(values).set(anyString(),anyString(),any(Duration.class));
        when(model.embedForResponse(anyList())).thenAnswer(call -> {
            List<String> texts=call.getArgument(0);
            var response=mock(EmbeddingResponse.class);
            List<Embedding> results=texts.stream().map(text -> {
                var result=mock(Embedding.class); when(result.getOutput()).thenReturn(new float[]{.1f,.2f}); return result;
            }).toList();
            when(response.getResults()).thenReturn(results); return response;
        });
    }
    @Test void repeatedBatchDoesNotCallModelAgain() {
        var first=service.embedBatch(List.of("title\nbody","second"));
        assertEquals(first,service.embedBatch(List.of("title\nbody","second")));
        verify(model,times(1)).embedForResponse(anyList());
    }
    @Test void sameTextWithinBatchKeepsOrderAndEmbedsOnce() {
        var vectors=service.embedBatch(List.of("same","same","other"));
        assertEquals(3,vectors.size()); verify(model).embedForResponse(List.of("same","other"));
    }
    @Test void modelVersionAndTextChangesInvalidateCache() {
        service.embed("text"); ReflectionTestUtils.setField(service,"model","new-model"); service.embed("text"); service.embed("changed");
        verify(model,times(3)).embedForResponse(anyList());
    }
    @Test void corruptVectorIsRecomputed() {
        service.embed("text"); stored.replaceAll((key,value)->"[0.1]"); service.embed("text");
        verify(model,times(2)).embedForResponse(anyList());
    }
    @Test void cacheOutageDoesNotFailEmbedding() {
        when(values.multiGet(anyCollection())).thenThrow(new IllegalStateException("offline"));
        assertEquals(2,service.embed("text").size()); verify(model).embedForResponse(List.of("text"));
    }
}
