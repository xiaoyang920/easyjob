# Skill 按需加载系统设计

## 一、概述

参考 Claude Code ECC 架构的 Skill 机制，为项目 Agent 增加 Skill 按需加载能力。

核心思想：Skill = 知识文档 + 指定 Tool 列表。Planner 只看元数据决定用哪些 Skill，Worker 执行时加载完整内容并只绑定 Skill 指定的 Tool。

## 二、与现有架构的关系

```
现有：Planner → Dispatcher → Worker（固定 System Prompt + 全部 Tool）→ Synthesizer
新增：Planner → Dispatcher → Worker（Skill 知识注入 Prompt + Skill 指定的 Tool）→ Synthesizer
```

改动点：
- 新增 SkillRegistry（独立于 ToolRegistry）
- Planner 输出增加 `required_skills` 字段
- Worker 执行前根据 Skill 动态组装 Prompt 和 Tool

## 三、目录结构

```
python-agent/app/skills/
├── registry.py              # Skill 注册中心
└── definitions/             # Skill 定义文件（md 格式）
    ├── spring_boot.md
    ├── docker_deploy.md
    ├── sql_optimize.md
    └── interview_prep.md
```

## 四、Skill 定义格式

每个 Skill 是一个 Markdown 文件，用 YAML front-matter 定义元数据：

```markdown
---
name: spring_boot
description: Spring Boot 开发最佳实践和常见问题解决
tags: [java, spring, backend]
required_tools: [search_articles, search_articles_by_knn, web_search]
---

# Spring Boot 开发指南

## 配置文件最佳实践
- application.yml 分环境配置（dev/prod）
- 敏感信息用环境变量，不要硬编码
- 使用 @ConfigurationProperties 绑定配置

## 常见问题
- 循环依赖：用 @Lazy 或重构代码结构
- 事务失效：确保方法是 public，不要自调用
...
```

元数据字段说明：
- `name`：唯一标识，Planner 输出时引用
- `description`：简短描述，Planner 看这个决定是否选用（不占太多 Token）
- `tags`：标签，辅助匹配
- `required_tools`：这个 Skill 需要的 Tool 列表，从 ToolRegistry 中按名称获取

## 五、SkillRegistry 实现

```python
# python-agent/app/skills/registry.py

import os
import logging
import yaml

log = logging.getLogger(__name__)

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "definitions")


class SkillMeta:
    """Skill 元数据（常驻内存，给 Planner 看）"""
    def __init__(self, name: str, description: str, tags: list[str],
                 required_tools: list[str], file_path: str):
        self.name = name
        self.description = description
        self.tags = tags
        self.required_tools = required_tools
        self.file_path = file_path


class SkillRegistry:
    """
    Skill 注册中心
    
    启动时扫描 definitions/ 目录，解析 front-matter 作为元数据。
    完整内容按需加载（调用 get_content 时才读文件）。
    """

    def __init__(self):
        self._skills: dict[str, SkillMeta] = {}
        self._scan()

    def _scan(self):
        """扫描 definitions 目录，解析所有 Skill 的元数据"""
        if not os.path.isdir(SKILLS_DIR):
            log.warning("Skill 目录不存在: %s", SKILLS_DIR)
            return

        for filename in os.listdir(SKILLS_DIR):
            if not filename.endswith(".md"):
                continue
            filepath = os.path.join(SKILLS_DIR, filename)
            try:
                meta = self._parse_meta(filepath)
                self._skills[meta.name] = meta
                log.info("注册 Skill: %s (%s)", meta.name, meta.description)
            except Exception as e:
                log.warning("解析 Skill 失败 [%s]: %s", filename, e)

        log.info("Skill 注册完成，共 %d 个", len(self._skills))

    def _parse_meta(self, filepath: str) -> SkillMeta:
        """解析 md 文件的 YAML front-matter"""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.startswith("---"):
            raise ValueError("缺少 YAML front-matter")

        parts = content.split("---", 2)
        if len(parts) < 3:
            raise ValueError("front-matter 格式错误")

        meta = yaml.safe_load(parts[1])
        return SkillMeta(
            name=meta["name"],
            description=meta.get("description", ""),
            tags=meta.get("tags", []),
            required_tools=meta.get("required_tools", []),
            file_path=filepath,
        )

    def get_catalog(self) -> str:
        """
        生成 Skill 目录文本，注入 Planner 的 System Prompt。
        只包含名称和描述，不包含完整内容。
        """
        if not self._skills:
            return "暂无可用 Skill"
        lines = []
        for s in self._skills.values():
            lines.append(f"- {s.name}: {s.description}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """按需加载 Skill 的完整内容（去掉 front-matter）"""
        skill = self._skills.get(name)
        if not skill:
            return ""
        with open(skill.file_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 去掉 front-matter，只返回正文
        parts = content.split("---", 2)
        return parts[2].strip() if len(parts) >= 3 else content

    def get_required_tools(self, name: str) -> list[str]:
        """获取 Skill 指定的 Tool 名称列表"""
        skill = self._skills.get(name)
        return skill.required_tools if skill else []

    def get_meta(self, name: str) -> SkillMeta | None:
        return self._skills.get(name)


# 全局单例
skill_registry = SkillRegistry()
```

## 六、Planner 改造

Planner 的 System Prompt 中注入 Skill 目录，输出增加 `required_skills` 字段：

```python
# planner.py 改造

from app.skills.registry import skill_registry

PLANNER_SYSTEM_PROMPT = """你是一个智能任务规划器。

【可用的Worker】
- search / analysis / writing / chat

【可用的Skill（领域知识包，按需选用）】
{skill_catalog}

【规划原则】
1. 简单问候/闲聊 → 只用 chat，不需要 Skill
2. 涉及特定技术领域 → 选择对应的 Skill
3. 不确定时不选 Skill，Worker 用默认知识回答

【当前日期】{current_date}

请严格以 JSON 格式返回：
{{"active_workers": ["worker1"], "task_descriptions": {{"worker1": "任务描述"}}, "required_skills": ["skill_name"]}}
"""

# 构建 Prompt 时注入目录和日期
prompt = PLANNER_SYSTEM_PROMPT.format(
    skill_catalog=skill_registry.get_catalog(),
    current_date=datetime.now().strftime("%Y-%m-%d"),
)
```

Planner 的 return 增加 `required_skills`：

```python
return {
    "active_workers": result.active_workers,
    "task_descriptions": result.task_descriptions,
    "required_skills": result.required_skills,  # 新增：传递给 Worker
}
```

PlannerOutput 增加字段：

```python
class PlannerOutput(BaseModel):
    active_workers: list[str]
    task_descriptions: dict[str, str]
    required_skills: list[str] = Field(default_factory=list)  # 新增
```

## 七、Worker 改造

Worker 执行前根据 Skill 动态组装 Prompt 和 Tool：

```python
# 以 chat_worker 为例

from app.skills.registry import skill_registry
from app.services.tool_registry import tool_registry

async def chat_worker_node(state: AgentState) -> dict:
    task_input = state["task_descriptions"].get("chat", state["user_message"])
    required_skills = state.get("required_skills", [])

    # 1. 组装 System Prompt = 基础 Prompt + Skill 知识
    system_prompt = CHAT_SYSTEM_PROMPT
    for skill_name in required_skills:
        content = skill_registry.get_content(skill_name)
        if content:
            system_prompt += f"\n\n【{skill_name} 领域知识】\n{content}"

    # 2. Tool 始终全绑定（Skill 只负责知识注入，不限制 Tool）
    tools = tool_registry.get_all_tools()

    # 3. 执行
    if tools:
        reply = await run_tool_agent(
            system_prompt=system_prompt,
            user_input=task_input,
            tools=tools,
        )
    else:
        llm = get_llm()
        messages = [SystemMessage(content=system_prompt)]
        messages.append(HumanMessage(content=task_input))
        response = await llm.ainvoke(messages)
        reply = response.content

    return {"worker_results": [{"worker_name": "chat", "result": reply}]}
```

## 八、AgentState 改造

```python
class AgentState(TypedDict):
    # ... 现有字段 ...
    required_skills: list[str]  # 新增：Planner 选择的 Skill 列表
```

## 九、数据流

```
用户: "Spring Boot 怎么配置多数据源？"
    ↓
Planner 看到 Skill 目录:
    - spring_boot: Spring Boot 开发最佳实践
    - docker_deploy: Docker 容器化部署指南
    ↓
Planner 输出:
    active_workers: ["chat"]
    task_descriptions: {"chat": "解答 Spring Boot 多数据源配置"}
    required_skills: ["spring_boot"]
    ↓
Dispatcher → ChatWorker:
    1. 加载 spring_boot.md 完整内容 → 注入 System Prompt
    2. 获取 spring_boot 指定的 Tool: [search_articles, web_search]
    3. 用增强后的 Prompt + 指定 Tool 执行
    ↓
Synthesizer → 返回用户
```

## 十、Skill 示例

### spring_boot.md

```markdown
---
name: spring_boot
description: Spring Boot 开发最佳实践和常见问题解决
tags: [java, spring, backend]
required_tools: [search_articles, search_articles_by_knn, web_search]
---

# Spring Boot 开发指南

## 配置最佳实践
- 使用 application.yml 分环境配置
- 敏感信息用环境变量
- @ConfigurationProperties 绑定配置类

## 常见问题
- 循环依赖：@Lazy 或重构
- 事务失效：方法必须 public，不能自调用
- 多数据源：@Primary + @Qualifier 区分
```

### interview_prep.md

```markdown
---
name: interview_prep
description: 技术面试准备助手，提供八股文和项目经验梳理
tags: [interview, career]
required_tools: [web_search]
---

# 面试准备指南

## 回答框架
- 先说结论，再展开细节
- 结合项目实际经验
- 对比不同方案的优缺点

## 常见追问应对
- "为什么选这个方案" → 对比其他方案
- "有什么缺点" → 诚实说，并给出改进方向
```

## 十一、依赖

需要安装 PyYAML 解析 front-matter：

```
pip install pyyaml
```

或在 requirements.txt 中添加：

```
pyyaml>=6.0,<7.0
```


## 十二、扩展：完整 Skill 目录结构（参考 ECC）

当前设计是简化版（单个 md 文件），将来 Skill 复杂度增加时，可以升级为目录结构：

```
python-agent/app/skills/definitions/
└── spring_boot/                    # 每个 Skill 是一个目录
    ├── SKILL.md                    # 核心知识文档（注入 System Prompt）
    ├── scripts/                    # 自动化脚本（Hooks 触发执行）
    │   ├── pre_check.py            # Tool 调用前的校验脚本
    │   └── post_format.py          # 回复后的格式化脚本
    └── references/                 # 补充参考资料
        ├── config_examples.md      # 配置示例
        └── common_errors.md        # 常见错误汇总
```

### 三部分职责

| 部分 | 内容 | 谁用 | 什么时候用 |
|---|---|---|---|
| SKILL.md | 核心知识 | Worker 的 LLM | Planner 选中后，注入 System Prompt |
| scripts/ | 自动化脚本 | Hooks 系统 | Tool 调用前后自动触发执行 |
| references/ | 补充资料 | Worker 的 LLM | 和 SKILL.md 一起加载，提供更详细的上下文 |

### scripts 使用场景

```python
# scripts/pre_check.py
# 在 Worker 调用 Tool 前自动执行，比如检查参数合法性
def pre_tool_check(tool_name, args):
    if tool_name == "web_search" and "Spring" not in args.get("query", ""):
        return {"warning": "当前 Skill 是 Spring Boot，搜索查询建议包含 Spring 关键词"}
    return {"ok": True}
```

### references 使用场景

references 目录下的 md 文件在 Skill 加载时一起读取，拼接到 SKILL.md 内容后面：

```python
def get_content(self, name: str) -> str:
    """加载 SKILL.md + references/ 下所有 md"""
    skill_dir = os.path.join(SKILLS_DIR, name)
    
    # 读主文档
    main_content = self._read_md(os.path.join(skill_dir, "SKILL.md"))
    
    # 读补充资料
    refs_dir = os.path.join(skill_dir, "references")
    if os.path.isdir(refs_dir):
        for ref_file in os.listdir(refs_dir):
            if ref_file.endswith(".md"):
                ref_content = self._read_md(os.path.join(refs_dir, ref_file))
                main_content += f"\n\n【参考：{ref_file}】\n{ref_content}"
    
    return main_content
```

### 迁移路径

当前单文件 → 目录结构的迁移很简单：

```
# 当前
definitions/spring_boot.md

# 升级后
definitions/spring_boot/
├── SKILL.md              ← 原来的 spring_boot.md 内容移过来
├── scripts/              ← 新增
└── references/           ← 新增
```

SkillRegistry 的 `_scan()` 方法改为同时支持文件和目录两种格式，向后兼容。
