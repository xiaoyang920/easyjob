package com.easyjob.constants;

/**
 * ES向量索引常量
 */
public class AgentEsConstants {
    public static final String CHUNK_METADATA_MAPPING = """
        {"properties": {
            "source_hash": {"type": "keyword"},
            "chunker_version": {"type": "keyword"},
            "chunk_type": {"type": "keyword"},
            "section_path": {"type": "text", "analyzer": "ik_smart"},
            "category_id": {"type": "long"},
            "publish_time": {"type": "date"}
        }}
        """;
    
    /**
     * 向量索引名称
     */
    public static final String VECTOR_INDEX = "article_vectors";
    
    /**
     * 索引Settings
     * - number_of_shards: 分片数，单机设为1即可
     * - number_of_replicas: 副本数，开发环境设为0
     */
    public static final String LEGACY_VECTOR_INDEX_SETTINGS = """
        {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "analyzer": {
                    "ik_smart_analyzer": {
                        "type": "custom",
                        "tokenizer": "ik_smart"
                    }
                }
            }
        }
        """;
    
    /**
     * 索引Mapping
     * 
     * 【核心字段说明】
     * - chunk_id: 文档块唯一ID (article_id + chunker_version + source_hash + chunk_index)
     * - article_id: 原文章ID，用于关联
     * - chunk_content: 文档块文本内容
     * - content_vector: 文本的向量表示 (dense_vector类型)
     * - source_type: 来源类型 (article/external_doc)
     * 
     * 【dense_vector配置】
     * - dims: 2048 (必须与Embedding模型输出维度一致)
     * - index: true (建立索引，支持KNN搜索)
     * - similarity: cosine (余弦相似度，最常用)
     */
    public static final String LEGACY_VECTOR_INDEX_MAPPING = """
        {
            "properties": {
                "chunk_id": {
                    "type": "keyword"
                },
                "article_id": {
                    "type": "keyword"
                },
                "user_id": {
                    "type": "long"
                },
                "title": {
                    "type": "text",
                    "analyzer": "ik_smart"
                },
                "section_path": {
                    "type": "text",
                    "analyzer": "ik_smart"
                },
                "chunk_content": {
                    "type": "text",
                    "analyzer": "ik_smart"
                },
                "chunk_index": {
                    "type": "integer"
                },
                "content_vector": {
                    "type": "dense_vector",
                    "dims": 2048,
                    "index": true,
                    "similarity": "cosine"
                },
                "source_type": {
                    "type": "keyword"
                },
                "create_time": {
                    "type": "date",
                    "format": "yyyy-MM-dd HH:mm:ss||epoch_millis"
                },
                "tags": {
                    "type": "keyword"
                },
                "like_count": {
                    "type": "integer"
                },
                "collect_count": {
                    "type": "integer"
                }
            }
        }
        """;
    public static final String VECTOR_INDEX_SETTINGS=ChineseSearchSchema.settings(LEGACY_VECTOR_INDEX_SETTINGS);
    public static final String VECTOR_INDEX_MAPPING=ChineseSearchSchema.mapping(LEGACY_VECTOR_INDEX_MAPPING,"title","chunk_content","section_path");
}
