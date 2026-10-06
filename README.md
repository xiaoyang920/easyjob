# EasyJob

技术博客平台，包含文章创作与审核、全文搜索、推荐、阅读等级、实时聊天和 AI 智能助手。

## 项目结构

- `src/`：Spring Boot 业务服务，文章、用户、通知、审核、权限及运维接口。
- `frontend/`：Vue 3、TypeScript、Element Plus 前端。
- `python-agent/`：FastAPI、LangGraph Agent，动态任务编排、混合检索、长期记忆及草稿审批。
- `python-agent/migrations/`：数据库增量迁移。
- `python-agent/evaluation/`：路由、检索和端到端评测；使用方式见该目录的 README。
- `scripts/`：本地启动、维护和回归检查脚本。

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

GitHub Actions 运行 Java 单元测试、前端测试及构建、Python 单元测试。真实模型和端到端评测需单独配置本地服务与密钥，可能调用付费 API；不包含在默认 CI 中。
