# Main 的四种动作与工具执行

Main 每轮只返回一个 `MainDecision`：

| action | 必须携带的执行请求 | 下一节点 |
| --- | --- | --- |
| `call_tool` | `tool_call` | `execute_tool` |
| `delegate` | `plan`、`delegation_reason` | `main_delegate` |
| `write_draft` | `draft_request` | 写作审批子图 |
| `answer` | `user_reply` | `final_gate` |

请求互斥。例如 `write_draft` 不能同时附带 `tool_call`。先检索再写作要经过两轮决策，避免用尚未完成的检索结果启动写作。

```json
{
  "action": "call_tool",
  "tool_call": {
    "name": "search_knowledge",
    "task_id": "research",
    "args": {
      "query": "查找平台中关于 Agent 工具调用的文章",
      "allow_web": false,
      "filters": {},
      "search_query": "Agent 工具调用"
    }
  }
}
```

示例省略了其他默认字段。`MainToolCall` 按 `name` 区分参数 Schema，禁止未知工具、额外参数和模型指定权限。文章／用户 ID 限定为正的有符号 64 位整数，超限在 Main 格式校验阶段反馈修正，避免进入 RPC 后才报错。`task_id` 可省略，服务端生成 `tool_<round>`；后续依赖引用执行结果中的真实任务 ID。

## Main 工具目录

| 工具 | 参数 | 使用的既有业务实现 |
| --- | --- | --- |
| `search_knowledge` | `query`，可选 `allow_web/article_ids/filters/search_query` | 完整 RAG：改写、混合召回、公开性核验、重排、引用；可请求联网补充 |
| `web_search` | `query`，最多 128 字符 | 相同网页检索与引用流程，跳过平台召回 |
| `read_webpage` | `urls`，最多 3 条 | 已知公开 URL 正文读取，保留正文／摘要范围标记 |
| `read_memory` | `query` | 当前用户的有效已确认决策 |
| `read_draft` | 可选 `article_id/keyword` | 当前用户数据库草稿；不提供 ID 时查找列表 |
| `read_editor` | `part=document/selection` | 本轮请求上传的编辑器快照；不会主动向浏览器取最新内容 |
| `get_article_comments` | `article_id`，可选 `limit` | 既有公开评论工具 |
| `get_user_articles` | `user_id`，可选 `page/page_size` | 既有公开文章列表工具，user_id 是公开查询对象 |
| `get_trending_topics` | 可选 `limit` | 既有热门话题工具 |

`ToolRegistry.main_tool` 是 Main 的执行白名单，`/tools` 返回该目录。历史 LangChain 工具包装仍供既有只读工具循环使用；原始关键词／向量搜索包装不作为 Main 的第二套 RAG。MCP 动态工具不会自动获得此白名单的权限，也不能覆盖 Main 的同名本地工具。

## 执行与失败反馈

1. Pydantic 校验动作和对应工具参数，后端预检任务、依赖和当前权限。可修正错误走已有的 Main 决策修正，最多一次，未通过前不执行工具或提交记忆变更。
2. 编译成服务端 `ExecutionTask`，保留 `tool_name/tool_args` 并校验与实际执行参数一致。检索沿用 `kind=search` 以保留证据语义；普通公开查询使用 `kind=tool`。
3. `execute_tool` 重新检查当前权限、执行代次和取消状态，查注册表并调用业务实现，不再让模型选择工具。每次执行有超时。
4. 结果进入 `task_results` 与 `observations`，Main 依据结果决定补检索、委派、写作或回答。任务数、轮数、失败次数和相同策略重复限制继续生效。
5. 暂时性服务失败记录安全错误码，返回 Main；取消、执行代次失效和权限拒绝继续向上传播，不作为参数错误自动重试。

评论、文章列表和热门话题是原始工具数据，不自行赋予正文引用。交付核验可以用 `execution_facts.public_tool_results` 核对准确转述；评论本身不能证明其中外部说法为真。工具资料转述未通过时，局部修正后仍须再次核验，不能仅凭修正调用成功就标记为通过。

这三个公开查询的成功结果会进入有大小与数量限制的恢复投影，失败后用户“继续”时可由 Main 显式选择复用。未知工具、失败结果、私有读取和写入产物不会因此获得复用资格。公开查询与网页资料沿用一天的复用时限，多次继续保留最初来源时间；这些结果是此前读取的快照，实时问题仍应重新查询。

草稿审批／保存、子任务依赖调度和记忆后台入队仍由原有业务流程控制。来源补检索也编译成相同工具请求，复用 `execute_tool`。

编辑器中的“帮我写个摘要”先调用 `read_editor(part=document)`，再通过 `answer.user_reply` 交付摘要；需要填入摘要栏时，附带 `editor_edits`，目标为 `summary`，最多 500 字符。其他目标为 `title/body/selection`。建议绑定本轮读取任务和快照，前端确认后应用，支持撤销；摘要在生成后或应用后继续修改时，不覆盖用户的新内容。首次尚未保存的文章同样可用，不创建数据库草稿。`answer` 的 `artifacts` 必须为空列表，不能将最终摘要放入执行产物字段。动作整体校验失败时，诊断仅保留动作名及字段类型、长度，不记录摘要或正文。

内容核验同样接收本轮成功读取且快照 ID 匹配的编辑器原文，使用 `user_content` 分类检查摘要、转述和润色的忠实性，不要求用户文档具有公开网页引用。未读取、读取失败、旧快照或未读取的全文不会进入该核验范围；原文也不证明外部事实客观正确，外部事实仍受原有依据要求约束。HTML 超出快照额度但纯文本仍在额度内时上传完整纯文本，不让格式标签挤掉正文；这种快照可以写摘要，但 `body_replaceable=false` 禁止整篇替换。纯文本仍超限或含未读取媒体时保留不完整标记。

## 旧断点

模型 Schema 已移除 `retrieve/retrieval`。图中保留 `main_retrieve` 的恢复别名，供部署前已保存的断点继续执行；旧服务端任务在执行入口转换为工具请求。该别名调用同一个实现，新 Main 决策不会路由到它。交付补检索的受限 `DeliveryLookup` 暂时保留内部检索参数结构，编译后仍通过新工具执行路径。

## 验证

`tests/test_main_tools.py` 覆盖实际图路由、参数修正、权限、取消、服务异常、工具名冲突和网页检索来源隔离；`tests/test_main_tool_regressions.py` 覆盖工具回答修正后的二次核验、公开查询的继续／过期／私有隔离及 ID 上限。既有 Main、RAG、记忆、私有草稿、编辑器、补检索、审批与流式测试继续验证原有边界。

全量离线回归：

```powershell
python-agent/.venv/Scripts/python.exe scripts/run-agent-offline-tests.py
```

该脚本在导入应用前禁止网络与 DNS；不调用真实模型或业务服务。
