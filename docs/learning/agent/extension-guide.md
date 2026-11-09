# 扩展指南：当前可以做什么

## 当前项目状态

| 节点 | 状态 | 说明 |
|---|---|---|
| `planner` | ✅ 完整 | LLM 决策调用哪些 Worker |
| `dispatcher` | ✅ 完整 | 并行分发任务 |
| `search_worker` | ✅ 完整 | RAG + 按需联网 |
| `chat_worker` | ✅ 完整 | 多轮对话 |
| `synthesizer` | ✅ 完整 | 多 Worker 结果汇总 |
| `analysis_worker` | ❌ 占位 | 返回固定字符串 |
| `writing_worker` | ❌ 占位 | 返回固定字符串 |

---

## 扩展方向一：实现 writing_worker

**文件**：`app/graph/nodes/writing_worker.py`（从 `builder.py` 里的占位函数独立出来）

**实现思路**：

```
1. 从 state["task_descriptions"]["writing"] 拿写作任务
2. 从 state["worker_results"] 里找 search worker 的结果作为已有参考资料
3. LLM bind_tools([search_articles, web_search])
4. 循环最多 2 轮工具调用（LLM 决定要不要补充资料）
5. 最终生成文章内容
```

**tool_map 和 search_worker 完全一样**，可以直接复用。

**参考文档**：`docs/tool-refactor-guide.md` 第 5 节。

---

## 扩展方向二：实现 analysis_worker

**文件**：`app/graph/nodes/analysis_worker.py`

**实现思路**：

```
1. 从 state["task_descriptions"]["analysis"] 拿分析任务
2. 从 state["worker_results"] 里找 search worker 的结果作为数据来源
3. 纯 LLM 推理，不需要 tool（数据已经在 state 里）
4. system prompt 强调：结构化输出、对比表格、找规律
```

**注意**：`analysis` 通常和 `search` 一起被 planner 激活，search 的结果会先进入 `worker_results`，analysis 可以直接用。但 LangGraph 并行执行 worker，`worker_results` 里 search 的结果不保证先于 analysis 到达。

解决方案：让 analysis 也能自己调 `search_articles` tool，不依赖 search worker 的结果。

---

## 扩展方向三：新增 Worker

**场景举例**：
- `resume_worker`：简历分析、优化建议
- `interview_worker`：模拟面试、答题解析
- `salary_worker`：薪资对比分析

**步骤**：

1. 新建 `app/graph/nodes/xxx_worker.py`，实现 `xxx_worker_node(state) -> dict`
2. 在 `app/graph/state.py` 的 `active_workers` 可选值里没有限制，planner 的 prompt 里加上新 worker 的说明
3. 在 `app/graph/builder.py` 里注册：
   ```python
   graph.add_node("xxx_worker", xxx_worker_node)
   graph.add_edge("xxx_worker", "synthesizer")
   ```
4. 更新 `app/graph/nodes/planner.py` 里的 `PLANNER_SYSTEM_PROMPT`，在 `【可用的Worker】` 里加一行描述

---

## 扩展方向四：新增 Tool

**场景举例**：
- `get_user_resume`：查询用户已上传的简历
- `get_job_recommendations`：获取平台推荐职位
- `calculate_salary`：薪资计算器

**步骤**：

1. 在 `app/tools/` 下新建文件或在现有文件里追加：
   ```python
   @tool
   def get_job_recommendations(keywords: str) -> str:
       """
       获取平台推荐的相关职位。
       适合：用户询问求职方向、岗位匹配时使用。

       Args:
           keywords: 职位关键词，如"Java后端"、"产品经理"
       """
       ...
   ```

2. 在需要用到的 worker 里 import，加入 `bind_tools` 列表和 `tool_map`：
   ```python
   from app.tools.job_tool import get_job_recommendations

   tool_map = {
       "web_search": web_search,
       "search_articles": search_articles,
       "get_job_recommendations": get_job_recommendations,  # 加这行
   }
   llm_with_tools = llm.bind_tools([web_search, search_articles, get_job_recommendations])
   ```

3. **更新 system prompt**，告诉 LLM 什么情况下用这个工具。

---

## 扩展方向五：streaming 流式输出

**当前**：`main.py` 里的 `/chat` 接口是普通同步接口，等全部生成完才返回。

**目标**：边生成边返回，前端实时显示文字。

**思路**：

```python
# main.py
from fastapi.responses import StreamingResponse

@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    async def generate():
        async for chunk in graph.astream(initial_state):
            # 从 synthesizer 节点拿到输出片段
            if "final_reply" in chunk.get("synthesizer", {}):
                yield chunk["synthesizer"]["final_reply"]
    
    return StreamingResponse(generate(), media_type="text/event-stream")
```

LangGraph 支持 `astream`（异步流式），LangChain 的 LLM 也支持 `astream`。

---

## 扩展方向六：对话历史持久化

**当前**：`history_messages` 由前端（Java 后端）传入，Python agent 本身不存储。

**如果需要 Python 端缓存**：

`app/clients/redis_client.py` 已经实现了 Redis 客户端，可以用：

```python
import json
from app.clients.redis_client import RedisClient

redis = RedisClient()

def save_history(conversation_id: int, messages: list[dict]):
    redis.set(f"chat:{conversation_id}", json.dumps(messages), ex=3600)

def load_history(conversation_id: int) -> list[dict]:
    data = redis.get(f"chat:{conversation_id}")
    return json.loads(data) if data else []
```

---

## 优先级建议

| 优先级 | 扩展项 | 原因 |
|---|---|---|
| 高 | 实现 `writing_worker` | 占位节点影响写作类请求质量 |
| 高 | 实现 `analysis_worker` | 占位节点影响分析类请求质量 |
| 中 | streaming 流式输出 | 用户体验明显提升 |
| 中 | 新增业务 tool | 按需，根据产品需求决定 |
| 低 | 新增 Worker | 现有 4 个 worker 覆盖大多数场景 |
