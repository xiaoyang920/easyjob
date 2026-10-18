package com.easyjob.agent.graph.config;

import com.alibaba.cloud.ai.graph.CompiledGraph;
import com.alibaba.cloud.ai.graph.StateGraph;
import com.alibaba.cloud.ai.graph.exception.GraphStateException;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.agent.graph.node.*;
import com.easyjob.agent.graph.state.AgentStateFactory;
import com.easyjob.agent.tool.ArticleTool;
import com.easyjob.agent.tool.DeepSeekSearchTool;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.deepseek.DeepSeekChatModel;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import static com.alibaba.cloud.ai.graph.StateGraph.END;
import static com.alibaba.cloud.ai.graph.StateGraph.START;
import static com.alibaba.cloud.ai.graph.action.AsyncNodeAction.node_async;

/**
 * Agent Graph 配置（并行版）
 *
 * 拓扑：START → planner → dispatcher → synthesizer → END
 *
 * 并行逻辑封装在 DispatcherNode 内部：
 * - Planner 输出执行计划（哪些Worker、是否有依赖）
 * - Dispatcher 根据计划并行/串行执行Worker
 * - Synthesizer 汇总结果
 *
 * 为什么不在Graph层面定义并行分支？
 * 因为并行组合是动态的（由LLM决定），编译期无法穷举所有组合。
 * 把并行逻辑放在DispatcherNode内部，用CompletableFuture实现运行时动态并行。
 */
@Slf4j
@Configuration
@RequiredArgsConstructor
public class AgentGraphConfiguration {
    private final PlannerNode plannerNode;
    private final DispatcherNode dispatcherNode;
    private final SynthesizerNode synthesizerNode;

    @Bean("compiledAgentGraph")
    public CompiledGraph compiledAgentGraph() throws GraphStateException {

        StateGraph stateGraph = new StateGraph(new AgentStateFactory())
                // 注册节点
                .addNode("planner", node_async(plannerNode))
                .addNode("dispatcher", node_async(dispatcherNode))
                .addNode("synthesizer", node_async(synthesizerNode))

                // 定义边：简洁的三节点链
                .addEdge(START, "planner")
                .addEdge("planner", "dispatcher")
                .addEdge("dispatcher", "synthesizer")
                .addEdge("synthesizer", END);

        log.info("Agent Graph（并行版）构建并编译完成");
        return stateGraph.compile();
    }
}