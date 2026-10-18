package com.easyjob.agent.service;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch.core.BulkRequest;
import co.elastic.clients.elasticsearch.core.BulkResponse;
import co.elastic.clients.util.ObjectBuilder;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.agent.config.EmbeddingExecutionConfiguration;
import com.easyjob.agent.config.EmbeddingExecutionProperties;
import com.easyjob.entity.DocumentChunk;
import com.easyjob.exception.BusinessException;
import com.easyjob.observability.RequestTrace;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.test.util.ReflectionTestUtils;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;
import java.util.stream.IntStream;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@SuppressWarnings({"unchecked", "rawtypes"})
class ArticleEmbeddingServiceTests {
    private record Fixture(EmbeddingExecutionProperties properties, ThreadPoolTaskExecutor executor,
                           ZhipuEmbeddingService provider, ArticleEmbeddingService service) implements AutoCloseable {
        public void close() { executor.shutdown(); }
    }
    private Fixture fixture(int threads, int queue, int window, int batch, Duration timeout) {
        var properties = new EmbeddingExecutionProperties();
        properties.setCorePoolSize(threads); properties.setMaxPoolSize(threads);
        properties.setQueueCapacity(queue); properties.setPerArticleParallelism(window);
        properties.setBatchSize(batch); properties.setArticleTimeout(timeout);
        return fixture(properties);
    }
    private Fixture fixture(EmbeddingExecutionProperties properties) {
        var executor = new EmbeddingExecutionConfiguration().articleEmbeddingExecutor(properties);
        executor.initialize();
        var provider = mock(ZhipuEmbeddingService.class);
        return new Fixture(properties, executor, provider, new ArticleEmbeddingService(provider, executor, properties));
    }
    private List<List<Double>> vectors(List<String> batch) {
        return batch.stream().map(text -> Collections.nCopies(2048, Double.parseDouble(text.substring(text.lastIndexOf('-')+1)))).toList();
    }
    private List<String> texts(int count) { return IntStream.range(0, count).mapToObj(i -> "chunk-"+i).toList(); }
    private List<DocumentChunk> chunks(int count) {
        return IntStream.range(0, count).mapToObj(i -> {
            var chunk = new DocumentChunk(); chunk.setArticleId("42"); chunk.setChunkIndex(i);
            chunk.setSourceHash("source");chunk.setChunkerVersion("html-dom-v1");chunk.setContent("chunk-"+i);
            return chunk;
        }).toList();
    }
    private EsVectorStore store(Fixture f, ElasticsearchClient es) {
        var store = new EsVectorStore();
        ReflectionTestUtils.setField(store, "esClient", es);
        ReflectionTestUtils.setField(store, "articleEmbeddingService", f.service);
        return store;
    }

    @Test void completionOrderCannotMixUpChunksAndFastBatchesKeepTheWindowMoving() throws Exception {
        try (var f = fixture(2, 2, 2, 2, Duration.ofSeconds(3))) {
            var thirdStarted = new CountDownLatch(1);
            var order = new ConcurrentLinkedQueue<String>();
            when(f.provider.embedBatch(anyList())).thenAnswer(call -> {
                List<String> batch = call.getArgument(0);
                if (batch.getFirst().equals("chunk-0")) assertTrue(thirdStarted.await(2, TimeUnit.SECONDS));
                if (batch.getFirst().equals("chunk-4")) thirdStarted.countDown();
                order.add(batch.getFirst()); return vectors(batch);
            });
            var output = f.service.embed(texts(6));
            assertNotEquals("chunk-0", order.peek());
            for (int i=0; i<6; i++) assertEquals((double)i, output.get(i).getFirst());
        }
    }

    @Test void oneSharedPoolCapsAllArticlesAndEachArticleHasItsOwnWindow() throws Exception {
        try (var f = fixture(new EmbeddingExecutionProperties()); var callers = Executors.newFixedThreadPool(4)) {
            var entered = new CountDownLatch(f.properties.getCorePoolSize());var release = new CountDownLatch(1);
            var active = new AtomicInteger();var peak = new AtomicInteger();
            var perArticle = new ConcurrentHashMap<String, AtomicInteger>();
            var perPeak = new ConcurrentHashMap<String, AtomicInteger>();
            when(f.provider.embedBatch(anyList())).thenAnswer(call -> {
                List<String> batch = call.getArgument(0);String article=batch.getFirst().split("-")[0];
                int own=perArticle.computeIfAbsent(article,k->new AtomicInteger()).incrementAndGet();
                perPeak.computeIfAbsent(article,k->new AtomicInteger()).accumulateAndGet(own,Math::max);
                peak.accumulateAndGet(active.incrementAndGet(),Math::max);entered.countDown();
                try { assertTrue(release.await(3,TimeUnit.SECONDS));return vectors(batch); }
                finally { active.decrementAndGet();perArticle.get(article).decrementAndGet(); }
            });
            var results=IntStream.range(0,4).mapToObj(a->callers.submit(()->f.service.embed(
                    IntStream.range(0,96).mapToObj(i->"a"+a+"-"+i).toList()))).toList();
            try {
                assertTrue(entered.await(3,TimeUnit.SECONDS));assertEquals(f.properties.getCorePoolSize(),active.get());
            } finally { release.countDown(); }
            for(var result:results) assertEquals(96,result.get(4,TimeUnit.SECONDS).size());
            assertEquals(f.properties.getCorePoolSize(),peak.get());
            assertTrue(perPeak.values().stream().allMatch(value->value.get()<=f.properties.getPerArticleParallelism()));
        }
    }

    @Test void rejectionCancelsPreviouslyQueuedBatchesWithoutCallingProvider() throws Exception {
        try (var f = fixture(1, 1, 2, 1, Duration.ofSeconds(2))) {
            var busy = new CountDownLatch(1);var release = new CountDownLatch(1);
            f.executor.execute(()->{busy.countDown();try { release.await(); } catch(InterruptedException e){Thread.currentThread().interrupt();}});
            assertTrue(busy.await(2,TimeUnit.SECONDS));
            try {
                assertThrows(RejectedExecutionException.class,()->f.service.embed(texts(3)));
                assertEquals(0,f.executor.getQueueSize());verifyNoInteractions(f.provider);
            } finally { release.countDown(); }
        }
    }

    @Test void failedBatchInterruptsItsSiblingAndCannotWriteEs() throws Exception {
        try (var f = fixture(2, 2, 2, 1, Duration.ofSeconds(3))) {
            var siblingStarted=new CountDownLatch(1);var interrupted=new CountDownLatch(1);
            when(f.provider.embedBatch(anyList())).thenAnswer(call->{
                List<String> batch=call.getArgument(0);
                if(batch.getFirst().endsWith("-0")) {
                    assertTrue(siblingStarted.await(2,TimeUnit.SECONDS));throw new IllegalStateException("simulated failure");
                }
                siblingStarted.countDown();
                try { new CountDownLatch(1).await();throw new AssertionError(); }
                catch(InterruptedException e){interrupted.countDown();throw e;}
            });
            var es=mock(ElasticsearchClient.class);
            assertThrows(BusinessException.class,()->store(f,es).saveChunks(chunks(3)));
            assertTrue(interrupted.await(2,TimeUnit.SECONDS));verifyNoInteractions(es);
            verify(f.provider,times(2)).embedBatch(anyList());
        }
    }

    @Test void timeoutDoesNotFreeAnHttpWorkerThatIgnoresInterruptOrAllowLateEsWrite() throws Exception {
        try (var f=fixture(1,2,1,1,Duration.ofMillis(80))) {
            var release=new CountDownLatch(1);var actuallyFinished=new CountDownLatch(1);
            when(f.provider.embedBatch(anyList())).thenAnswer(call->{
                while(release.getCount()!=0) try {release.await();} catch(InterruptedException ignored) {}
                actuallyFinished.countDown();return vectors(call.getArgument(0));
            });
            var es=mock(ElasticsearchClient.class);
            try {
                assertThrows(BusinessException.class,()->store(f,es).saveChunks(chunks(2)));
                assertEquals(1,f.executor.getActiveCount());
                assertThrows(BusinessException.class,()->store(f,es).saveChunks(chunks(2)));
                assertEquals(0,f.executor.getQueueSize());verify(f.provider,times(1)).embedBatch(anyList());
            } finally {release.countDown();}
            assertTrue(actuallyFinished.await(2,TimeUnit.SECONDS));verifyNoInteractions(es);
        }
    }

    @Test void interruptIsPreservedAndQueuedWorkIsRemoved() throws Exception {
        try (var f=fixture(1,1,1,1,Duration.ofSeconds(2))) {
            var entered=new CountDownLatch(1);var exited=new CountDownLatch(1);
            when(f.provider.embedBatch(anyList())).thenAnswer(call->{entered.countDown();new CountDownLatch(1).await();return List.of();});
            var interruptPreserved=new AtomicInteger();
            var caller=new Thread(()->{try{f.service.embed(texts(2));}catch(BusinessException e){
                if(Thread.currentThread().isInterrupted())interruptPreserved.set(1);
            }finally{exited.countDown();}});
            caller.start();assertTrue(entered.await(2,TimeUnit.SECONDS));caller.interrupt();
            assertTrue(exited.await(2,TimeUnit.SECONDS));assertEquals(1,interruptPreserved.get());
        }
    }

    @Test void bulkRunsOnceAfterAllBatchesAndVectorsKeepOriginalChunkIds() throws Exception {
        try (var f=fixture(4,8,2,16,Duration.ofSeconds(3))) {
            when(f.provider.embedBatch(anyList())).thenAnswer(call->vectors(call.getArgument(0)));
            var es=mock(ElasticsearchClient.class);var chunks=chunks(36);
            when(es.bulk(any(Function.class))).thenAnswer(call->{
                Function<BulkRequest.Builder,ObjectBuilder<BulkRequest>> builder=call.getArgument(0);
                var request=builder.apply(new BulkRequest.Builder()).build();
                assertEquals(36,request.operations().size());
                for(int i=0;i<36;i++) {
                    var operation=request.operations().get(i).index();
                    assertEquals(chunks.get(i).getChunkId(),operation.id());
                    var document=(Map<String,Object>)operation.document();
                    assertEquals((double)i,((List<Double>)document.get("content_vector")).getFirst());
                }
                return BulkResponse.of(b->b.errors(false).took(1).items(List.of()));
            });
            store(f,es).saveChunks(chunks);
            verify(f.provider,times(3)).embedBatch(anyList());verify(es,times(1)).bulk(any(Function.class));
        }
    }

    @Test void mismatchedBatchSizeAndOversizedInputFailBeforeEsWrite() {
        try (var f=fixture(2,2,2,2,Duration.ofSeconds(2))) {
            when(f.provider.embedBatch(anyList())).thenReturn(List.of());
            var es=mock(ElasticsearchClient.class);
            assertThrows(BusinessException.class,()->store(f,es).saveChunks(chunks(3)));
            verifyNoInteractions(es);
            assertThrows(BusinessException.class,()->f.service.embed(texts(513)));
            assertTrue(f.service.embed(List.of()).isEmpty());
        }
    }

    @Test void maximum512ChunksUse32BatchesWithoutSubmittingThemAllAtOnce() {
        try (var f=fixture(4,8,2,16,Duration.ofSeconds(3))) {
            when(f.provider.embedBatch(anyList())).thenAnswer(call->vectors(call.getArgument(0)));
            var output=f.service.embed(texts(512));
            assertEquals(512,output.size());
            for(int i=0;i<512;i++)assertEquals((double)i,output.get(i).getFirst());
            verify(f.provider,times(32)).embedBatch(anyList());
            assertTrue(f.executor.getThreadPoolExecutor().getLargestPoolSize()<=4);
        }
    }

    @Test void threadNamesAndRequestTraceAreIsolated() throws Exception {
        try (var f=fixture(1,1,1,1,Duration.ofSeconds(2))) {
            when(f.provider.embedBatch(anyList())).thenAnswer(call->{
                assertTrue(Thread.currentThread().getName().startsWith("article-embedding-"));
                assertEquals("embedding-test-trace",MDC.get("trace_id"));return vectors(call.getArgument(0));
            });
            try(var trace=new RequestTrace("embedding-test-trace",null)){f.service.embed(texts(1));}
            assertNull(f.executor.submit(()->MDC.get("trace_id")).get(2,TimeUnit.SECONDS));
        }
    }

    @Test void externalConfigurationBindsAndInvalidRangesPreventStartup() {
        new ApplicationContextRunner().withUserConfiguration(EmbeddingExecutionConfiguration.class)
                .withPropertyValues("agent.embedding.execution.core-pool-size=2","agent.embedding.execution.max-pool-size=4",
                        "agent.embedding.execution.queue-capacity=16","agent.embedding.execution.article-timeout=3s")
                .run(context->{assertNull(context.getStartupFailure());
                    var pool=context.getBean("articleEmbeddingExecutor",ThreadPoolTaskExecutor.class);
                    assertEquals(2,pool.getCorePoolSize());assertEquals(4,pool.getMaxPoolSize());assertEquals(16,pool.getQueueCapacity());
                    assertEquals(Duration.ofSeconds(3),context.getBean(EmbeddingExecutionProperties.class).getArticleTimeout());});
        new ApplicationContextRunner().withUserConfiguration(EmbeddingExecutionConfiguration.class)
                .withPropertyValues("agent.embedding.execution.core-pool-size=5","agent.embedding.execution.max-pool-size=4")
                .run(context->assertNotNull(context.getStartupFailure()));
    }
}
