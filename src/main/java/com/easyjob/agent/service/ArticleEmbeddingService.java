package com.easyjob.agent.service;

import com.easyjob.agent.config.EmbeddingExecutionProperties;
import com.easyjob.agent.component.DocumentChunkService;
import com.easyjob.exception.BusinessException;
import com.easyjob.observability.RequestTrace;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.stereotype.Service;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.FutureTask;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/** Bounded submission per article; only the caller may write ES after every batch succeeds. */
@Service
public class ArticleEmbeddingService {
    private final ZhipuEmbeddingService embedding;
    private final ThreadPoolTaskExecutor executor;
    private final EmbeddingExecutionProperties properties;
    private record BatchResult(int offset, List<List<Double>> vectors) {}

    public ArticleEmbeddingService(ZhipuEmbeddingService embedding,
            @Qualifier("articleEmbeddingExecutor") ThreadPoolTaskExecutor executor,
            EmbeddingExecutionProperties properties) {
        properties.validate();
        this.embedding = embedding;
        this.executor = executor;
        this.properties = properties;
    }

    public List<List<Double>> embed(List<String> texts) {
        if (texts.isEmpty()) return List.of();
        if (texts.size() > DocumentChunkService.MAX_CHUNKS) throw new BusinessException("文章超过分块数量上限");
        List<String> input = List.copyOf(texts);
        int batchSize = properties.getBatchSize();
        int batches = (input.size() + batchSize - 1) / batchSize;
        int window = Math.min(properties.getPerArticleParallelism(), batches);
        BlockingQueue<FutureTask<BatchResult>> completed = new LinkedBlockingQueue<>(batches);
        List<FutureTask<BatchResult>> submitted = new ArrayList<>(batches);
        List<List<Double>> ordered = new ArrayList<>(Collections.nCopies(input.size(), null));
        long deadline = System.nanoTime() + properties.getArticleTimeout().toNanos();
        String trace = RequestTrace.current(), run = MDC.get("run_id");
        int next = 0, finished = 0;
        try {
            while (finished < batches) {
                if (Thread.currentThread().isInterrupted()) throw new InterruptedException();
                while (next < batches && next - finished < window) {
                    if (System.nanoTime() >= deadline) throw new TimeoutException();
                    int offset = next * batchSize;
                    List<String> batch = input.subList(offset, Math.min(offset + batchSize, input.size()));
                    var task = new FutureTask<BatchResult>(() -> {
                        try (var ignored = new RequestTrace(trace, run)) {
                            return new BatchResult(offset, embedding.embedBatch(batch));
                        }
                    }) {
                        @Override protected void done() { completed.add(this); }
                    };
                    submitted.add(task);
                    executor.execute(task);
                    next++;
                }
                long remaining = deadline - System.nanoTime();
                if (remaining <= 0) throw new TimeoutException();
                var future = completed.poll(remaining, TimeUnit.NANOSECONDS);
                if (future == null) throw new TimeoutException();
                BatchResult result = future.get();
                int expected = Math.min(batchSize, input.size() - result.offset());
                if (result.vectors() == null || result.vectors().size() != expected) {
                    throw new BusinessException("Embedding返回数量与文本块不一致");
                }
                for (int i = 0; i < expected; i++) ordered.set(result.offset() + i, result.vectors().get(i));
                finished++;
            }
            return List.copyOf(ordered);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new BusinessException("文章向量化已中断，未提交索引", error);
        } catch (TimeoutException error) {
            throw new BusinessException("文章向量化超时，未提交索引", error);
        } catch (ExecutionException error) {
            throw new BusinessException("文章向量化批次失败，未提交索引", error.getCause());
        } finally {
            // Cancelling a Future does not prove its HTTP call has stopped. The worker slot remains
            // occupied until it really returns; queued work is removed and can never write ES.
            for (var task : submitted) {
                task.cancel(true);
                executor.getThreadPoolExecutor().remove(task);
            }
        }
    }
}
