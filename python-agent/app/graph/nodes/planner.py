"""
Planner 节点
对应 Java: PlannerNode.java
"""
import json

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field
from datetime import datetime

from app.services.logging_config import get_logger, truncate

log = get_logger(__name__)

from app.config import settings, get_llm
from app.graph.state import AgentState
from app.services.observability import trace_node
from app.skills.registry import skill_registry

class PlannerOutput(BaseModel):
    """Planner 输出结构"""
    active_workers: list[str] = Field(description="需要执行的Worker列表，可选: search, analysis, writing, chat")
    task_descriptions: dict[str, str] = Field(description="每个Worker的任务描述")
    is_degraded: bool = Field(default=False, description="是否降级到单Agent模式")
    required_skills: list[str] = Field(default_factory=list, description="需要使用的技能列表")

PLANNER_MAX_FAILURES = 5  # 连续失败阈值
_planner_failure_count = 0

PLANNER_SYSTEM_PROMPT = """你是一个智能任务规划器。根据用户消息，分析意图并决定需要调用哪些专家Worker。

【可用的Worker】
- search: 搜索专家，负责检索平台文章、联网搜索实时信息
- analysis: 分析专家，负责数据分析、对比分析、趋势分析
- writing: 写作专家，负责文章撰写、内容创作、文案优化
- chat: 聊天专家，负责日常对话、简单问答、闲聊

【可用的Skill（领域知识包，按需选用）】
{skill_catalog}

【规划原则】
1. 简单问候/闲聊 → 只用 chat
2. 需要搜索信息 → 用 search
3. 需要分析数据 → 用 analysis
4. 需要写作创作 → 用 writing
5. 复杂任务可以组合多个Worker

【当前日期】{current_date}

请严格以 JSON 格式返回，不要输出其他内容：
{{"active_workers": ["worker1"], "task_descriptions": {{"worker1": "任务描述"}}, "required_skills": ["skill_name"]}}
"""

@trace_node("planner")
async def planner_node(state: AgentState) -> dict:
    """
    规划节点：分析用户意图，决定调用哪些 Worker
    
    对应 Java: PlannerNode.apply()
    """
    llm = get_llm()

    log.info("[planner] 开始规划 | user_msg=%r | history_count=%d",
             (state.get("user_message") or "")[:200], len(state.get("history_messages", [])))

    messages = [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT.format(
            skill_catalog=skill_registry.get_catalog(),
            current_date=datetime.now().strftime("%Y-%m-%d")
        )),
    ]
    
    # 注入历史消息，让 planner 理解上下文（如"把刚才的内容写成文章"）
    for msg in state.get("history_messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
        elif role == "system":
            messages.append(SystemMessage(content=content))
    
    messages.append(HumanMessage(content=state["user_message"]))
    
    try:
        # 用 function_calling 方式强制结构化输出，DeepSeek 对 tool call 支持最好
        structured_llm = llm.with_structured_output(PlannerOutput, method="function_calling")
        result = await structured_llm.ainvoke(messages)

        log.info("[planner] 规划成功 | workers=%s | skills=%s | tasks=%s",
                 result.active_workers, result.required_skills,
                 {k: (v or "")[:80] for k, v in result.task_descriptions.items()})

        return {
            "active_workers": result.active_workers,
            "task_descriptions": result.task_descriptions,
            "required_skills":  result.required_skills,
        }
    except Exception as e:
        # 诊断用：输出裸 LLM 看它真实返回了啥
        try:
            raw = await llm.ainvoke(messages)
            log.warning("Planner 解析失败: %s | 裸响应 content=%r | tool_calls=%r",
                        e, (raw.content or "")[:500],
                        getattr(raw, "tool_calls", None))
        except Exception as ee:
            log.warning("Planner 解析失败: %s | 裸响应也失败: %s", e, ee)

        # 降级：按关键字兜底决策，比一股脑走 chat 好
        text = state["user_message"] or ""
        if any(k in text for k in ["搜索", "查找", "查询", "找一下", "找找", "搜一下"]):
            return {
                "active_workers": ["search"],
                "task_descriptions": {"search": text},
                "required_skills": [],
            }
        if any(k in text for k in ["写", "生成文章", "起草", "草稿"]):
            return {
                "active_workers": ["writing"],
                "task_descriptions": {"writing": text},
                "required_skills": [],
            }
        return {
            "active_workers": ["chat"],
            "task_descriptions": {"chat": text},
            "required_skills": [],
        }
