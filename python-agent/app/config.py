"""
配置管理
对应 Java: application.yml + @Value 注入
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

_env_dir = Path(__file__).resolve().parent.parent
# Local runtime overrides stay outside the legacy tracked .env. Explicit process
# environment variables retain priority because load_dotenv does not override them.
load_dotenv(_env_dir / ".env.runtime.local")
load_dotenv(_env_dir / ".env")


class Settings:
    AGENT_SERVICE_KEY: str = os.getenv("AGENT_SERVICE_KEY", "")
    JAVA_AGENT_URL: str = os.getenv("JAVA_AGENT_URL", "http://localhost:8080")
    INTERNAL_TRANSPORT: str = os.getenv("AGENT_INTERNAL_TRANSPORT", "triple").strip().lower()
    AGENT_RPC_ENABLED: bool = os.getenv("AGENT_RPC_ENABLED", "true").lower() in ("true", "1", "yes")
    AGENT_RPC_BIND: str = os.getenv("AGENT_RPC_BIND", "127.0.0.1:50051")
    BLOG_RPC_TARGET: str = os.getenv("BLOG_RPC_TARGET", "127.0.0.1:20881")
    RUN_TIMEOUT_SECONDS: int = int(os.getenv("AGENT_RUN_TIMEOUT_SECONDS", "300"))
    EXECUTOR_HEARTBEAT_SECONDS: int = 10
    EXECUTOR_LEASE_SECONDS: int = 45
    EXECUTION_GLOBAL_LIMIT: int = max(1, int(os.getenv("AGENT_EXECUTION_GLOBAL_LIMIT", "8")))
    EXECUTION_USER_LIMIT: int = max(1, int(os.getenv("AGENT_EXECUTION_USER_LIMIT", "2")))
    EXECUTION_QUEUE_LIMIT: int = max(0, int(os.getenv("AGENT_EXECUTION_QUEUE_LIMIT", "16")))
    EXECUTION_WAIT_SECONDS: int = max(1, int(os.getenv("AGENT_EXECUTION_WAIT_SECONDS", "10")))
    RUN_TOTAL_TOKEN_BUDGET: int = max(16384, int(os.getenv("AGENT_RUN_TOTAL_TOKEN_BUDGET", "524288")))
    STREAM_RETENTION_DAYS: int = max(1, int(os.getenv("AGENT_STREAM_RETENTION_DAYS", "7")))
    CHECKPOINT_SUCCESS_RETENTION_DAYS: int = max(1, int(os.getenv('AGENT_CHECKPOINT_SUCCESS_RETENTION_DAYS', '1')))
    CHECKPOINT_RETENTION_DAYS: int = max(1, int(os.getenv('AGENT_CHECKPOINT_FAILURE_RETENTION_DAYS',
                                                       os.getenv('AGENT_CHECKPOINT_RETENTION_DAYS', '7'))))
    MAIN_MAX_ROUNDS: int = max(1, min(20, int(os.getenv("AGENT_MAIN_MAX_ROUNDS", "8"))))
    MAIN_MAX_TASKS: int = max(1, min(32, int(os.getenv("AGENT_MAIN_MAX_TASKS", "8"))))
    # Character limits are secondary protection; token limits govern model calls.
    MAIN_CONTEXT_MAX_CHARS: int = max(8000, int(os.getenv("AGENT_MAIN_CONTEXT_MAX_CHARS", "1048576")))
    MAIN_OUTPUT_MAX_CHARS: int = max(1000, int(os.getenv("AGENT_MAIN_OUTPUT_MAX_CHARS", "65536")))
    TASK_RESULT_MAX_CHARS: int = max(1000, int(os.getenv("AGENT_TASK_RESULT_MAX_CHARS", "131072")))
    DEPENDENCY_MAX_CHARS: int = max(1000, int(os.getenv("AGENT_DEPENDENCY_MAX_CHARS", "524288")))
    # Application budgets, deliberately below the provider's maximum context.
    MAIN_CONTEXT_MAX_TOKENS: int = max(4096, int(os.getenv("AGENT_MAIN_CONTEXT_MAX_TOKENS", "131072")))
    MAIN_OUTPUT_MAX_TOKENS: int = max(256, int(os.getenv("AGENT_MAIN_OUTPUT_MAX_TOKENS", "8192")))
    WORKER_OUTPUT_MAX_TOKENS: int = max(256, int(os.getenv("AGENT_WORKER_OUTPUT_MAX_TOKENS", "16384")))
    CONTEXT_SAFETY_TOKENS: int = max(256, int(os.getenv("AGENT_CONTEXT_SAFETY_TOKENS", "8192")))
    CONTEXT_COMPACT_TRIGGER_TOKENS: int = max(1024, int(os.getenv("AGENT_CONTEXT_COMPACT_TRIGGER_TOKENS", "98304")))
    CONTEXT_COMPACT_TARGET_TOKENS: int = max(512, int(os.getenv("AGENT_CONTEXT_COMPACT_TARGET_TOKENS", "65536")))
    CONTEXT_COMPACT_MIN_SAVING_TOKENS: int = max(1, int(os.getenv("AGENT_CONTEXT_COMPACT_MIN_SAVING_TOKENS", "4096")))
    AUXILIARY_HISTORY_MAX_TOKENS: int = max(512, int(os.getenv("AGENT_AUXILIARY_HISTORY_MAX_TOKENS", "32768")))
    HISTORY_RECENT_TOKENS: int = max(256, int(os.getenv("AGENT_HISTORY_RECENT_TOKENS", "24576")))
    ARTICLE_CONTEXT_MAX_TOKENS: int = max(256, min(32768, int(os.getenv("AGENT_ARTICLE_CONTEXT_MAX_TOKENS", "8192"))))
    SUMMARY_MAX_TOKENS: int = max(128, int(os.getenv("AGENT_SUMMARY_MAX_TOKENS", "4096")))
    SUMMARY_INPUT_MAX_TOKENS: int = max(1024, int(os.getenv("AGENT_SUMMARY_INPUT_MAX_TOKENS", "32768")))
    SUMMARY_MAX_CALLS: int = max(1, min(16, int(os.getenv("AGENT_SUMMARY_MAX_CALLS", "8"))))
    SUMMARY_TIMEOUT_SECONDS: int = max(1, int(os.getenv("AGENT_SUMMARY_TIMEOUT_SECONDS", "45")))
    SUBAGENT_CONCURRENCY: int = max(1, min(8, int(os.getenv("AGENT_SUBAGENT_CONCURRENCY", "3"))))
    RETRIEVAL_CONCURRENCY: int = max(1, min(8, int(os.getenv("AGENT_RETRIEVAL_CONCURRENCY", "4"))))
    RETRIEVAL_TIMEOUT_SECONDS: int = max(1, int(os.getenv("AGENT_RETRIEVAL_TIMEOUT_SECONDS", "30")))
    GROUNDING_TIMEOUT_SECONDS: int = max(1, min(60, int(os.getenv('AGENT_GROUNDING_TIMEOUT_SECONDS', '25'))))
    GROUNDING_OUTPUT_MAX_TOKENS: int = max(1024, min(16384, int(os.getenv('AGENT_GROUNDING_OUTPUT_MAX_TOKENS', '4096'))))
    MEMORY_INPUT_MAX_TOKENS: int = max(1024, int(os.getenv("AGENT_MEMORY_INPUT_MAX_TOKENS", "16384")))
    MEMORY_OUTPUT_MAX_TOKENS: int = max(256, int(os.getenv("AGENT_MEMORY_OUTPUT_MAX_TOKENS", "2048")))
    BACKGROUND_JOB_MAX_ATTEMPTS: int = max(1, min(20, int(os.getenv("AGENT_BACKGROUND_JOB_MAX_ATTEMPTS", "8"))))
    AGENT_WEB_SEARCH_ENABLED: bool = os.getenv("AGENT_WEB_SEARCH_ENABLED", "true").strip().lower() in ("true", "1", "yes")
    APPROVAL_TIMEOUT_SECONDS: int = int(os.getenv("AGENT_APPROVAL_TIMEOUT_SECONDS", "86400"))
    # DeepSeek API
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
    
    # DashScope (阿里云 Reranker)
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
    
    # Elasticsearch
    ES_HOST: str = os.getenv("ES_HOST", "localhost")
    ES_PORT: int = int(os.getenv("ES_PORT", "9200"))
    
    # Redis（会话缓存等，跟 Java 共用同一个）
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD")

    # Redis Stack（LangGraph Checkpoint 专用，需要 RediSearch 模块）
    REDIS_STACK_HOST: str = os.getenv("REDIS_STACK_HOST", "localhost")
    REDIS_STACK_PORT: int = int(os.getenv("REDIS_STACK_PORT", "6379"))
    REDIS_STACK_DB: int = int(os.getenv("REDIS_STACK_DB", "0"))
    REDIS_STACK_PASSWORD: str = os.getenv("REDIS_STACK_PASSWORD")
    
    # DeepSeek Search / Fetch 与模型共用 API Key，工具端点独立于聊天代理地址。
    DEEPSEEK_TOOLS_BASE_URL: str = os.getenv("DEEPSEEK_TOOLS_BASE_URL", "https://api.deepseek.com/v1")
    
    # RAG 参数
    COARSE_TOP_K: int = max(1, min(100, int(os.getenv("COARSE_TOP_K", "20"))))
    QUERY_VECTOR_CACHE_CAPACITY: int = max(0, min(4096, int(os.getenv("AGENT_QUERY_VECTOR_CACHE_CAPACITY", "512"))))
    QUERY_VECTOR_CACHE_TTL_SECONDS: int = max(1, int(os.getenv("AGENT_QUERY_VECTOR_CACHE_TTL_SECONDS", "600")))
    STREAM_COALESCE_MS: int = max(0, min(500, int(os.getenv("AGENT_STREAM_COALESCE_MS", "120"))))
    COARSE_SIMILARITY_THRESHOLD: float = 0.5
    RERANK_TOP_K: int = max(1, min(20, int(os.getenv("RERANK_TOP_K", "5"))))
    RELEVANCE_THRESHOLD: float = 0.3

    ZHIPUAI_API_KEY: str = os.getenv("ZHIPUAI_API_KEY", "")
    ZHIPU_EMBEDDING_MODEL: str = os.getenv("ZHIPU_EMBEDDING_MODEL", "embedding-3")
    ZHIPU_EMBEDDING_DIMENSIONS: int = int(os.getenv("ZHIPU_EMBEDDING_DIMENSIONS", "2048"))

    # 文件上传
    FILE_UPLOAD_PATH: str = os.getenv("FILE_UPLOAD_PATH", "E:/easyjob/uploads")
    FILE_BASE_URL: str = os.getenv("FILE_BASE_URL", "")  # 生产环境填公网域名

    # MySQL
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DB: str = os.getenv("MYSQL_DB", "easyjob")

    MCP_SERVERS_JSON: str = os.getenv("MCP_SERVERS_JSON", "{}")
    @property
    def mysql_url(self) -> str:
        """databases 库用的连接字符串"""
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
            "?charset=utf8mb4"
        )
settings = Settings()

def get_llm(temperature: float = 0.7, **kwargs):
    # DeepSeek V4 系列的模型默认开启 thinking，会在多轮调用里要求回传 reasoning_content；
    # langchain-openai 当前版本不会自动保留 reasoning_content，所以显式关掉思考模式最稳
    extra_body = kwargs.pop("extra_body", {}) or {}
    extra_body.setdefault("thinking", {"type": "disabled"})

    return ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=temperature,
        extra_body=extra_body,
        **kwargs,
    )
