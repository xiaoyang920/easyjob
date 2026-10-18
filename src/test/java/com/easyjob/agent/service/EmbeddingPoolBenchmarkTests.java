package com.easyjob.agent.service;

import com.easyjob.agent.config.EmbeddingExecutionConfiguration;
import com.easyjob.agent.config.EmbeddingExecutionProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.IntStream;
import static org.junit.jupiter.api.Assertions.*;

/** Real project executor + real loopback HTTP; no paid model, Redis, MySQL or ES calls. */
@EnabledIfEnvironmentVariable(named = "EASYJOB_EMBEDDING_BENCHMARK", matches = "1")
class EmbeddingPoolBenchmarkTests {
    private static final ObjectMapper JSON = new ObjectMapper();
    private record Profile(String name, int core, int max, int queue, int window) {}
    private record Workload(String name, int consumers, int[] chunks, int providerCapacity, boolean cached, int deadlineMs) {}
    private record Trial(double milliseconds, String outcome, double backlogWaitMs, double endToEndMs) {}
    private record Measurement(double elapsedMs, List<Trial> articles, int providerCalls, int rateLimited,
                               int providerPeak, int workerPeak, int queuePeak, int largestPool) {}

    private static class Provider implements AutoCloseable {
        final HttpServer server;
        final ExecutorService handlers;
        final HttpClient client = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(2)).build();
        final AtomicInteger active = new AtomicInteger(), peak = new AtomicInteger(), calls = new AtomicInteger(), limited = new AtomicInteger();
        final Semaphore slots;
        Provider(int capacity) throws Exception {
            slots = new Semaphore(capacity);
            // The fixture must not silently cap a capacity-100 comparison at 16 handlers.
            handlers = Executors.newFixedThreadPool(Math.max(16, capacity));
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.setExecutor(handlers);
            server.createContext("/embedding", exchange -> {
                boolean acquired = false;
                try {
                    var request = JSON.readTree(exchange.getRequestBody());calls.incrementAndGet();
                    acquired = slots.tryAcquire();
                    if (!acquired) {
                        limited.incrementAndGet();exchange.sendResponseHeaders(429, -1);return;
                    }
                    peak.accumulateAndGet(active.incrementAndGet(), Math::max);
                    // Deterministic I/O delay, 60..100ms. This is NOT a provider latency measurement.
                    Thread.sleep(60 + Math.floorMod(request.path("id").asText().hashCode(), 41));
                    byte[] result = "{\"ok\":true}".getBytes(java.nio.charset.StandardCharsets.UTF_8);
                    exchange.getResponseHeaders().set("Content-Type", "application/json");
                    exchange.sendResponseHeaders(200, result.length);exchange.getResponseBody().write(result);
                } catch (InterruptedException error) {
                    Thread.currentThread().interrupt();
                } catch (java.io.IOException ignored) { /* Client cancellation may close the connection. */ }
                finally {
                    if (acquired) {active.decrementAndGet();slots.release();}
                    exchange.close();
                }
            });
            server.start();
        }
        void awaitIdle() throws Exception {
            long end=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
            while(active.get()!=0 && System.nanoTime()<end) Thread.sleep(5);
            assertEquals(0,active.get());
        }
        void reset() throws Exception { awaitIdle();calls.set(0);limited.set(0);peak.set(0); }
        void request(String identity) {
            try {
                var request=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+server.getAddress().getPort()+"/embedding"))
                        .timeout(Duration.ofSeconds(3)).header("Content-Type","application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(Map.of("id",identity)))).build();
                var response=client.send(request,HttpResponse.BodyHandlers.ofString());
                if(response.statusCode()!=200) throw new IllegalStateException("simulated_provider_"+response.statusCode());
            } catch(InterruptedException error) {
                Thread.currentThread().interrupt();throw new IllegalStateException("interrupted",error);
            } catch(java.io.IOException error) { throw new IllegalStateException("loopback_http_failure",error); }
        }
        public void close() {
            // close() can wait indefinitely for cancelled JDK21 HTTP exchanges. Shut the
            // owned fixture down explicitly, with a bounded wait, before the next scenario.
            server.stop(0);handlers.shutdownNow();client.shutdownNow();
            try { assertTrue(client.awaitTermination(Duration.ofSeconds(3)), "HTTP fixture did not terminate"); }
            catch(InterruptedException error){Thread.currentThread().interrupt();throw new IllegalStateException(error);}
        }
    }

    private static class HttpEmbedding extends ZhipuEmbeddingService {
        final Provider provider;final boolean cached;
        HttpEmbedding(Provider provider,boolean cached) { super(null);this.provider=provider;this.cached=cached; }
        @Override public List<List<Double>> embedBatch(List<String> texts) {
            String first=texts.getFirst();int firstChunk=Integer.parseInt(first.substring(first.lastIndexOf('-')+1));
            // 50% batch cache-hit scenario. Real Redis/cache overhead is not measured here.
            if(!cached || (firstChunk/16)%2!=0) provider.request(first);
            return texts.stream().map(text->Collections.nCopies(2048,
                    Double.parseDouble(text.substring(text.lastIndexOf('-')+1)))).toList();
        }
    }

    private Measurement measure(Profile profile,Workload workload,Provider provider) throws Exception {
        return measure(profile,workload,provider,0);
    }

    private Measurement measure(Profile profile,Workload workload,Provider provider,int simulatedStorageMs) throws Exception {
        var properties=new EmbeddingExecutionProperties();
        properties.setCorePoolSize(profile.core);properties.setMaxPoolSize(profile.max);
        properties.setQueueCapacity(profile.queue);properties.setPerArticleParallelism(profile.window);
        properties.setArticleTimeout(Duration.ofMillis(workload.deadlineMs));
        var pool=new EmbeddingExecutionConfiguration().articleEmbeddingExecutor(properties);pool.initialize();
        var service=new ArticleEmbeddingService(new HttpEmbedding(provider,workload.cached),pool,properties);
        var workers=new AtomicInteger();var queued=new AtomicInteger();
        var sampler=Executors.newSingleThreadScheduledExecutor();
        var startGate=new CountDownLatch(1);
        var callerPool=Executors.newFixedThreadPool(workload.consumers);
        provider.reset();
        sampler.scheduleAtFixedRate(()->{
            workers.accumulateAndGet(pool.getActiveCount(),Math::max);
            queued.accumulateAndGet(pool.getQueueSize(),Math::max);
        },0,2,TimeUnit.MILLISECONDS);
        long started=System.nanoTime();
        List<Trial> results=new ArrayList<>();
        try {
            var futures=new ArrayList<Future<Trial>>();
            for(int article=0;article<workload.chunks.length;article++) {
                int identity=article,count=workload.chunks[article];
                long enqueued=System.nanoTime();
                futures.add(callerPool.submit(()->{
                    startGate.await();long begin=System.nanoTime();String outcome="success";
                    try {
                        var texts=IntStream.range(0,count).mapToObj(chunk->"article-"+identity+"-"+chunk).toList();
                        var vectors=service.embed(texts);assertEquals(count,vectors.size());
                        for(int i=0;i<count;i++) assertEquals((double)i,vectors.get(i).getFirst());
                        if(simulatedStorageMs>0)Thread.sleep(simulatedStorageMs);
                    } catch(Exception error) { outcome=classify(error); }
                    long end=System.nanoTime();
                    return new Trial((end-begin)/1_000_000.0,outcome,
                            (begin-enqueued)/1_000_000.0,(end-enqueued)/1_000_000.0);
                }));
            }
            startGate.countDown();
            for(var future:futures) results.add(future.get(30,TimeUnit.SECONDS));
            double elapsed=(System.nanoTime()-started)/1_000_000.0;
            int largest=pool.getThreadPoolExecutor().getLargestPoolSize();
            return new Measurement(elapsed,results,provider.calls.get(),provider.limited.get(),provider.peak.get(),
                    workers.get(),queued.get(),largest);
        } finally {
            startGate.countDown();callerPool.shutdownNow();sampler.shutdownNow();pool.shutdown();provider.awaitIdle();
        }
    }

    private String classify(Throwable error) {
        for(Throwable cause=error;cause!=null;cause=cause.getCause()) {
            if(cause instanceof RejectedExecutionException)return "pool_rejected";
            if(cause instanceof TimeoutException)return "article_timeout";
            if("simulated_provider_429".equals(cause.getMessage()))return "provider_429";
        }
        return "unexpected_"+error.getClass().getSimpleName();
    }
    private double percentile(List<Double> values,double percentile) {
        var ordered=values.stream().sorted().toList();
        return ordered.get(Math.min(ordered.size()-1,(int)Math.ceil(ordered.size()*percentile)-1));
    }

    @Test void compareBoundedPoolProfiles() throws Exception {
        var profiles=List.of(new Profile("serial",1,1,8,1),new Profile("fixed2",2,2,8,2),
                new Profile("elastic2_4_q16",2,4,16,2),new Profile("fixed4_q8",4,4,8,2),
                new Profile("elastic4_8",4,8,8,2),new Profile("fixed8",8,8,8,2),
                new Profile("fixed4_q64",4,4,64,2),new Profile("fixed4_window4",4,4,8,4),
                new Profile("fixed4_q0",4,4,0,2));
        var workloads=List.of(
                new Workload("single_long",1,new int[]{256},4,false,10_000),
                new Workload("short_backlog",4,new int[]{8,16,12,8,16,8,16,8,12,16,8,16},4,false,10_000),
                new Workload("mixed_two_consumers",2,new int[]{8,16,32,64,128,256,64,24},4,false,10_000),
                new Workload("burst_four_consumers",4,new int[]{16,64,128,256,32,64,128,64,16,256,64,32},4,false,10_000),
                new Workload("half_cached",4,new int[]{16,64,128,256,32,64,128,64},4,true,10_000),
                new Workload("provider_capacity_2",4,new int[]{64,64,128,64,128,64,32,64},2,false,10_000),
                new Workload("provider_capacity_8",4,new int[]{64,64,128,64,128,64,32,64},8,false,10_000),
                new Workload("overload_16_callers",16,IntStream.range(0,24).map(i->64).toArray(),4,false,350));
        var report=new LinkedHashMap<String,Object>();
        report.put("mode","real_project_executor_with_simulated_loopback_embedding_http");
        report.put("paid_model_calls",0);report.put("database_or_es_writes",0);
        report.put("provider_latency_ms","deterministic 60..100ms, synthetic; excludes real token-length/Redis/provider effects");
        report.put("normal_provider_capacity_assumption",4);
        report.put("repetitions",3);report.put("java_version",System.getProperty("java.version"));
        report.put("available_processors",Runtime.getRuntime().availableProcessors());
        var rows=new ArrayList<Map<String,Object>>();report.put("results",rows);
        Path output=Path.of(System.getProperty("embedding.benchmark.output","logs/embedding-pool-benchmark.json"));
        Files.createDirectories(output.toAbsolutePath().getParent());
        for(var workload:workloads) try(var provider=new Provider(workload.providerCapacity)) {
            provider.request("warmup"); // Exclude first HTTP-client connection/class initialization.
            for(var profile:profiles) {
                var trials=new ArrayList<Measurement>();
                for(int repeat=0;repeat<3;repeat++)trials.add(measure(profile,workload,provider));
                var articles=trials.stream().flatMap(trial->trial.articles.stream()).toList();
                var outcomes=new TreeMap<String,Long>();articles.forEach(article->outcomes.merge(article.outcome,1L,Long::sum));
                assertTrue(outcomes.keySet().stream().noneMatch(key->key.startsWith("unexpected_")),outcomes.toString());
                var row=new LinkedHashMap<String,Object>();
                row.put("workload",workload.name);row.put("profile",profile.name);
                row.put("core",profile.core);row.put("max",profile.max);row.put("queue",profile.queue);row.put("article_window",profile.window);
                row.put("consumers",workload.consumers);row.put("article_chunks",workload.chunks);
                row.put("provider_capacity",workload.providerCapacity);row.put("outcomes",outcomes);
                row.put("article_p50_ms",percentile(articles.stream().map(Trial::milliseconds).toList(),.50));
                row.put("article_p95_ms",percentile(articles.stream().map(Trial::milliseconds).toList(),.95));
                row.put("mean_workload_ms",trials.stream().mapToDouble(Measurement::elapsedMs).average().orElseThrow());
                row.put("provider_calls",trials.stream().mapToInt(Measurement::providerCalls).sum());
                row.put("provider_429",trials.stream().mapToInt(Measurement::rateLimited).sum());
                row.put("peak_provider_concurrency",trials.stream().mapToInt(Measurement::providerPeak).max().orElseThrow());
                row.put("peak_active_workers",trials.stream().mapToInt(Measurement::workerPeak).max().orElseThrow());
                row.put("peak_queue_depth",trials.stream().mapToInt(Measurement::queuePeak).max().orElseThrow());
                row.put("largest_pool_size",trials.stream().mapToInt(Measurement::largestPool).max().orElseThrow());
                row.put("article_trials",articles);rows.add(row);
                JSON.writerWithDefaultPrettyPrinter().writeValue(output.toFile(),report);
                System.out.printf(Locale.ROOT,"embedding-benchmark workload=%s profile=%s outcomes=%s p95_ms=%.1f%n",
                        workload.name,profile.name,outcomes,(double)row.get("article_p95_ms"));
            }
        }
        assertEquals(72,rows.size());
        var selected=rows.stream().filter(row->row.get("profile").equals("fixed4_q8")
                && !Set.of("provider_capacity_2","overload_16_callers").contains(row.get("workload"))).toList();
        assertTrue(selected.stream().allMatch(row->((Map<?,?>)row.get("outcomes")).keySet().equals(Set.of("success"))));
        report.put("passed",true);JSON.writerWithDefaultPrettyPrinter().writeValue(output.toFile(),report);
    }

    @Test void compareConsumerLimitsOnSameInputs() throws Exception {
        var profile=new Profile("fixed4_q8",4,4,8,2);
        var rows=new ArrayList<Map<String,Object>>();
        var report=new LinkedHashMap<String,Object>();
        report.put("mode","same_inputs_consumer_comparison_with_simulated_loopback_embedding");
        report.put("paid_model_calls",0);report.put("database_or_es_writes",0);
        report.put("provider_capacity",4);report.put("provider_latency_ms","synthetic 60..100ms");
        report.put("repetitions",3);report.put("results",rows);
        Path output=Path.of("logs/embedding-consumer-benchmark.json");
        Files.createDirectories(output.toAbsolutePath().getParent());
        for(String scenario:List.of("short_articles","long_articles","long_with_storage_wait")) {
            int[] chunks=scenario.equals("short_articles")
                    ?new int[]{8,16,12,8,16,8,16,8,12,16,8,16}:IntStream.range(0,8).map(i->64).toArray();
            int storageMs=scenario.equals("long_with_storage_wait")?200:0;
            try(var provider=new Provider(4)) {
                provider.request("warmup");
                for(int consumers:List.of(1,2,4)) {
                    var workload=new Workload(scenario,consumers,chunks,4,false,10_000);
                    var trials=new ArrayList<Measurement>();
                    for(int repeat=0;repeat<3;repeat++)trials.add(measure(profile,workload,provider,storageMs));
                    var articles=trials.stream().flatMap(trial->trial.articles.stream()).toList();
                    assertTrue(articles.stream().allMatch(article->article.outcome.equals("success")));
                    double elapsed=trials.stream().mapToDouble(Measurement::elapsedMs).average().orElseThrow();
                    var row=new LinkedHashMap<String,Object>();row.put("scenario",scenario);row.put("consumers",consumers);
                    row.put("same_article_chunks",chunks);row.put("simulated_storage_wait_ms",storageMs);
                    row.put("mean_whole_workload_ms",elapsed);row.put("successful_article_trials",articles.size());
                    row.put("article_processing_p95_ms",percentile(articles.stream().map(Trial::milliseconds).toList(),.95));
                    row.put("peak_workers",trials.stream().mapToInt(Measurement::workerPeak).max().orElseThrow());
                    row.put("peak_queued_batches",trials.stream().mapToInt(Measurement::queuePeak).max().orElseThrow());
                    row.put("article_trials",articles);rows.add(row);
                    JSON.writerWithDefaultPrettyPrinter().writeValue(output.toFile(),report);
                    System.out.printf(Locale.ROOT,"consumer-benchmark scenario=%s consumers=%d workload_ms=%.1f%n",scenario,consumers,elapsed);
                }
            }
        }
        assertEquals(9,rows.size());report.put("passed",true);
        JSON.writerWithDefaultPrettyPrinter().writeValue(output.toFile(),report);
    }

    @Test void compareArticleWindowsOnSameInputs() throws Exception {
        var profiles=List.of(new Profile("window2_q8",4,4,8,2),
                new Profile("window4_q16",4,4,16,4),new Profile("all_batches_q128",4,4,128,32));
        var workloads=List.of(new Workload("single_512_chunks",1,new int[]{512},4,false,10_000),
                new Workload("mixed_with_short_articles",4,new int[]{512,8,16,64,128,8,32,16},4,false,10_000));
        var report=new LinkedHashMap<String,Object>();var rows=new ArrayList<Map<String,Object>>();
        report.put("mode","same_inputs_article_window_comparison_with_simulated_loopback_embedding");
        report.put("paid_model_calls",0);report.put("database_or_es_writes",0);report.put("provider_capacity",4);
        report.put("provider_latency_ms","synthetic 60..100ms");report.put("repetitions",3);report.put("results",rows);
        Path output=Path.of("logs/embedding-window-benchmark.json");
        Files.createDirectories(output.toAbsolutePath().getParent());
        for(var workload:workloads)try(var provider=new Provider(4)) {
            provider.request("warmup");
            for(var profile:profiles) {
                var trials=new ArrayList<Measurement>();
                for(int repeat=0;repeat<3;repeat++)trials.add(measure(profile,workload,provider));
                var articles=trials.stream().flatMap(trial->trial.articles.stream()).toList();
                assertTrue(articles.stream().allMatch(article->article.outcome.equals("success")));
                var shortArticles=new ArrayList<Double>();
                for(var trial:trials)for(int i=0;i<workload.chunks.length;i++)
                    if(workload.chunks[i]<=16)shortArticles.add(trial.articles.get(i).milliseconds);
                var row=new LinkedHashMap<String,Object>();row.put("scenario",workload.name);row.put("profile",profile.name);
                row.put("same_article_chunks",workload.chunks);row.put("consumers",workload.consumers);
                row.put("article_window",profile.window);row.put("queue",profile.queue);row.put("core",profile.core);row.put("max",profile.max);
                row.put("mean_whole_workload_ms",trials.stream().mapToDouble(Measurement::elapsedMs).average().orElseThrow());
                row.put("article_processing_p95_ms",percentile(articles.stream().map(Trial::milliseconds).toList(),.95));
                row.put("short_article_processing_p95_ms",shortArticles.isEmpty()?null:percentile(shortArticles,.95));
                row.put("peak_queued_batches",trials.stream().mapToInt(Measurement::queuePeak).max().orElseThrow());
                row.put("successful_article_trials",articles.size());row.put("article_trials",articles);rows.add(row);
                JSON.writerWithDefaultPrettyPrinter().writeValue(output.toFile(),report);
                System.out.printf(Locale.ROOT,"window-benchmark scenario=%s profile=%s workload_ms=%.1f short_p95=%s%n",
                        workload.name,profile.name,(double)row.get("mean_whole_workload_ms"),row.get("short_article_processing_p95_ms"));
            }
        }
        assertEquals(6,rows.size());report.put("passed",true);
        JSON.writerWithDefaultPrettyPrinter().writeValue(output.toFile(),report);
    }

    @Test void compareConsumersAndWorkersAtCapacity100() throws Exception {
        record Candidate(Profile profile,int consumers) {}
        record Scenario(String name,int[] chunks,int storageMs,boolean single) {}
        var candidates=new ArrayList<Candidate>();
        for(int consumers:List.of(2,4,8))for(int threads:List.of(4,8,16))for(int window:List.of(2,4)) {
            // Size the queue for all consumer windows, so this test isolates useful
            // parallelism rather than accidentally comparing rejection-heavy queues.
            int queue=Math.max(8,consumers*window);
            candidates.add(new Candidate(new Profile("c"+consumers+"_t"+threads+"_w"+window+"_q"+queue,
                    threads,threads,queue,window),consumers));
        }
        var singleCandidates=new ArrayList<Candidate>();
        for(int threads:List.of(4,8,16))for(int window:List.of(2,4,8))
            singleCandidates.add(new Candidate(new Profile("c1_t"+threads+"_w"+window+"_q16",
                    threads,threads,16,window),1));
        int[] shortChunks=IntStream.range(0,24).map(i->new int[]{8,12,16}[i%3]).toArray();
        int[] longChunks=IntStream.range(0,12).map(i->new int[]{64,128,256}[i%3]).toArray();
        int[] mixedChunks=IntStream.range(0,24).map(i->new int[]{512,8,16,64,128,8,32,16}[i%8]).toArray();
        var scenarios=List.of(new Scenario("short_backlog",shortChunks,0,false),
                new Scenario("long_backlog",longChunks,0,false),
                new Scenario("long_with_storage_wait",longChunks,200,false),
                new Scenario("mixed_with_storage_wait",mixedChunks,200,false),
                new Scenario("single_512_chunks",new int[]{512},0,true));
        int repetitions=3;
        var rows=new ArrayList<Map<String,Object>>();var report=new LinkedHashMap<String,Object>();
        report.put("mode","capacity_100_same_inputs_consumer_worker_comparison_with_simulated_loopback_http");
        report.put("paid_model_calls",0);report.put("database_or_es_writes",0);
        report.put("provider_capacity",100);report.put("provider_handler_threads",100);
        report.put("provider_latency_ms","synthetic deterministic 60..100ms, independent of token length");
        report.put("storage_wait","synthetic per-article 200ms sleep in named scenarios; no real ES or DB");
        report.put("consumer_simulation","fixed caller threads, no RabbitMQ broker or dynamic container scaling");
        report.put("end_to_end_latency","caller-queue submission to completion, including simulated backlog and storage wait");
        report.put("processing_latency","consumer start to completion, including embedding queue and simulated storage wait");
        report.put("model_quota","100 is a scenario assumption; embedding-3-pro screenshot is not verification of configured embedding-3 quota");
        report.put("repetitions",repetitions);report.put("batch_size",16);
        report.put("java_version",System.getProperty("java.version"));
        report.put("available_processors",Runtime.getRuntime().availableProcessors());report.put("results",rows);
        Path output=Path.of("logs/embedding-capacity100-benchmark.json");
        Files.createDirectories(output.toAbsolutePath().getParent());
        int completed=0;
        for(var scenario:scenarios)try(var provider=new Provider(100)) {
            provider.request("warmup");
            measure(new Profile("warmup",4,4,8,2),
                    new Workload("warmup",2,new int[]{32,32},100,false,20_000),provider);
            var compared=scenario.single?singleCandidates:candidates;
            var trialsByCandidate=new LinkedHashMap<Candidate,List<Measurement>>();
            for(var candidate:compared)trialsByCandidate.put(candidate,new ArrayList<>());
            for(int repeat=0;repeat<repetitions;repeat++) {
                var order=new ArrayList<>(compared);
                Collections.shuffle(order,new Random(20261016L+repeat));
                for(var candidate:order) {
                    var workload=new Workload(scenario.name,candidate.consumers,scenario.chunks,100,false,20_000);
                    var result=measure(candidate.profile,workload,provider,scenario.storageMs);
                    trialsByCandidate.get(candidate).add(result);completed++;
                    System.out.printf(Locale.ROOT,
                            "capacity100-benchmark scenario=%s repeat=%d profile=%s workload_ms=%.1f success=%d/%d%n",
                            scenario.name,repeat+1,candidate.profile.name,result.elapsedMs,
                            result.articles.stream().filter(article->article.outcome.equals("success")).count(),result.articles.size());
                }
            }
            for(var entry:trialsByCandidate.entrySet()) {
                var candidate=entry.getKey();var profile=candidate.profile;var trials=entry.getValue();
                var articles=trials.stream().flatMap(trial->trial.articles.stream()).toList();
                var outcomes=new TreeMap<String,Long>();articles.forEach(article->outcomes.merge(article.outcome,1L,Long::sum));
                var shortArticles=new ArrayList<Double>();
                for(var trial:trials)for(int i=0;i<scenario.chunks.length;i++)
                    if(scenario.chunks[i]<=16)shortArticles.add(trial.articles.get(i).endToEndMs);
                double elapsed=trials.stream().mapToDouble(Measurement::elapsedMs).average().orElseThrow();
                var row=new LinkedHashMap<String,Object>();
                row.put("scenario",scenario.name);row.put("profile",profile.name);
                row.put("consumers",candidate.consumers);row.put("core",profile.core);row.put("max",profile.max);
                row.put("queue",profile.queue);row.put("article_window",profile.window);
                row.put("same_article_chunks",scenario.chunks);row.put("simulated_storage_wait_ms",scenario.storageMs);
                row.put("mean_whole_workload_ms",elapsed);
                row.put("mean_successful_articles_per_second",trials.stream().mapToDouble(trial->
                        trial.articles.stream().filter(article->article.outcome.equals("success")).count()*1000.0/trial.elapsedMs)
                        .average().orElseThrow());
                row.put("article_processing_p95_ms",percentile(articles.stream().map(Trial::milliseconds).toList(),.95));
                row.put("article_end_to_end_p95_ms",percentile(articles.stream().map(Trial::endToEndMs).toList(),.95));
                row.put("article_backlog_wait_p95_ms",percentile(articles.stream().map(Trial::backlogWaitMs).toList(),.95));
                row.put("short_article_end_to_end_p95_ms",shortArticles.isEmpty()?null:percentile(shortArticles,.95));
                row.put("peak_provider_concurrency",trials.stream().mapToInt(Measurement::providerPeak).max().orElseThrow());
                row.put("peak_workers",trials.stream().mapToInt(Measurement::workerPeak).max().orElseThrow());
                row.put("largest_pool_size",trials.stream().mapToInt(Measurement::largestPool).max().orElseThrow());
                row.put("peak_queued_batches",trials.stream().mapToInt(Measurement::queuePeak).max().orElseThrow());
                row.put("provider_calls",trials.stream().mapToInt(Measurement::providerCalls).sum());
                row.put("provider_429",trials.stream().mapToInt(Measurement::rateLimited).sum());
                row.put("outcomes",outcomes);row.put("article_trials",articles);rows.add(row);
            }
            report.put("completed_workload_runs",completed);
            JSON.writerWithDefaultPrettyPrinter().writeValue(output.toFile(),report);
        }
        validateCapacity100Report(report);
        report.put("article_trials",rows.stream().mapToInt(row->((List<?>)row.get("article_trials")).size()).sum());
        report.put("passed",true);JSON.writerWithDefaultPrettyPrinter().writeValue(output.toFile(),report);
    }

    private void validateCapacity100Report(Map<String,Object> report) {
        var tree=JSON.valueToTree(report);var rows=tree.path("results");
        assertEquals("capacity_100_same_inputs_consumer_worker_comparison_with_simulated_loopback_http",tree.path("mode").asText());
        assertEquals(100,tree.path("provider_capacity").asInt());
        assertEquals(3,tree.path("repetitions").asInt());
        assertEquals(81,rows.size());assertEquals(243,tree.path("completed_workload_runs").asInt());
        int articleTrials=0;
        var identities=new HashSet<String>();var sameInputs=new HashMap<String,List<Integer>>();
        for(var row:rows) {
            assertTrue(identities.add(row.path("scenario").asText()+"/"+row.path("profile").asText()));
            assertEquals(1,row.path("outcomes").size(),"Latency ranking requires all-success measurements");
            var chunks=new ArrayList<Integer>();row.path("same_article_chunks").forEach(value->chunks.add(value.asInt()));
            var previous=sameInputs.putIfAbsent(row.path("scenario").asText(),chunks);
            if(previous!=null)assertEquals(previous,chunks,"Candidates must use the same article inputs");
            int count=chunks.size()*3,expected=chunks.stream().mapToInt(value->(value+15)/16).sum()*3;
            assertEquals(count,row.path("outcomes").path("success").asInt());
            assertEquals(count,row.path("article_trials").size());articleTrials+=count;
            assertEquals(expected,row.path("provider_calls").asInt(),"Every expected batch must reach the loopback fixture");
            assertEquals(0,row.path("provider_429").asInt());
            assertTrue(row.path("peak_workers").asInt()<=row.path("max").asInt());
            assertTrue(row.path("peak_queued_batches").asInt()<=row.path("queue").asInt());
            if(row.has("largest_pool_size"))assertTrue(row.path("largest_pool_size").asInt()<=row.path("max").asInt());
            // A client can receive the full response and send its next request before
            // the old server handler's finally block runs. Server cleanup overlaps;
            // its peak is bounded by provider capacity, not by client worker count.
            assertTrue(row.path("peak_provider_concurrency").asInt()<=tree.path("provider_capacity").asInt());
            assertTrue(row.path("mean_whole_workload_ms").asDouble()>0);
            for(var trial:row.path("article_trials")) {
                assertEquals("success",trial.path("outcome").asText());
                assertTrue(trial.path("backlogWaitMs").asDouble()>=0);
                assertEquals(trial.path("milliseconds").asDouble()+trial.path("backlogWaitMs").asDouble(),
                        trial.path("endToEndMs").asDouble(),.001);
            }
        }
        assertEquals(3915,articleTrials);
        report.put("provider_peak_definition","server handlers until response cleanup; may briefly exceed client workers");
    }

    /** Replay completed measurements after a validation-only repair; never runs implicitly. */
    @Test
    @EnabledIfSystemProperty(named="embedding.capacity100.validate-completed",matches="true")
    void validateCompletedCapacity100Measurements() throws Exception {
        // Fresh execution also checks the current fixture and production executor.
        try(var provider=new Provider(100)) {
            var measurement=measure(new Profile("validation_smoke",8,8,16,4),
                    new Workload("validation_smoke",4,new int[]{64,64,128,128},100,false,10_000),provider);
            assertTrue(measurement.articles.stream().allMatch(article->article.outcome.equals("success")));
            assertEquals(24,measurement.providerCalls);assertEquals(0,measurement.rateLimited);
            assertTrue(measurement.largestPool<=8);assertTrue(measurement.workerPeak<=8);
        }
        Path output=Path.of("logs/embedding-capacity100-benchmark.json");
        var report=JSON.readValue(output.toFile(),new com.fasterxml.jackson.core.type.TypeReference<LinkedHashMap<String,Object>>() {});
        validateCapacity100Report(report);
        report.put("article_trials",3915);report.put("passed",true);
        report.put("validation_replayed_from_completed_measurements",true);
        report.put("validation_note","Original workload runs all succeeded; replaced invalid server-peak <= client-workers assertion with local worker/queue bounds and server-peak <= provider-capacity checks. No timing measurements changed.");
        JSON.writerWithDefaultPrettyPrinter().writeValue(output.toFile(),report);
    }
}
