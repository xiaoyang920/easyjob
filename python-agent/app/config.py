"""
配置管理
对应 Java: application.yml + @Value 注入
"""
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()


class Settings:
    # DeepSeek API
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    
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
    
    # 博查搜索
    BOCHA_API_KEY: str = os.getenv("BOCHA_API_KEY", "")
    
    # RAG 参数
    COARSE_TOP_K: int = 5
    COARSE_SIMILARITY_THRESHOLD: float = 0.5
    RERANK_TOP_K: int = 5
    RELEVANCE_THRESHOLD: float = 0.3

    ZHIPUAI_API_KEY: str = os.getenv("ZHIPUAI_API_KEY", "")
    ZHIPU_EMBEDDING_MODEL: str = os.getenv("ZHIPU_EMBEDDING_MODEL", "embedding-3")
    ZHIPU_EMBEDDING_DIMENSIONS: int = int(os.getenv("ZHIPU_EMBEDDING_DIMENSIONS", "2048"))
    ZHIPU_VISION_MODEL: str = os.getenv("ZHIPU_VISION_MODEL", "glm-4.6v")

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

    return init_chat_model(
        model="deepseek-v4-flash",
        model_provider="openai",  # DeepSeek 兼容 OpenAI 协议
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=temperature,
        extra_body=extra_body,
        **kwargs,
    )

def get_vision_llm(**kwargs):
    """GLM-4V 视觉模型"""
    return init_chat_model(
        model=settings.ZHIPU_VISION_MODEL,
        model_provider="openai",
        api_key=settings.ZHIPUAI_API_KEY,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        **kwargs,
    )