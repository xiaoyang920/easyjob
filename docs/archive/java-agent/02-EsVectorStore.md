> 历史归档：本文包含已移除的 Java Agent 实现，仅供学习参考。当前结构见[运行架构](../../architecture/current-runtime.md)。

# ES向量索引配置

## 一、索引常量

```java
public class AgentEsConstants {
    public static final String VECTOR_INDEX = "article_vectors";
    
    // Settings: 1分片, 0副本, ik分词器
    // Mapping核心字段:
    // - content_vector: dense_vector, dims=2048, similarity=cosine
    // - article_id, title, chunk_content, like_count, collect_count
}
```

## 二、EsVectorStore核心方法

- initIndex(): 创建索引
- saveChunks(chunks): 批量保存向量
- search(query, topK, threshold): KNN+热度混合评分
- deleteByArticleId(id): 删除文章向量

混合评分: finalScore = knnScore * 0.7 + popularityScore * 0.3

## 三、DocumentChunkService

TokenTextSplitter配置:
- chunkSize: 500
- minChunkSizeChars: 100
- maxNumChunks: 50

流程: HTML -> Jsoup清洗 -> 分块 -> DocumentChunk列表
