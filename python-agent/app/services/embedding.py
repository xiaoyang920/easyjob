"""
Embedding 服务
对应 Java: ZhipuEmbeddingService.java

使用 LangChain 的 ZhipuAIEmbeddings 封装，调用智谱 embedding-3 模型。
与 Java 侧使用同一个模型，保证向量空间一致，KNN 检索才有意义。
"""
from langchain_community.embeddings import ZhipuAIEmbeddings

from app.config import settings
from app.services.dependency_policy import embedding_policy


class EmbeddingService:
    def __init__(self):
        self.client = ZhipuAIEmbeddings(
            model=settings.ZHIPU_EMBEDDING_MODEL,
            dimensions=settings.ZHIPU_EMBEDDING_DIMENSIONS,
            api_key=settings.ZHIPUAI_API_KEY,
        )
        # The async LangChain adapter runs this SDK in a thread. Bound the SDK
        # transport as well, so cancellation cannot leave an unbounded request.
        self.client.client.timeout = 8
        self.client.client.max_retries = 0

    def embed(self, text: str) -> list[float]:
        """单文本向量化，对应 Java: ZhipuEmbeddingService.embed()"""
        return self.client.embed_query(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量向量化，对应 Java: ZhipuEmbeddingService.embedBatch()"""
        return self.client.embed_documents(texts)

    async def aembed(self, text: str) -> list[float]:
        """异步版本"""
        return await embedding_policy.run(lambda: self.client.aembed_query(text))

    async def aembed_batch(self, texts: list[str]) -> list[list[float]]:
        """异步批量版本，一次 API 请求，比多次 aembed 更高效"""
        return await embedding_policy.run(lambda: self.client.aembed_documents(texts))
