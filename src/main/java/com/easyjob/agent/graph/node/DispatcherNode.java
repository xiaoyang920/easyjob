package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.agent.tool.ArticleTool;
import com.easyjob.agent.tool.DeepSeekSearchTool;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CopyOnWriteArrayList;

@Slf4j
@Component
@RequiredArgsConstructor
public class DispatcherNode implements NodeAction {


    private final SearchWorkerNode searchWorkerNode;
    private final AnalysisWorkerNode analysisWorkerNode;
    private final WritingWorkerNode writingWorkerNode;
    private final ChatWorkerNode chatWorkerNode;

    @Override
    @SuppressWarnings("unchecked")
    public Map<String, Object> apply(OverAllState state) throws Exception {
        List<String> activeWorkers = state.value("activeWorkers", List.of("chat"));
        String userMessage = state.value("userMessage", "");
        Long conversationId = state.value("conversationId", 0L);

        log.info("Dispatcher开始调度, activeWorkers: {}", activeWorkers);

        // 分离：依赖链任务 vs 独立并行任务
        List<String> parallelWorkers = new ArrayList<>();
        List<String> chainWorkers = new ArrayList<>();  // search_then_analysis 这种

        for (String worker : activeWorkers) {
            if (worker.contains("_then_")) {
                chainWorkers.add(worker);
            } else {
                parallelWorkers.add(worker);
            }
        }

        // 收集所有结果（线程安全）
        CopyOnWriteArrayList<Map<String, String>> allResults = new CopyOnWriteArrayList<>();
        // 用于传递 searchResult 给 analysis
        Map<String, String> sharedContext = new HashMap<>();

        // === 第一阶段：并行执行独立Worker + 依赖链的第一步 ===
        List<CompletableFuture<Void>> futures = new ArrayList<>();

        // 独立Worker并行执行
        for (String workerName : parallelWorkers) {
            futures.add(CompletableFuture.runAsync(() -> {
                try {
                    NodeAction worker = createWorker(workerName);
                    Map<String, Object> result = worker.apply(state);
                    collectResults(result, allResults);
                } catch (Exception e) {
                    log.error("Worker[{}]执行失败", workerName, e);
                    Map<String, String> errorResult = new HashMap<>();
                    errorResult.put("workerName", workerName);
                    errorResult.put("result", "该模块执行出错，请稍后重试");
                    allResults.add(errorResult);
                }
            }));
        }

        // 依赖链：先执行第一个，再执行第二个
        for (String chain : chainWorkers) {
            futures.add(CompletableFuture.runAsync(() -> {
                try {
                    String[] parts = chain.split("_then_");
                    // 执行第一个Worker（如search）
                    NodeAction firstWorker = createWorker(parts[0]);
                    Map<String, Object> firstResult = firstWorker.apply(state);
                    collectResults(firstResult, allResults);

                    // 将第一个Worker的结果写入共享上下文
                    if (firstResult.containsKey("searchResult")) {
                        sharedContext.put("searchResult", (String) firstResult.get("searchResult"));
                    }

                    // 执行第二个Worker（如analysis），注入前置结果
                    if (parts.length > 1) {
                        NodeAction secondWorker = createWorker(parts[1]);
                        Map<String, Object> secondResult = secondWorker.apply(state);
                        collectResults(secondResult, allResults);
                    }
                } catch (Exception e) {
                    log.error("依赖链[{}]执行失败", chain, e);
                }
            }));
        }

        // 等待所有任务完成
        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();

        log.info("Dispatcher调度完成, 总结果数: {}", allResults.size());

        // 构建输出（文章卡片留在 Redis，由 AgentService 统一取出，避免 AppendStrategy 导致重复）
        Map<String, Object> output = new HashMap<>();
        output.put("workerResults", new ArrayList<>(allResults));
        if (sharedContext.containsKey("searchResult")) {
            output.put("searchResult", sharedContext.get("searchResult"));
        }
        return output;
    }

    /**
     * 根据Worker名称创建对应的NodeAction实例
     */
    // createWorker 方法：直接返回注入的 Bean
    private NodeAction createWorker(String workerName) {
        return switch (workerName) {
            case "search" -> searchWorkerNode;
            case "analysis" -> analysisWorkerNode;
            case "writing" -> writingWorkerNode;
            case "chat" -> chatWorkerNode;
            default -> throw new IllegalArgumentException("未知的Worker: " + workerName);
        };
    }

    /**
     * 收集Worker结果到线程安全列表
     */
    @SuppressWarnings("unchecked")
    private void collectResults(Map<String, Object> result,
                                CopyOnWriteArrayList<Map<String, String>> allResults) {
        Object wr = result.get("workerResults");
        if (wr instanceof Map) {
            allResults.add((Map<String, String>) wr);
        }
    }
}