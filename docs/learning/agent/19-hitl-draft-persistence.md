# HITL 草稿持久化设计

> AI 对话中 writing_worker 生成的草稿，在用户"确认"后持久化到草稿箱，替换当前"切会话即丢"的中间态。

## 1. 背景与问题

### 1.1 当前流程

```
用户: 帮我写一篇关于 X 的文章
  ↓
[planner]        规划调用 writing + search
[writing_worker] 生成 markdown 草稿 draft
                 └─→ interrupt({ action:"confirm_publish", draft }) 暂停
   SSE 下发 __INTERRUPTED__ 事件
   前端把 draft 塞进 AI 气泡（msg.content = draft, msg.isDraft = true）
   并显示【确认】/【拒绝】按钮

用户点【确认】
  ↓
前端 resume(approve) → 后端从 RedisCheckpointer 恢复图
  ↓
[writing_worker] 续跑 → worker_results += { worker:"writing", result: draft }
[synthesizer]    把所有 worker_results 汇总 → 最终回复 final_reply
  ↓
后端 add_message(role="assistant", content=final_reply) 落库
  最终写入 ai_message 表的只有 final_reply
```

### 1.2 问题

- **切换会话再回来，草稿"消失"**：`ai_message.content` 里只存 synthesizer 输出的 `final_reply`，而 `final_reply` 多半是"对话式总结"，并非草稿原文。
- **草稿原文没处安放**：当前 draft 只活在 LangGraph 的 checkpoint（Redis）里，`resume` 之后就随 checkpoint 一起过期。
- **产品闭环断开**：用户同意的"草稿"应当能继续编辑/发布，但现在连"看一眼"都做不到。
- **synthesizer 可能改写 draft**：同意的内容和最终看到的内容未必一致，二次加工让用户困惑。

## 2. 设计目标

1. 用户在 AI 对话中点击【确认】后，草稿持久化到 `article_info` 表（`status=0` 草稿态），与用户手工"保存草稿"完全等价
2. AI 聊天记录里保留对该草稿的轻量引用（仅 `draft_article_id`），不冗余存储正文
3. 同一会话中多次生成草稿不会相互覆盖——每条草稿是 `article_info` 的独立行
4. 切回历史会话时，每条 assistant 消息若带有 `draft_article_id`，前端显示【查看 / 编辑草稿】按钮
5. synthesizer 对 writing 任务不再二次改写草稿内容，只产出一句简短提示（例如"已为你生成草稿《xxx》，可在草稿箱继续编辑"）
6. 【拒绝】行为保持不变：草稿**不落库**，对话结束

## 3. 数据模型

### 3.1 `ai_message` 新增字段

```sql
ALTER TABLE ai_message
ADD COLUMN draft_article_id BIGINT DEFAULT NULL
COMMENT 'HITL 产生的草稿 article_id（引用 article_info.article_id），NULL 表示该消息无关联草稿';
```

- 类型 `BIGINT`：与 `article_info.article_id`（雪花 ID）保持一致
- 默认 `NULL`：绝大多数 assistant 消息不带草稿
- 不建外键约束（和仓库其他表的风格一致，软引用）
- 前端 JSON 序列化为 string 避免 JS 精度丢失（已有全局 Jackson 规则）

### 3.2 不动的东西

- `ai_conversation` 表：**不加字段**。草稿是 1 对 N 挂在消息上的，和会话无关
- `article_info` 表：**不加字段**。由 AI 生成的草稿，在用户视角等同于手工草稿，没有本质区别
- `article_cards` 字段：保持原状，只挂 `search_worker` 的搜索结果

### 3.3 为什么不是"给会话加字段"

用户直觉会想"给 `ai_conversation` 加 `latest_draft`"，这是错的：

| 方案 | 结果 |
| --- | --- |
| `ai_conversation.latest_draft` | 第二次生成草稿会**覆盖**第一次的，多草稿互相吃 |
| `ai_message.draft_content`（TEXT） | 能存多草稿，但挪不到草稿箱，且每条消息 content 会很大 |
| **`ai_message.draft_article_id`（选用）** | 多草稿 1:1 挂在各自消息上；草稿本身活在 `article_info` 里，用户可编辑可发布 |

### 3.4 `article_info` 表字段填充策略

`article_info` 表字段多，AI 生成草稿时按"**自动可算的都填，需要运营/用户决策的留空**"切分：

| 类别 | 字段 | 填充策略 |
| --- | --- | --- |
| **主键/外键** | `article_id` | `snowflake.next_id()` |
| | `user_id` | 当前登录用户（state.user_id） |
| **内容（LLM 同步产出）** | `title` | `DraftOutput.title`（见 §4.1.1），抽不到 fallback `AI 草稿·yyyy-MM-dd HH:mm` |
| | `summary` | `DraftOutput.summary`，LLM 空值时走正则兜底（见 `_make_fallback_summary`） |
| | `content` | `DraftOutput.content`（markdown 正文） |
| | `content_type` | `2`（Markdown） |
| | `tags` | **留空**（字段传 `""` 或 NULL）。AI 不自动生成标签，统一在用户发布前的编辑器里选择 |
| **状态** | `status` | `0`（草稿） |
| | `is_original` | `1`（AI 协助生成，默认视为用户原创，和手工草稿一致） |
| | `is_top` / `is_essence` | `0`（运营态，AI 不碰） |
| | `deleted` | `0` |
| **计数（自动维护）** | `view_count` / `like_count` / `collect_count` / `comment_count` / `share_count` | 全部 `0`，日常业务行为触发累加（点赞 / 收藏 / 浏览等 Service 已有），AI 侧不填 |
| **时间** | `create_time` / `update_time` | `now()` |
| | `publish_time` | `NULL`（草稿未发布，`ArticleServiceImpl.publish` 时赋值） |
| **留给用户编辑** | `cover_image` | `NULL`（AI 不好选，用户在编辑器里挑） |
| | `category_id` | `NULL`（分类体系与业务强耦合，用户点两下就能选，让 AI 猜反而风险大） |

**关键决策说明**：

- `category_id` 留空：若将来确需 AI 自动选分类，把 `article_category` 表的分类名拼进 writing prompt 让 LLM 选一个再回查 id 即可，属于**可选增强**，不阻塞本次
- `summary` **必须**有：草稿箱列表页会展示 summary，空字符串会让卡片看起来很空
- `tags` **由用户在发布前选择**：AI 草稿不自动打标签，也不调用任何 `article_tag` / `article_tag_relation` 相关逻辑。用户从草稿箱进入 `/edit-article?id=xxx` 时，沿用现有 `CreateArticle.vue` 的联想 / 热门 / 手工输入机制自己选 tag，然后点发布走 `ArticleServiceImpl.publish`。
  - **好处 1**：彻底回避 AI 乱起标签导致的 tag 体系污染（`SpringBoot / Spring Boot / spring-boot` 同义词泛滥）
  - **好处 2**：Python agent 不跨库写 `article_tag` / `article_tag_relation`，规则由 Java 一处维护
  - **好处 3**：复用现有发布流程，无需任何新接口
  - **产品约束**：发布流程最好对 AI 草稿的 `tags` 做"至少一个"校验，避免用户直接从草稿箱一键发布却没标签；若现有发布流程已强校验则无需改动

## 4. 后端流程改造

### 4.1 Python Agent（`python-agent/`）

#### 4.1.1 `writing_worker_node`：结构化产出 DraftOutput

把 `generate_draft` 的输出从"一整段 markdown"改成"结构化对象"，一次 LLM 调用同时拿到 **title / summary / content / tags**，避免二次解析、避免"草稿箱列表空摘要"。

```python
# python-agent/app/graph/nodes/writing_worker.py（伪代码，仅示意改动点）
from pydantic import BaseModel, Field


class DraftOutput(BaseModel):
    title: str = Field(description="文章标题，≤50 字，简洁有信息量")
    summary: str = Field(description="一段话摘要，≤120 字，用于列表页展示")
    content: str = Field(description="完整 markdown 正文，从 # 一级标题开始")
    # 说明：不要求 LLM 产出 tags。AI 草稿的 tags 字段留空，
    # 用户在发布前的编辑器里手工选择（参见 §3.4）。


async def generate_draft(task_input: str, system_prompt: str) -> DraftOutput:
    """生成草稿：LLM + Tool 多轮检索 → 结构化产出"""
    all_tools = tool_registry.get_all_tools()

    # 先照旧跑 tool 多轮检索，拿到"信息充分的 markdown"
    raw_markdown = await run_tool_agent(
        system_prompt=system_prompt,
        user_input=task_input,
        tools=all_tools,
        max_rounds=2,
        tag="writing_worker",
    )

    # 再让裸 LLM 把 raw_markdown 结构化成 DraftOutput
    llm = get_llm().with_structured_output(DraftOutput, method="function_calling")
    structured = await llm.ainvoke([
        SystemMessage(content=STRUCTURIZE_PROMPT),
        HumanMessage(content=raw_markdown),
    ])

    # 兜底：LLM 偶尔会少字段
    if not structured.title:
        structured.title = extract_title_from_draft(raw_markdown)
    if not structured.summary:
        structured.summary = _make_fallback_summary(raw_markdown)
    if not structured.content:
        structured.content = raw_markdown

    return structured
```

`STRUCTURIZE_PROMPT` 由自然语言组成，要求 LLM：
- 从原 markdown 抽一级标题作为 `title`（若无则自造一个 ≤50 字的标题）
- 生成 ≤120 字的 `summary`
- `content` 原样保留（包括原 markdown 结构）

**interrupt 阶段**把 `draft` 传给前端用 `DraftOutput.content`（用户看到的仍是原 markdown 正文）：

```python
user_decision = interrupt({
    "action": "confirm_publish",
    "draft": structured.content,          # 前端预览用
    "title": structured.title,            # 供前端在徽章/标题处展示
    "summary": structured.summary,
    "message": "草稿已生成，是否发布？",
})
```

**approve 分支**把完整结构体入库：

```python
if user_decision == "approve":
    article_id = await save_draft_to_article_info(
        user_id=state["user_id"],
        draft=structured,
    )
    return {
        "worker_results": [{
            "worker_name": "writing",
            "result": structured.content,     # 给 synthesizer 的"结果文本"保持 markdown
            "draft_article_id": article_id,
            "draft_title": structured.title,  # 供 SSE __DRAFT_SAVED__ 事件透传给前端
        }]
    }
```

**reject / 修改意见分支**保持原有语义，不入库。


#### 4.1.2 `save_draft_to_article_info`：尽量填充 article_info 字段

按 §3.4 的字段填充策略，一次把所有"自动可算"的字段补齐：

```python
# python-agent/app/services/draft_service.py（新建）
import re
from datetime import datetime

from app.clients.mysql_client import db
from app.utils.snowflake import snowflake


async def save_draft_to_article_info(user_id: int, draft: "DraftOutput") -> int:
    """
    把 writing_worker 生成的 DraftOutput 持久化为 article_info 草稿（status=0）。
    与用户手工"保存草稿"行为完全等价，后续可在草稿箱直接编辑 / 发布。
    """
    article_id = snowflake.next_id()
    now = datetime.now()

    title = (draft.title or "").strip() \
        or extract_title_from_draft(draft.content) \
        or f"AI 草稿·{now.strftime('%Y-%m-%d %H:%M')}"
    title = title[:50]

    summary = (draft.summary or "").strip() or _make_fallback_summary(draft.content)
    summary = summary[:200]

    await db.execute(
        """
        INSERT INTO article_info (
            article_id, user_id,
            title, cover_image, summary, content, content_type,
            category_id, tags,
            view_count, like_count, collect_count, comment_count, share_count,
            status, is_top, is_essence, is_original,
            publish_time, create_time, update_time, deleted
        ) VALUES (
            :aid, :uid,
            :title, NULL, :summary, :content, 2,
            NULL, '',
            0, 0, 0, 0, 0,
            0, 0, 0, 1,
            NULL, :now, :now, 0
        )
        """,
        {
            "aid": article_id,
            "uid": user_id,
            "title": title,
            "summary": summary,
            "content": draft.content,
            "now": now,
        },
    )
    return article_id


def extract_title_from_draft(content: str) -> str:
    """从 markdown 首个 `# 标题` 抽取标题；抽不到返回空字符串"""
    if not content:
        return ""
    m = re.search(r"^\s*#\s+(.+)$", content, flags=re.MULTILINE)
    if not m:
        return ""
    return m.group(1).strip()[:50]


def _make_fallback_summary(content: str) -> str:
    """从正文抽 ≤150 字作为摘要兜底（去 markdown 语法 + 去多余空白）"""
    if not content:
        return ""
    plain = re.sub(r"^#+\s+.+$", "", content, flags=re.MULTILINE)   # 去标题行
    plain = re.sub(r"```[\s\S]*?```", "", plain)                     # 去代码块
    plain = re.sub(r"[*_`#>\[\]()]+", "", plain)                     # 去行内 markdown 标记
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:150]
```

**落地要点**：

- 与用户手工"保存草稿"行为**完全等价**，用户在草稿箱里看到的 AI 草稿和自己起草的一样，能直接走已有的 `EditArticle.vue` 编辑流程
- 计数字段显式填 `0`，和 `ArticleServiceImpl` 里对应 `changeLikeCount / changeCollectCount` 等累加逻辑一致（避免默认 `NULL` 被累加出 `NULL + 1 = NULL`）
- `is_original=1`（原创）：AI 生成的内容经用户确认发布，视同用户原创作品；若将来业务上要区分 AI 生成，另加一个 `is_ai_generated` 字段，不动 `is_original`
- `publish_time=NULL`：不在这里赋值，保持和 `ArticleServiceImpl.publish` 单点负责的约定
- **不触发 ES 索引**：草稿不进搜索索引，与 `ArticleService.publish()` 的行为一致

#### 4.1.3 `synthesizer`

原来 synthesizer 会把 draft 连同其他 worker 的产出一起揉成一段"好的，我为您写了…"的长回复。现在要做三件事：

- 草稿已经在 `article_info` 里了，不能再塞进 synthesizer 的 LLM prompt（几千字 markdown 既烧 token 又让最终气泡变长）
- 但若 planner 规划了 `writing + search`（或 `writing + analysis`）并行，search / analysis 的**真实产出要保留**，不能因为有草稿就全丢
- `draft_article_id` 要透传给下游（最终会落到 `ai_message.draft_article_id` 列）

因此 synthesizer 改为三分支：

```python
# 伪代码
writing_result = next(
    (r for r in worker_results
     if r["worker_name"] == "writing" and r.get("draft_article_id")),
    None,
)
other_results = [r for r in worker_results if r is not writing_result]
has_other_content = any((r.get("result") or "").strip() for r in other_results)

# 场景 A：只有 writing 有草稿，其他 worker 没实际产出（或根本没被规划）
#   → 不走 LLM，直接出简短提示，最便宜
if writing_result and not has_other_content:
    return {
        "final_reply": "已为你生成草稿，可在草稿箱继续编辑。",
        "draft_article_id": writing_result["draft_article_id"],
    }

# 场景 B：writing 有草稿 + 其他 worker 也有实际产出（例如同时做了 search）
#   → 只把 other_results 喂给 synthesizer LLM 做正常汇总
#   → 末尾追加一句草稿提示
if writing_result:
    base_reply = await synthesize(other_results, ...)   # 不包含 draft 正文
    final_reply = (
        base_reply.rstrip()
        + "\n\n---\n另外，我已为你起草了一份文章，可在草稿箱继续编辑。"
    )
    return {
        "final_reply": final_reply,
        "draft_article_id": writing_result["draft_article_id"],
    }

# 场景 C：没有 writing（纯检索 / 分析）
#   → 完全保持现有 synthesizer 逻辑
return {
    "final_reply": await synthesize(worker_results, ...),
}
```

关键点：

- **writing 的 draft 永远不进 synthesizer 的 LLM prompt**。这既避免了"同意的草稿内容和 synthesizer 二次改写后的内容不一致"的困惑，也不会让简单场景花冤枉钱
- **"有草稿 + 有其他产出"用拼接而非再让 LLM 重新写**：因为拼接能保证"搜索结果照实呈现 + 草稿提示一句话"，而让 LLM 再重写一遍往往会漏掉某一路信息
- `draft_article_id` 只在有草稿时透传；没有草稿的场景（场景 C）返回里不含这个字段，下游 `state.get("draft_article_id")` 自然为 None

理由：草稿本体已经在草稿箱可编辑，聊天记录不需要再复述一遍，否则 `ai_message.content` 会被巨长的 markdown 淹没。

#### 4.1.4 `ConversationService.add_message`

签名增加可选参数：
```python
async def add_message(
    self, conversation_id: int, role: str, content: str,
    image_paths: list[str] | None = None,
    article_cards: list[dict] | None = None,
    draft_article_id: int | None = None,   # ← 新增
):
    ...
    await db.execute(
        """
        INSERT INTO ai_message
            (message_id, conversation_id, role, content, token_count, 
             image_paths, article_cards, draft_article_id, create_time)
        VALUES
            (:mid, :cid, :role, :content, :tc, :imgs, :cards, :draft_aid, :now)
        """,
        { ..., "draft_aid": draft_article_id }
    )
```

`_get_all_messages` 的 SELECT 也加上 `draft_article_id` 字段，返回给前端。

#### 4.1.5 保存消息的调用点

目前 `chat.py` 或对应 SSE 入口处，流式结束后会：
```python
await conversation.add_message(
    cid, "assistant", final_reply,
    article_cards=state.get("article_cards"),
)
```

改为：
```python
await conversation.add_message(
    cid, "assistant", final_reply,
    article_cards=state.get("article_cards"),
    draft_article_id=state.get("draft_article_id"),   # ← 新增
)
```

### 4.2 Java 后端

#### 4.2.1 `ai_message` 的查询 VO / 映射

找到 `ai_message` 对应的实体 / Mapper / VO，把 `draft_article_id` 字段加上：

```java
// 实体
@Data
public class AiMessage {
    ...
    private Long draftArticleId;   // ← 新增
}
```

```java
// VO（返回给前端的）
@Data
public class AiMessageVO {
    ...
    private String draftArticleId;  // 雪花 ID 用 String，避免 JS 精度丢失
}
```

Jackson 全局规则已把 Long 输出为 String，VO 用 `Long` 也可，与仓库其他雪花 ID 字段保持一致即可。

#### 4.2.2 `/api/agent/conversations/{cid}/messages` 接口

返回结构里加字段：
```json
{
  "role": "assistant",
  "content": "已为你生成草稿，可在草稿箱继续编辑。",
  "createTime": "...",
  "articleCards": [],
  "draftArticleId": "12345678901234567",     // ← 新增
  "imagePaths": null
}
```

### 4.3 拒绝路径

`writing_worker_node` 的 reject 分支保持不变：
```python
elif user_decision == "reject":
    return { "worker_results": [{ "worker_name": "writing", "result": "用户取消了发布" }] }
```

不写 `article_info`，不带 `draft_article_id`，消息记录里也没有草稿按钮。

### 4.4 SSE 事件协议

现有事件保留：
- `__CONV_ID__:xxx`
- `__ARTICLES__:[]`
- `__PROGRESS__:...`
- `__INTERRUPTED__:{"draft":"...","message":"..."}`（interrupt 阶段，draft 仍然下发，前端实时预览）

新增一个事件类型（resume approve 之后、流式推文本前）：

```
__DRAFT_SAVED__:{"draftArticleId":"12345678901234567","title":"Spring Boot 入门"}
```

前端收到这个事件，立刻把当前 ai message 的 `draftArticleId` 设上，切走再回来也能从 ai_message 表同步到同样的 id。

## 5. 前端改造

### 5.1 数据结构

`frontend/src/views/AiChat.vue` 里的 `ChatMessage` 接口：

```ts
interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  image?: string | null
  articles?: ArticleCard[]
  progressSteps?: ProgressStep[]
  interrupted?: boolean
  interruptPayload?: Record<string, any>
  isDraft?: boolean              // 仅在 interrupt 阶段为 true，用来显示"草稿预览"徽章
  draftArticleId?: string        // ← 新增，resume approve 后后端下发
}
```

### 5.2 SSE 解析

新增事件处理：
```ts
if (data.startsWith('__DRAFT_SAVED__:')) {
  try {
    const payload = JSON.parse(data.substring(16).trim())
    messages.value[aiMsgIndex].draftArticleId = payload.draftArticleId
    // approve 后 isDraft 变成历史态，不再显示"草稿预览"徽章
    messages.value[aiMsgIndex].isDraft = false
  } catch (e) {
    console.error('解析草稿保存事件失败:', e)
  }
  continue
}
```

### 5.3 历史消息加载

`switchConversation` 里加载 `/agent/conversations/{cid}/messages` 的映射补上：
```ts
messages.value = res.data.map((msg: any) => ({
  role: msg.role,
  content: msg.content,
  image: msg.imagePaths?.[0] ? `/uploads/${msg.imagePaths[0]}` : null,
  articles: msg.articleCards || [],
  draftArticleId: msg.draftArticleId || undefined,   // ← 新增
}))
```

### 5.4 消息气泡 UI

在 `interrupt-actions` 下方追加一块**草稿指引**（仅 `msg.draftArticleId` 存在时显示）：

```html
<div v-if="msg.draftArticleId" class="draft-link">
  <svg class="draft-link-icon" viewBox="..."><path .../></svg>
  <span class="draft-link-text">已保存至草稿箱</span>
  <button class="draft-link-btn" @click="editDraft(msg.draftArticleId)">
    编辑草稿
  </button>
</div>
```

```ts
function editDraft(articleId: string) {
  router.push(`/edit-article?id=${articleId}`)
}
```

样式（与当前克制高级感一致）：
- 浅灰底 `#fafbfc`，细边框 `#edf0f3`
- 左侧小图标（文档图），深灰文字
- 右侧一个主题蓝的链接按钮"编辑草稿"

### 5.5 审批态变化

- interrupt 阶段：显示【确认】【拒绝】按钮、"草稿预览"徽章、draft 内容
- 用户点【确认】：
  - `msg.interrupted = false`（审批按钮消失）
  - 收到 `__DRAFT_SAVED__` → `msg.draftArticleId` 被设上
  - `msg.isDraft = false`（预览徽章消失）
  - 最终收到 synthesizer 的简短提示 → `msg.content = "已为你生成草稿..."`
  - 气泡下方出现"已保存至草稿箱 / 编辑草稿"按钮
- 用户点【拒绝】：
  - `msg.interrupted = false`
  - content 变成 "用户取消了发布" 或直接为空
  - 无 draftArticleId，不显示草稿按钮

## 6. 多草稿场景验证

| 场景 | 期望 |
| --- | --- |
| 同一会话里连续生成 2 条草稿并都确认 | `article_info` 新增 2 条独立行，对应 2 个 assistant 消息各自带不同的 `draft_article_id` |
| 同一会话里生成草稿 A 并拒绝，再生成草稿 B 并确认 | `article_info` 只新增 B，消息 A 的 content 为"用户取消了发布"且无 draftArticleId |
| 切换到其他会话再切回来 | 两条 assistant 消息都能正确拉到各自的 `draftArticleId`，"编辑草稿"按钮都可点 |
| 用户把某条草稿在草稿箱里删除 | 聊天记录里的"编辑草稿"按钮点击后需要处理 404（见 §7） |

## 7. 异常与边界

1. **草稿落库失败**：`save_draft_to_article_info` 捕获异常，log error + 降级为"保存失败但文本已产出"——在 `ai_message` 只存 synthesizer 的降级文案（例如"草稿已生成，但保存失败，请复制保留"），`draft_article_id` 为 NULL
2. **用户在草稿箱删除草稿**后，聊天记录里的"编辑草稿"按钮点进去 404：`EditArticle.vue` 已有的 404 处理即可，不需要额外适配
3. **LangGraph checkpoint 过期**：如果用户长时间（例如 24h）后才点【确认】，checkpoint 已清理，resume 会报错。现有行为是 SSE 返回错误，前端提示"会话已过期，请重新发送"，本设计不改变该行为
4. **标题/摘要产出为空**：`DraftOutput` 里字段在 `save_draft_to_article_info` 内都有兜底——标题走 `extract_title_from_draft` → `AI 草稿·yyyy-MM-dd HH:mm`；摘要走 `_make_fallback_summary`；tags 固定写入空字符串，由用户发布前在编辑器里选择
5. **用户没登录 user_id 缺失**：这种场景不应到达 interrupt（前置 JWT 校验会拦截），兜底 log error 并不落库

## 8. 迁移与回滚

### 8.1 上线步骤

1. 先执行 SQL：`ALTER TABLE ai_message ADD COLUMN draft_article_id BIGINT DEFAULT NULL ...`
2. Python Agent 服务升级（新 add_message / writing_worker / synthesizer / 事件下发）
3. Java 后端升级（VO / 查询映射）
4. 前端升级

顺序可反，因为字段是可选的，老前端连同老后端也能兼容（没有该字段而已）。

### 8.2 历史数据

- 老 `ai_message` 行的 `draft_article_id` 全部为 NULL，显示效果 = 当前效果
- 不需要数据迁移

### 8.3 回滚

- 回滚前端：没任何副作用，老版本只是看不到新按钮
- 回滚后端：Python Agent 退回老版本 writing_worker + synthesizer 即可；已插入 `article_info` 的草稿依然是用户的正常草稿，可继续使用
- 回滚 SQL：不建议；`draft_article_id` 留着也无害

## 9. 不在本次范围

- 草稿的**智能润色 / 重新生成**按钮（未来可在编辑页加入 AI 助手，不是本设计问题）
- 草稿自动发布（本设计始终 `status=0`，发布走原有 `ArticleService.publish` 流程）
- **AI 自动标签**：刻意排除。AI 草稿 `tags` 字段始终为空，由用户在发布前的编辑器里选择，沿用现有 `CreateArticle.vue` 的联想 / 热门 / 手工输入机制。理由见 §3.4
- `category_id` 自动选择：本期留空由用户在编辑器内选，若要 AI 自动分类，可把 `article_category` 表拼进 writing prompt 让 LLM 选一个名字再回查 id
- 封面图自动生成 / 抽取：本期留空；未来可用 LLM 提取正文里的首张图片 URL 或调文生图
- interrupt 失效时的"跨会话继续审批"（如果用户希望切走再回来还能点确认，需要上线更复杂的 HITL 状态管理，不在本期）
