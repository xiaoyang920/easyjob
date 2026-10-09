# EasyJob

技术博客平台，包含文章创作与审核、全文搜索、推荐、阅读等级、实时聊天和 AI 智能助手。

## 项目结构

- `src/`：Spring Boot 业务服务，文章、用户、通知、审核、权限及运维接口。
- `frontend/`：Vue 3、TypeScript、Element Plus 前端。
- `python-agent/`：FastAPI、LangGraph Agent，动态任务编排、混合检索、长期记忆及草稿审批。
- `python-agent/migrations/`：数据库增量迁移。
- `python-agent/evaluation/`：路由、检索和端到端评测；使用方式见该目录的 README。
- `scripts/`：本地启动、维护和回归检查脚本。

知识检索直接返回候选资料，下一轮 Main 在同一次模型调用内筛选引用、判断充分性并决定回答或继续检索，不再固定调用独立的充分性评估模型。执行契约与测试说明见 [Main 证据评估](python-agent/docs/main-evidence-assessment.md)。

## 环境与配置

开发环境需要 JDK 21、Maven、Node.js 24、Python 3.12，以及 MySQL、Elasticsearch、RabbitMQ、Redis。LangGraph Checkpoint 使用带 RedisJSON 和 RediSearch 模块的 Redis Stack；普通 Windows Redis 不能替代该实例。

真实密钥、数据库密码、本地运行配置、上传文件及测试日志不会提交。配置模板为：

- Java：复制 `src/main/resources/application-example.yml` 为同目录的 `application.yml`，配置数据库、缓存、消息队列、模型服务和 JWT 密钥。
- Python：复制 `python-agent/.env.example` 为 `.env`，补充数据库配置、模型密钥、文件上传路径；参考 `agent-runtime.env.example` 设置运行预算与 `REDIS_STACK_*`。
- Java 与 Python 必须使用相同的 `AGENT_SERVICE_KEY`（至少 32 字节），可通过进程环境变量提供。Java 的 `agent.python-url` 默认为 `http://localhost:8000`。
- Java 的 `file.upload.path` 与 Python 的 `FILE_UPLOAD_PATH` 应指向同一个上传目录。

迁移脚本升级已有业务数据库，不能代替基础业务表的初始化。升级前先备份数据库，在 Python 环境安装依赖后执行 `python -m app.migrate`；Agent 启动时会检查所需字段。

## 本地启动

先启动依赖服务并准备业务数据库，再分别启动三个服务：

```sh
# 项目根目录
mvn spring-boot:run

# python-agent 目录，先创建并激活虚拟环境
pip install -r requirements.txt
python -m app.migrate
uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend 目录
npm ci
npm run dev
```

前端地址为 `http://localhost:3000`，Java 为 `8080`，Python 为 `8000`。Vite 已配置 `/api`、`/uploads` 与 WebSocket 代理。

`scripts/start-local.ps1` 是 Windows 本地辅助脚本，使用前需准备运行配置并按实际安装目录设置参数。线上部署应另行配置反向代理、TLS、凭据与依赖服务访问权限。

## 验证

Python 离线单元测试需在进程环境中将 `DEEPSEEK_API_KEY`、`ZHIPUAI_API_KEY` 设为 `offline-test-key`，并设置 `LANGFUSE_TRACING_ENABLED=false`。这些值仅用于初始化被测试替身替换的客户端，无需使用真实模型密钥。

```sh
# 根目录；排除需要实际依赖服务的启动测试
mvn "-Dtest=!EasyjobApplicationTests" test

# frontend 目录
npm test
npm run build

# python-agent 目录
python -m unittest discover -s tests
```

GitHub Actions 运行 Java 单元测试、前端测试及构建、Python 单元测试。另有 `integration.yml` 启动独立 MySQL、Redis、RabbitMQ，初始化仅含结构的测试数据库，应用迁移，运行真实 Java 接口、SQL/Excel 对照与 Chromium 页面回归。该任务使用虚拟模型密钥、关闭索引投递及消费者，不启动 Agent 生成；实际模型效果评测仍需显式配置服务和密钥。

Agent 检索支持完整查询跳过额外改写、容量及过期受控的查询向量缓存。流式传输合并临时文本增量，第一段文字和控制事件立即发送；最终交付仍经过质量校验。失败的只读委派任务可在对话中选择“继续未完成任务”，最多恢复一次，复用来源版本有效的已完成子任务。取消及草稿审批不使用此入口。升级需执行包含 `015_task_recovery.sql` 的数据库迁移；运行参数见 `python-agent/.env.example`，成本和独立进程故障测试见 `python-agent/evaluation/README.md`。

管理员在“用户与成长”列表点击“编辑”，可修改昵称、简介、角色、账号状态及校正累计阅读时长。升级前执行包含 `016_admin_user_edit.sql` 的 `python -m app.migrate`。每次修改必须填写原因，日志保留完整前后值；旧表单与正在变化的阅读时长通过预期值校验保护。管理员不能取消自己的身份或禁用自己。角色/状态改变会递增登录版本，旧访问令牌和续签凭证失效，重新启用也需重新登录。阅读校正会重新计算等级并重置活动计时器，不改历史每日阅读统计。此入口不修改邮箱或密码。真实本地接口回归见 `python-agent/evaluation/admin_users.py`。

后台“概览”支持近 7、30、90 天的新增用户、首次发布文章及有效阅读趋势，以及当前文章状态和阅读等级分布。Java 在北京时间下统一查询统计，前端 SVG 展示图表，可查看每日数值；`GET /api/admin/statistics` 返回图表数据，`GET /api/admin/statistics/export` 使用 EasyExcel 导出含“统计说明、每日趋势、文章状态、阅读等级”的 XLSX，两者使用相同 `days`、`source` 参数，仅管理员可访问。`source` 支持 `business`（默认真实业务）、`evaluation`（评测样例）、`all`，按独立来源字段筛选，与账号是否禁用无关；上方管理概览仍展示全部记录。首次发布包含当前已下架文章，排除已删除文章；未公开不等同于纯草稿。阅读趋势来自所选来源用户的每日计时记录，不计管理员校正的成长时长；阅读用户按所选周期去重，等级分布包含所选来源的禁用账号。迁移 `018_statistics_and_category_management.sql` 只标记明确的保留评测账号及其文章，不删除数据；评测样例生成脚本和新文章保存同步继承来源。真实接口及工作簿内容回归见 `python-agent/evaluation/admin_statistics.py`。

管理员可在后台“分类管理”或写文章页的“新增分类”创建一级/二级分类，设置名称、说明和排序；编辑器创建后自动选中，分类列表只返回启用分类。`GET/POST /api/admin/categories` 每次校验管理员权限，创建及操作日志在同一事务提交；同一父分类下由数据库唯一索引拦截重名并发创建。升级执行包含 `017_admin_categories.sql` 的 `python -m app.migrate`，存在历史重名时会停止并要求人工确认，不自动合并或删除。分类列表直接读库，避免旧缓存影响新增分类的可见性。真实本地权限/并发回归：`python -m evaluation.admin_categories`。

分类管理还支持 `PUT /api/admin/categories/{id}` 改名、排序、说明和启停；`POST /api/admin/categories/{id}/migrate` 将未删除文章整体迁入目标并停用原分类，一次最多500篇。源、目标分类必须带当前版本，过期表单返回409；一级分类停用/迁移前须先处理启用的二级分类。已迁移分类保留转向，不能重新启用；旧草稿、编辑器和待审核版本在读取或保存时解析至新分类，保留不可变版本正文及原校验值。迁移、索引投递意图和操作日志在同一事务提交，提交后失效详情缓存。升级先执行包含018的 `python -m app.migrate`。接口回归覆盖并发编辑、停用可见性、迁移原子性、旧编辑器保存及迁移后审核通过，使用隔离夹具并清理。

## 后台角色、运行指标与推荐反馈

迁移 `019_platform_completion.sql` 增加角色权限映射及推荐反馈表。管理员（角色2）保留完整权限，并可在“用户与成长”分配审核员（角色3）或运营员（角色4）。审核员管理文章与审核，运营员管理分类、查看统计和 Agent 指标、处理运行任务；两者可查看概览和操作日志，都不能修改用户或分配角色。`GET /api/admin/me` 返回当前能力集合，前端据此显示模块，后端每个入口独立校验；角色和账号状态改变撤销旧登录。阅读等级的管理员豁免仍仅适用于角色2。

后台“Agent 指标”支持7/30/90天及业务/评测/全部来源，展示运行状态、完成成功率、活跃时长P50/P95、模型调用及失败数量、供应商已记录的输入/输出Token与每日趋势。成功率覆盖周期内全部运行，分母为已结束运行，取消和过期计为未成功；进行中及待审批不计入分母。时长和使用量只采样最近10000次运行，标明覆盖数量，缺失时长为空；Token仅累计已测得部分，不以预算替代真实用量，也不估算费用。活跃时长排除用户审批等待，使用量不含Embedding、精排和后台记忆处理。

登录用户可在首页推荐卡片选择“不感兴趣”或“不再推荐该作者”，在“推荐偏好”中恢复。反馈按用户隔离，仅影响推荐列表，不影响搜索、最新发布或主动访问；作者屏蔽保留目标作者ID，原文章删除后仍有效。每人最多200条，写入用用户行锁保护上限，删除仅允许操作自己的记录。接口为 `GET /api/recommendation/feedback`、`PUT/DELETE /api/recommendation/feedback/{articleId}`。

本地真实回归：先在 `python-agent` 执行 `python -m evaluation.platform --seed-browser`，再在 `frontend` 执行 `npx playwright install chromium` 和 `npm run test:browser`，最后执行 `python -m evaluation.platform --cleanup`。仅创建并清理核验过身份的临时账号、文章、分类、运行和登录凭证；夹具不提交仓库。`tests/integration/schema.sql` 仅供空的 `*_ci` 测试数据库初始化，不包含用户数据，不用于覆盖已有数据库。
