package com.easyjob.agent.graph.state;

import com.alibaba.cloud.ai.graph.KeyStrategy;
import com.alibaba.cloud.ai.graph.KeyStrategyFactory;
import com.alibaba.cloud.ai.graph.state.strategy.AppendStrategy;
import com.alibaba.cloud.ai.graph.state.strategy.ReplaceStrategy;

import java.util.HashMap;
import java.util.Map;

public class AgentStateFactory implements KeyStrategyFactory {

    @Override
    public Map<String, KeyStrategy> apply() {
        Map<String, KeyStrategy> strategies = new HashMap<>();

        // === 输入字段（ReplaceStrategy） ===
        strategies.put("userMessage", new ReplaceStrategy());       // 用户原始消息
        strategies.put("conversationId", new ReplaceStrategy());    // 会话ID
        strategies.put("userId", new ReplaceStrategy());            // 用户ID
        strategies.put("historyMessages", new ReplaceStrategy());   // 历史对话消息列表（仅Planner使用）

        // === Planner 输出字段 ===
        strategies.put("executionPlan", new ReplaceStrategy());     // 执行计划（JSON字符串，LLM原始输出）
        strategies.put("activeWorkers", new ReplaceStrategy());     // 需要执行的Worker名称列表 List<String>
        strategies.put("taskDescriptions", new ReplaceStrategy());  // 【新增】Planner为每个Worker定制的任务描述 Map<String, String>
        strategies.put("degraded", new ReplaceStrategy());          // 【新增】降级标记，Planner解析失败时为true，ChatWorker据此决定是否注入历史消息

        // === Worker 输出字段（AppendStrategy：并行Worker结果追加） ===
        strategies.put("workerResults", new AppendStrategy());      // 所有Worker的结果列表
        strategies.put("articleCards", new AppendStrategy());       // 文章卡片列表（多Worker合并）

        // === 中间传递字段 ===
        strategies.put("searchResult", new ReplaceStrategy());      // search结果（供analysis依赖读取）

        // === 最终输出 ===
        strategies.put("finalReply", new ReplaceStrategy());        // 最终回复文本

        return strategies;
    }
}
