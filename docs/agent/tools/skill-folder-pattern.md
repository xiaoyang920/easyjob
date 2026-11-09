# Skill 文件夹模式（Semantic Kernel 风格）

## 一、核心思想

每个 Skill 是一个**独立文件夹**，包含三个文件：

```
app/skills/
  rag_search/
    skill.md        ← LLM 读这个（prompt + 描述）
    config.json     ← 参数配置（工具列表、轮数等）
    execute.py      ← Python 执行逻辑
  writing/
    skill.md
    config.json
    execute.py
    templates/      ← 可选：资源目录
      tech-blog.md
  translate/        ← 新增 Skill，不改任何 agent 代码
    skill.md
    config.json
    execute.py
```

**最大特点**：
- `skill.md` 由 LLM 读取，**prompt 和代码完全分离**
- 新增/删除 Skill 只操作文件夹，**不改 agent 代码**
- 非开发者也能通过修改 `skill.md` 调整 Skill 行为
- Loader 在启动时自动扫描目录发现所有 Skill

---

## 二、与普通 Tool 和 my之前方案的区别

| 维度 | @tool 函数 | Python 单文件 Skill | **文件夹 Skill（本文）** |
|------|-----------|-------------------|----------------------|
| 粒度 | 原子操作（一个函数） | 完整工作流 | 完整工作流 |
| prompt 位置 | 代码里的字符串 | 代码里的字符串 | **独立 md 文件** |
| 修改 prompt | 改 .py | 改 .py | **只改 .md** |
| 新增能力 | 加函数 | 加 .py + 改注册 | **加文件夹，不改其他** |
| 资源文件 | 不支持 | 不支持 | **支持（templates/ 等）** |
| 非技术人员参与 | ❌ | ❌ | ✅ |

---

## 三、文件规范

### 3.1 `skill.md` — LLM 的认知来源

LLM 在执行该 Skill 时，`skill.md` 的内容会作为 `system_prompt` 注入。
**两阶段读取**：
- **第一阶段（Planner 选择）**：只读 `## 摘要` 节的一句话
- **第二阶段（执行时）**：读完整的 `skill.md` 作为 system_prompt

```markdown
# [Skill 名称]

## 摘要
一句话描述这个 Skill 能做什么（Planner 第一阶段只看这里，要简短精确）

## 能力描述
详细描述：
- 这个 Skill 会执行哪些步骤
- 使用了哪些工具
- 输出的格式和内容

## 适用场景
- 用户问 xxx 时使用
- 需要 yyy 时使用

## 不适用场景
- 不需要搜索的纯闲聊（用 chat）
- 需要实时数据（用 web_search_skill）

## 输出要求
- 格式要求（如 Markdown、JSON 等）
- 内容要求（如引用来源、数据支撑等）
- 长度要求
```

### 3.2 `config.json` — 参数配置

```json
{
  "name": "skill_name",
  "tools": ["web_search", "search_articles"],
  "max_rounds": 2,
  "supports_interrupt": false,
  "description": "可选的额外说明（不注入 LLM，给开发者看）"
}
```

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 唯一标识，Planner 输出这个名字选中该 Skill |
| `tools` | list | ✅ | 依赖的 Tool 名称（引用全局 TOOL_REGISTRY） |
| `max_rounds` | int | ❌ | 最大工具调用轮数，默认 2 |
| `supports_interrupt` | bool | ❌ | 是否支持 interrupt，默认 false |

### 3.3 `execute.py` — 执行逻辑

```python
# 固定签名，由 loader 调用

async def execute(task_input: str, history: list[dict], context: dict) -> dict:
    """
    :param task_input: Planner 分配的任务描述
    :param history: 会话历史
    :param context: 运行时上下文，包含：
        - context["tools"]       : 已解析的 Tool 实例列表
        - context["skill_prompt"]: skill.md 的完整内容
        - context["config"]      : config.json 的内容
        - context["skill_dir"]   : 该 Skill 的目录路径（Path 对象）
    :return: 至少包含 "result" 字段的 dict，可附加旁路数据
    """
    ...
    return {
        "result": "...",           # 必须
        "article_cards": [...],    # 可选旁路数据
    }
```

**关键约定**：
- `context["skill_prompt"]` 是 `skill.md` 的完整内容，直接传给 `run_tool_agent` 的 `system_prompt`
- `execute.py` **不导入 TOOL**，工具实例由 loader 注入到 `context["tools"]`
- `execute.py` **不读取 config.json**，配置由 loader 注入到 `context["config"]`

---

## 四、完整 Skill 示例

### 4.1 RAG 检索

```
app/skills/rag_search/
├── skill.md
├── config.json
└── execute.py
```

**skill.md**
```markdown
# RAG 检索技能

## 摘要
在平台知识库中检索技术文章、面试题、职场经验，支持语义搜索和关键词搜索

## 能力描述
- 自动执行查询改写（语义扩展 + 关键词提取）
- 向量 KNN 检索 + 关键词全文检索双路召回
- Reranker 精排，保证结果相关性
- 如果平台文章不足，自动调用 web_search 联网补充

## 适用场景
- 用户询问技术知识点、最佳实践、配置方法
- 查找平台已有的教程、经验分享、面试题
- 需要引用权威资料回答的问题

## 不适用场景
- 纯闲聊、问候（用 chat）
- 需要最新新闻、实时股价（用 web_search_skill）
- 需要撰写文章（用 writing）

## 输出要求
- 优先引用 RAG 检索到的平台文章，标注文章标题
- 如检索结果为空或不相关，主动告知并尝试联网搜索
- 回复简洁有条理，避免重复内容
```

**config.json**
```json
{
  "name": "rag_search",
  "tools": ["web_search", "search_articles", "search_articles_by_knn"],
  "max_rounds": 2,
  "supports_interrupt": false
}
```

**execute.py**
```python
from datetime import datetime


async def execute(task_input: str, history: list[dict], context: dict) -> dict:
    from app.services.query_rewrite import QueryRewriteService
    from app.services.reranker import RerankerService
    from app.clients.es_client import EsVectorStore, EsComponent
    from app.tools.web_search import do_search
    from app.graph.tool_executor import run_tool_agent
    from app.config import settings

    # 1. Query Rewriting
    rewrite_result = await QueryRewriteService().rewrite(task_input, history)

    # 2. 多路粗检索
    doc_map = {}
    es_vector = EsVectorStore()
    es_keyword = EsComponent()

    for sq in rewrite_result.get("semantic_queries", []):
        try:
            chunks = await es_vector.search(sq, settings.COARSE_TOP_K, settings.COARSE_SIMILARITY_THRESHOLD)
            for c in chunks:
                doc_map.setdefault(f"{c['article_id']}_{c['chunk_index']}", c)
        except Exception:
            pass

    for kw in rewrite_result.get("keywords", []):
        try:
            articles = await es_keyword.search(kw, page_size=5)
            for a in articles:
                doc_map.setdefault(f"keyword_{a['article_id']}", {
                    "article_id": a["article_id"], "title": a["title"],
                    "content": a.get("summary", ""), "chunk_index": 0,
                })
        except Exception:
            pass

    # 联网兜底（ES 全空时）
    if not doc_map:
        queries = rewrite_result.get("semantic_queries") or rewrite_result.get("keywords", [])
        if queries:
            try:
                for i, item in enumerate(await do_search(queries[0], size=5)):
                    doc_map[f"web_{i}"] = {
                        "article_id": f"web_{i}", "title": item.get("title", ""),
                        "content": item.get("content", ""), "chunk_index": i, "score": 0.1,
                    }
            except Exception:
                pass

    candidates = list(doc_map.values())

    # 3. Reranker 精排
    ranked = RerankerService().rerank(task_input, candidates) if candidates else []

    # 4. 旁路：构建文章卡片
    article_cards = [
        {
            "articleId": str(r.get("article_id", "")),
            "title": r.get("title", ""),
            "coverImage": r.get("cover", ""),
            "authorName": r.get("author_name", ""),
            "viewCount": r.get("view_count", 0),
            "likeCount": r.get("like_count", 0),
        }
        for r in ranked
        if str(r.get("article_id", "")) and not str(r.get("article_id", "")).startswith("web_")
    ]

    # 5. 构建 RAG 上下文
    if ranked:
        rag_context = "\n\n".join(
            f"【{i + 1}. {doc.get('title', '无标题')}】\n{doc.get('content', '')[:500]}"
            for i, doc in enumerate(ranked[:5])
        )
    else:
        rag_context = "未找到相关资料"

    # 6. LLM + Tool（使用 skill.md 作为 system_prompt）
    reply = await run_tool_agent(
        system_prompt=context["skill_prompt"] + f"\n\n【当前日期】{datetime.now().strftime('%Y-%m-%d')}",
        user_input=f"任务：{task_input}\n\nRAG 参考资料：\n{rag_context}",
        tools=context["tools"],
        max_rounds=context["config"]["max_rounds"],
    )

    return {"result": reply, "article_cards": article_cards}
```

### 4.2 写作（含 interrupt 和资源文件）

```
app/skills/writing/
├── skill.md
├── config.json
├── execute.py
└── templates/
    ├── tech-blog.md      ← 技术博客模板
    └── tutorial.md       ← 教程模板
```

**skill.md**
```markdown
# 写作技能

## 摘要
撰写技术文章、博客、教程，生成草稿后需要用户审核确认

## 能力描述
- 根据主题搜索参考资料（平台文章 + 联网）
- 生成结构完整的文章草稿（Markdown 格式）
- 支持用户审核：approve 发布 / reject 取消 / 文字修改意见重新生成

## 输出格式
完整的 Markdown 文章，包含：
- # 标题
- 正文（分节，每节有标题）
- 代码示例（如适用）
- 总结
```

**config.json**
```json
{
  "name": "writing",
  "tools": ["web_search", "search_articles", "search_articles_by_knn"],
  "max_rounds": 2,
  "supports_interrupt": true
}
```

**execute.py**
```python
async def execute(task_input: str, history: list[dict], context: dict) -> dict:
    from langgraph.types import interrupt
    from app.graph.tool_executor import run_tool_agent

    # 读取模板（资源文件）
    skill_dir = context["skill_dir"]
    template_path = skill_dir / "templates" / "tech-blog.md"
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""

    system_prompt = context["skill_prompt"]
    if template:
        system_prompt += f"\n\n## 参考模板\n{template}"

    # 1. 生成草稿
    draft = await run_tool_agent(
        system_prompt=system_prompt,
        user_input=task_input,
        tools=context["tools"],
        max_rounds=context["config"]["max_rounds"],
    )

    # 2. interrupt 等用户确认
    user_decision = interrupt({
        "action": "confirm_publish",
        "draft": draft,
        "message": "草稿已生成，是否发布？",
    })

    # 3. 处理决策
    if user_decision == "approve":
        return {"result": draft}
    elif user_decision == "reject":
        return {"result": "用户取消了发布"}
    else:
        revised = await run_tool_agent(
            system_prompt=system_prompt,
            user_input=f"原草稿：\n{draft}\n\n用户修改意见：{user_decision}\n\n请重新生成。",
            tools=context["tools"],
            max_rounds=context["config"]["max_rounds"],
        )
        return {"result": revised}
```

### 4.3 最简单的 Skill：翻译（新增示例）

```
app/skills/translate/
├── skill.md
├── config.json
└── execute.py
```

**skill.md**
```markdown
# 翻译技能

## 摘要
中英文互译、技术文档翻译，保持专业术语准确

## 能力描述
- 中文 ↔ 英文互译
- 技术术语使用业界通用翻译
- 不确定的术语通过 web_search 查询标准译法

## 适用场景
- 用户要求翻译一段文字
- 技术文档国际化
```

**config.json**
```json
{
  "name": "translate",
  "tools": ["web_search"],
  "max_rounds": 1
}
```

**execute.py**
```python
async def execute(task_input: str, history: list[dict], context: dict) -> dict:
    from app.graph.tool_executor import run_tool_agent

    reply = await run_tool_agent(
        system_prompt=context["skill_prompt"],
        user_input=task_input,
        tools=context["tools"],
        max_rounds=context["config"]["max_rounds"],
    )
    return {"result": reply}
```

**把这个文件夹放进去，重启服务，不改任何其他代码，翻译能力自动生效。**

---

## 五、Skill Loader（自动发现引擎）

```python
# app/skills/loader.py

import json
import importlib.util
from pathlib import Path

from app.tools.web_search import web_search
from app.tools.article_tool import search_articles, search_articles_by_knn

# 全局 Tool 注册表：Skill 的 config.json 里的 "tools" 列表引用这里的 key
TOOL_REGISTRY = {
    "web_search": web_search,
    "search_articles": search_articles,
    "search_articles_by_knn": search_articles_by_knn,
}


class SkillLoader:
    """
    Skill 文件夹自动发现引擎

    扫描 app/skills/ 目录，找到所有包含 skill.md + config.json + execute.py 的文件夹，
    自动加载为可用 Skill。
    """

    def __init__(self):
        self._skills: dict[str, dict] = {}

    def discover(self):
        """启动时调用，扫描目录加载所有 Skill"""
        skills_dir = Path(__file__).parent

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            config_path = skill_dir / "config.json"
            md_path = skill_dir / "skill.md"
            execute_path = skill_dir / "execute.py"

            # 三个核心文件都存在才算有效 Skill
            if not all([config_path.exists(), md_path.exists(), execute_path.exists()]):
                continue

            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                skill_prompt = md_path.read_text(encoding="utf-8")

                # 动态加载 execute.py
                spec = importlib.util.spec_from_file_location(
                    f"skill_{config['name']}", execute_path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                self._skills[config["name"]] = {
                    "config": config,
                    "skill_prompt": skill_prompt,
                    "module": module,
                    "skill_dir": skill_dir,
                    "tools": [
                        TOOL_REGISTRY[t]
                        for t in config.get("tools", [])
                        if t in TOOL_REGISTRY
                    ],
                    "summary": self._extract_summary(skill_prompt),
                }

            except Exception as e:
                print(f"[SkillLoader] 加载 {skill_dir.name} 失败: {e}")

    @staticmethod
    def _extract_summary(md_content: str) -> str:
        """从 skill.md 的 ## 摘要 节提取一句话描述（Planner 第一阶段用）"""
        lines = md_content.splitlines()
        in_summary = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") and "摘要" in stripped:
                in_summary = True
                continue
            if in_summary:
                if stripped.startswith("#"):
                    break
                if stripped:
                    return stripped
        return ""

    def get_summaries(self) -> str:
        """
        生成 Planner 第一阶段使用的摘要列表

        输出格式：
        - rag_search: 在平台知识库中检索技术文章...
        - chat: 日常对话...
        """
        return "\n".join(
            f"- {name}: {skill['summary']}"
            for name, skill in self._skills.items()
        )

    def list_names(self) -> list[str]:
        """返回所有已发现的 Skill 名"""
        return list(self._skills.keys())

    async def run_skill(self, name: str, task_input: str, history: list[dict]) -> dict:
        """
        执行指定 Skill

        :param name: Skill 名称（config.json 的 name 字段）
        :param task_input: 任务描述（由 Planner 生成的 task_descriptions[name]）
        :param history: 会话历史消息
        :return: {"result": "...", ...}
        """
        skill = self._skills.get(name)
        if not skill:
            return {
                "result": f"技能 '{name}' 不存在，可用技能: {', '.join(self.list_names())}"
            }

        context = {
            "tools": skill["tools"],
            "skill_prompt": skill["skill_prompt"],
            "config": skill["config"],
            "skill_dir": skill["skill_dir"],
        }

        return await skill["module"].execute(task_input, history, context)


# 全局单例，import 时自动 discover
skill_loader = SkillLoader()
skill_loader.discover()
```

---

## 六、接入 LangGraph 图

### 通用 Skill Worker 节点

```python
# app/graph/nodes/skill_worker.py

from app.graph.state import AgentState
from app.skills.loader import skill_loader


async def skill_worker_node(state: AgentState) -> dict:
    """
    通用 Skill 执行节点
    _skill_name 由 Dispatcher 通过 Send 注入
    """
    if state.get("cancelled"):
        return {"worker_results": []}

    skill_name = state.get("_skill_name", "chat")
    task_input = state["task_descriptions"].get(skill_name, state["user_message"])
    history = state.get("history_messages", [])

    result = await skill_loader.run_skill(skill_name, task_input, history)

    output = {
        "worker_results": [{
            "worker_name": skill_name,
            "result": result.get("result", ""),
        }]
    }

    if result.get("article_cards"):
        output["article_cards"] = result["article_cards"]

    return output
```

### Planner 动态生成可用 Skill 列表

```python
# app/graph/nodes/planner.py

from app.skills.loader import skill_loader

# skill_loader.get_summaries() 自动生成，新增 Skill 文件夹后这里不用改
PLANNER_SYSTEM_PROMPT = f"""你是一个智能任务规划器。

【可用的技能】
{skill_loader.get_summaries()}

请根据用户消息选择需要的技能。
- 简单闲聊 → 只用 chat
- 技术问答 → rag_search
- 撰写文章 → writing
- 翻译 → translate
- 数据分析 → analysis
- 需要最新信息 → web_search_skill

以 JSON 返回：
{{"active_workers": ["skill1"], "task_descriptions": {{"skill1": "具体任务描述"}}}}
"""
```

### Graph Builder

```python
# app/graph/builder.py

def _build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("skill_worker", skill_worker_node)   # 1 个节点搞定所有 Skill
    graph.add_node("synthesizer", synthesizer_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", dispatcher_node)
    graph.add_edge("skill_worker", "synthesizer")       # 1 条边
    graph.add_edge("synthesizer", END)

    return graph
```

---

## 七、新增 Skill 标准操作

以新增「代码审查」Skill 为例，**完整操作只需 4 步**：

```bash
# 1. 创建目录
mkdir app/skills/code_review

# 2. 写描述（这里调整 LLM 行为）
# app/skills/code_review/skill.md

# 3. 写配置
# app/skills/code_review/config.json

# 4. 写逻辑
# app/skills/code_review/execute.py

# 重启服务，自动生效 ✓
```

**不需要修改**：
- `loader.py` ❌
- `dispatcher.py` ❌
- `builder.py` ❌
- `planner.py` ❌（摘要自动从 skill.md 提取）
- `skill_worker.py` ❌
- 任何其他文件 ❌

---

## 八、目录结构总览

```
app/
├── graph/
│   ├── tool_executor.py         # 公共 Tool 调用循环
│   └── nodes/
│       ├── planner.py           # 使用 skill_loader.get_summaries()
│       ├── dispatcher.py        # Send("skill_worker", ...)
│       ├── skill_worker.py      # 通用执行节点
│       └── synthesizer.py
├── skills/                      # Skill 文件夹目录
│   ├── loader.py                # 自动发现引擎（不需要改）
│   ├── rag_search/
│   │   ├── skill.md
│   │   ├── config.json
│   │   └── execute.py
│   ├── chat/
│   │   ├── skill.md
│   │   ├── config.json
│   │   └── execute.py
│   ├── writing/
│   │   ├── skill.md
│   │   ├── config.json
│   │   ├── execute.py
│   │   └── templates/
│   │       └── tech-blog.md
│   ├── analysis/
│   │   ├── skill.md
│   │   ├── config.json
│   │   └── execute.py
│   └── translate/               # ← 新增，不改其他任何文件
│       ├── skill.md
│       ├── config.json
│       └── execute.py
└── tools/
    ├── web_search.py            # @tool 原子工具（Skill 可以使用）
    └── article_tool.py
```
