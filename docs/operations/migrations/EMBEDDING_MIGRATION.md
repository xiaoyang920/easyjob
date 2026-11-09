# Python Agent Embedding 迁移说明

## 1. 你原 Java 项目里用的是什么

已经从现有 Java 项目确认：

- Embedding 接入方式：`Spring AI`
- 供应商：`智谱 AI`
- Java 服务类：`src/main/java/com/easyjob/agent/service/ZhipuEmbeddingService.java`
- Spring 依赖：`spring-ai-starter-model-zhipuai`
- 配置位置：`src/main/resources/application.yml`
- Embedding 模型：`embedding-3`
- 向量维度：`2048`

对应配置大致如下：

```yaml
spring:
  ai:
    zhipuai:
      api-key: your-zhipu-api-key
      embedding:
        options:
          model: embedding-3
          dimensions: 2048
```

Java 代码中实际调用的是 Spring AI 提供的 `EmbeddingModel`：

```java
EmbeddingResponse response = embeddingModel.embedForResponse(List.of(text));
float[] embedding = response.getResult().getOutput();
```

也就是说，你原项目不是本地向量模型，不是手写向量，也不是 OpenAI Embedding，而是：

- **智谱 Embedding API**
- **模型名 `embedding-3`**
- **2048 维向量**

---

## 2. 为什么 Python Agent 里当前的 `embedding.py` 必须替换

当前 `python-agent/app/services/embedding.py` 只是一个临时兜底实现：

- 用 `md5 hash` 把词打到固定槽位
- 生成 2048 维伪向量
- 只是为了让 `EsVectorStore.search()` 这条链路先跑通

它的问题很明显：

- **不具备真实语义能力**
- **和 Java 侧入库时用的向量空间不一致**
- **如果 ES 中历史向量是用智谱 `embedding-3` 生成的，Python 侧再用 hash 向量去检索，结果会严重失真**

这点非常关键：

### 向量检索要求“查询向量”和“索引向量”来自同一模型

如果文章入库时用的是：

- 智谱 `embedding-3`

那查询时也必须用：

- 智谱 `embedding-3`

否则相似度空间根本不一致，召回结果基本不可信。

---

## 3. Python 侧应该怎么迁移

最稳妥的方案是：

### 方案 A：Python 直接调用智谱 Embedding API

优点：

- 与 Java 现有向量索引完全保持一致
- 不需要重建 `article_vectors` 索引
- 迁移成本最低

这也是最推荐的方案。

### 方案 B：Python 换成别的 Embedding 模型

比如：

- OpenAI `text-embedding-3-large`
- 通义 embedding
- BGE / m3e 本地模型

这类方案只有在你准备 **整库重建向量索引** 时才合适。

因为一旦换模型，就必须重新：

- 重新分块
- 重新生成所有 chunk 向量
- 重建 `article_vectors`

否则查询向量和库里旧向量不在同一个语义空间。

---

## 4. 推荐的 Python 配置方式

在 `python-agent/.env` 中新增：

```env
ZHIPU_API_KEY=your-zhipu-api-key
ZHIPU_EMBEDDING_MODEL=embedding-3
ZHIPU_EMBEDDING_DIMENSIONS=2048
```

同时在 `app/config.py` 中加入：

```python
ZHIPU_API_KEY: str = os.getenv("ZHIPU_API_KEY", "")
ZHIPU_EMBEDDING_MODEL: str = os.getenv("ZHIPU_EMBEDDING_MODEL", "embedding-3")
ZHIPU_EMBEDDING_DIMENSIONS: int = int(os.getenv("ZHIPU_EMBEDDING_DIMENSIONS", "2048"))
```

---

## 5. 推荐的 Python 实现思路

你可以把当前的 `EmbeddingService` 替换成真实 HTTP 调用版本。

实现目标：

- 输入：文本 `str`
- 输出：`List[float]`
- 模型：`embedding-3`
- 维度：`2048`
- 与 Java 原逻辑保持一致

伪代码如下：

```python
class EmbeddingService:
    def embed(self, text: str) -> List[float]:
        resp = httpx.post(
            "智谱 Embedding API 地址",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "embedding-3",
                "input": text,
                "dimensions": 2048,
            },
        )
        return resp.json()["data"][0]["embedding"]
```

注意事项：

- 不要再返回 hash 向量
- 返回维度必须和 ES 索引一致
- 批量接口 `embed_batch()` 最好也一起支持
- 要增加超时、异常处理和降级日志

---

## 6. 对 `EsVectorStore.search()` 的影响

`app/clients/es_client.py` 中这段逻辑：

```python
query_vector = self.embedding_service.embed(query)
```

这里生成的向量必须和 `article_vectors` 里存储的 `content_vector` 同源。

也就是：

- Java 入库时如果用智谱 `embedding-3`
- Python 查询时也必须用智谱 `embedding-3`

这样 `knn` 检索才有意义。

---

## 7. 当前迁移建议

建议按下面顺序做：

1. 保持 Java 和 Python 使用同一个 Embedding 模型：`embedding-3`
2. 替换 `python-agent/app/services/embedding.py`
3. 更新 `python-agent/.env.example`
4. 如果后续换模型，再统一重建向量索引

---

## 8. 一句话结论

你原项目里真实用的是：

- **智谱 Embedding `embedding-3`**
- **2048 维**
- **Spring AI 封装调用**

所以 Python Agent 里当前的假向量实现只是临时占位，**正式迁移时必须换成智谱 `embedding-3` 的真实调用**，否则向量检索结果不可靠。
