# Agent Harness 工程优化方案

> 基于 Claude Code Harness 四层架构思想，结合本项目现状，提出下一阶段优化方案。

## 一、现状与 Harness 架构对标

| Harness 层 | Claude Code | 本项目现状 | 差距 |
|---|---|---|---|
| L1 用户交互 | 57+命令 + 全局Rules | 无命令层，Planner 理解意图 | 无结构化入口 |
| L2 智能层 | 25 Agent + 108 Skill | 4 Worker + 固定 System Prompt | 无 Skill 按需加载 |
| L3 自动化层 | Hooks + 权限网关 + 熔断 | 无 | **完全缺失** |
| L4 学习层 | CLAUDE.md + 跨会话学习 | Memory Service（画像+事件记忆） | 已实现，可增强 |

**结论**：L2 和 L4 已有基础，L3 自动化层完全缺失，是最大短板。

---

## 二、优化方案一：Tool 执行守卫（L3 自动化层）

### 2.1 问题

当前 `run_tool_agent()` 中 Tool 调用没有任何校验，LLM 决定调什么就调什么：
- 无参数校验（如 web_search 传入超长 query）
- 无结果截断（Tool 返回超长内容直接塞进上下文，浪费 Token）
- 无异常处理（Tool 抛异常直接中断整个流程）

> 注意：现有的 `max_rounds` 限制的是总调用轮数，不是失败次数。熔断机制对本项目 Tool 数量少（3个）且 max_rounds=2 的场景意义不大，不引入。

### 2.2 方案：参数校验 + 结果截断 + 异常兜底

```
LLM 决定调用 Tool
    ↓
参数校验（拦截明显不合理的参数）
    ↓ 通过
执行 Tool（try-catch 兜底）
    ↓
结果截断（防止超长结果撑爆上下文）
    ↓
结果返回给 LLM
```

### 2.3 直接修改 tool_executor.py

不需要新增文件，直接在现有的 `run_tool_agent()` 中增强 Tool 调用部分：

```python
MAX_RESULT_LENGTH = 3000  # 单次 Tool 返回最大字符数

def _validate_args(tool_name: str, args: dict) -> tuple[bool, str]:
    """参数校验"""
    if tool_name == "web_search" and len(args.get("query", "")) > 200:
        return False, "搜索查询过长，请精简后重试"
    return True, ""

def _truncate_result(result: str) -> str:
    """结果截断"""
    if len(result) > MAX_RESULT_LENGTH:
        return result[:MAX_RESULT_LENGTH] + "\n...[结果已截断]"
    return result

# 修改 tool_executor.py 中的 Tool 调用部分
for tc in response.tool_calls:
    fn = tool_map.get(tc["name"])
    if fn:
        allowed, reason = _validate_args(tc["name"], tc["args"])
        if not allowed:
            result = reason
        else:
            try:
                result = await fn.ainvoke(tc["args"])
                result = _truncate_result(str(result))
            except Exception as e:
                result = f"工具执行失败: {e}"
    else:
        result = f"工具 {tc['name']} 不存在"
    messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))
```

---

## 三、优化方案二：Self-Correction 自纠错

### 3.1 问题

当前 Worker 执行完直接把结果交给 Synthesizer，没有质量评估环节。如果 Worker 回答偏题或信息不完整，最终回复质量无法保证。

### 3.2 方案：在 Synthesizer 前加 Review 环节

```
Worker 执行完毕
    ↓
Review（评估回答质量，0-1 打分）
    ↓ score >= 0.7
Synthesizer 汇总
    ↓ score < 0.7（最多重试1次）
Worker 带反馈重新执行
```

### 3.3 实现

```python
# 新增文件：python-agent/app/services/review.py

REVIEW_PROMPT = """评估以下回答的质量。

【用户问题】
{question}

【Agent 回答】
{answer}

请以 JSON 格式返回：
{{"score": 0.0-1.0, "feedback": "如果分数低于0.7，说明具体问题"}}
"""

class ReviewResult(BaseModel):
    score: float = Field(description="质量评分 0-1")
    feedback: str = Field(default="", description="改进建议")

async def review_answer(question: str, answer: str) -> ReviewResult:
    """评估回答质量"""
    llm = get_llm(temperature=0)
    structured_llm = llm.with_structured_output(ReviewResult, method="json_mode")
    result = await structured_llm.ainvoke([
        HumanMessage(content=REVIEW_PROMPT.format(
            question=question, answer=answer
        ))
    ])
    return result
```

### 3.4 集成位置

在 `synthesizer_node` 中，对每个 Worker 结果做质量检查：

```python
# synthesizer.py 中增加
for wr in worker_results:
    review = await review_answer(user_message, wr["result"])
    if review.score < 0.7:
        log.warning(
            "Worker %s 质量不达标(%.1f): %s",
            wr["worker_name"], review.score, review.feedback
        )
        # 可选：标记低质量结果，Synthesizer 汇总时降权或忽略
        wr["quality_score"] = review.score
        wr["quality_feedback"] = review.feedback
```

> 注意：Self-Correction 会增加一次 LLM 调用，需要权衡延迟和质量。建议只对 search 和 analysis Worker 启用，chat 不需要。

---

## 四、优化方案三：Planner 降级熔断

### 4.1 问题

当前 Planner 解析失败时降级到 chat，但没有追踪失败频率。如果 Planner 持续失败（如模型抽风），会一直降级，用户体验差。

### 4.2 方案

```python
# planner.py 中增加熔断逻辑

PLANNER_MAX_FAILURES = 5  # 连续失败阈值
_planner_failure_count = 0

async def planner_node(state: AgentState) -> dict:
    global _planner_failure_count

    # 熔断：连续失败过多，直接走 chat，不再尝试 Planner
    if _planner_failure_count >= PLANNER_MAX_FAILURES:
        log.warning("Planner 熔断中，直接走 chat")
        return {
            "active_workers": ["chat"],
            "task_descriptions": {"chat": state["user_message"]}
        }

    try:
        # ... 正常 Planner 逻辑 ...
        _planner_failure_count = 0  # 成功则重置
        return result
    except Exception as e:
        _planner_failure_count += 1
        log.warning("Planner 失败(%d/%d): %s",
                     _planner_failure_count, PLANNER_MAX_FAILURES, e)
        return {
            "active_workers": ["chat"],
            "task_descriptions": {"chat": state["user_message"]}
        }
```

---

## 五、优先级建议

| 方案 | 复杂度 | 收益 | 面试价值 | 建议 |
|---|---|---|---|---|
| Tool 参数校验+结果截断 | 低 | 高（健壮性） | ⭐⭐⭐⭐ | **第一个做** |
| Planner 熔断 | 低 | 中（稳定性） | ⭐⭐⭐ | 第二个做 |
| Self-Correction | 中 | 高（质量） | ⭐⭐⭐⭐⭐ | 第三个做 |

Tool 执行守卫最简单，改动最小（只改 tool_executor.py + 新增一个文件），但直接对标 Claude Code 的 Harness L3 层，面试讲起来很有说服力。
