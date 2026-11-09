# Elasticsearch 搜索接口文档

## 概述

基于 Elasticsearch 实现的全文搜索功能，支持文章搜索和用户搜索。

---

## 1. 统一搜索接口

### 请求

```
GET /api/search
```

### 请求参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| keyword | String | 是 | 搜索关键词 |
| type | String | 否 | 搜索类型：`article`（文章，默认）、`user`（用户） |
| sort | String | 否 | 排序方式：`relevance`（相关度，默认）、`latest`（最新）、`hottest`（最热）、`liked`（点赞） |
| page | Integer | 否 | 页码，默认1 |
| size | Integer | 否 | 每页条数，默认10，最大50 |

### 响应示例

#### 文章搜索结果 (type=article)

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "total": 100,
    "pages": 10,
    "current": 1,
    "records": [
      {
        "articleId": 1,
        "title": "Spring Boot 入门教程",
        "summary": "本文介绍Spring Boot的基础知识...",
        "content": "文章内容（截取前200字）...",
        "coverImage": "/uploads/covers/2026/01/xxx.jpg",
        "authorId": 1,
        "authorName": "张三",
        "authorAvatar": "/uploads/avatars/xxx.jpg",
        "viewCount": 1000,
        "likeCount": 50,
        "collectCount": 20,
        "createTime": "2026-01-14T10:00:00"
      }
    ]
  }
}
```

#### 用户搜索结果 (type=user)

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "total": 50,
    "pages": 5,
    "current": 1,
    "records": [
      {
        "userId": 1,
        "nickName": "张三",
        "avatar": "/uploads/avatars/xxx.jpg",
        "personIntroduction": "全栈开发工程师",
        "followerCount": 100,
        "articleCount": 20,
        "isFollowing": false
      }
    ]
  }
}
```

---

## 2. 搜索建议接口（可选）

### 请求

```
GET /api/search/suggest
```

### 请求参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| keyword | String | 是 | 搜索关键词前缀 |
| size | Integer | 否 | 返回建议数量，默认5 |

### 响应示例

```json
{
  "code": 200,
  "message": "success",
  "data": [
    "Spring Boot",
    "Spring Cloud",
    "Spring Security"
  ]
}
```

---

## 3. 热门搜索接口（可选）

### 请求

```
GET /api/search/hot
```

### 请求参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| size | Integer | 否 | 返回数量，默认10 |

### 响应示例

```json
{
  "code": 200,
  "message": "success",
  "data": [
    { "keyword": "Java", "count": 5000 },
    { "keyword": "Python", "count": 4500 },
    { "keyword": "Vue", "count": 4000 }
  ]
}
```

---

## 4. Elasticsearch 索引设计

### 4.1 文章索引 (article)

```json
PUT /article
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "analysis": {
      "analyzer": {
        "ik_smart_pinyin": {
          "type": "custom",
          "tokenizer": "ik_smart",
          "filter": ["lowercase"]
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "articleId": { "type": "long" },
      "title": { 
        "type": "text", 
        "analyzer": "ik_max_word",
        "search_analyzer": "ik_smart"
      },
      "summary": { 
        "type": "text", 
        "analyzer": "ik_max_word" 
      },
      "content": { 
        "type": "text", 
        "analyzer": "ik_max_word" 
      },
      "coverImage": { "type": "keyword" },
      "authorId": { "type": "long" },
      "authorName": { 
        "type": "text",
        "fields": {
          "keyword": { "type": "keyword" }
        }
      },
      "authorAvatar": { "type": "keyword" },
      "categoryId": { "type": "long" },
      "tags": { "type": "keyword" },
      "viewCount": { "type": "integer" },
      "likeCount": { "type": "integer" },
      "collectCount": { "type": "integer" },
      "status": { "type": "integer" },
      "createTime": { "type": "date" },
      "updateTime": { "type": "date" }
    }
  }
}
```

### 4.2 用户索引 (user)

```json
PUT /user
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 0
  },
  "mappings": {
    "properties": {
      "userId": { "type": "long" },
      "nickName": { 
        "type": "text",
        "analyzer": "ik_max_word",
        "fields": {
          "keyword": { "type": "keyword" }
        }
      },
      "avatar": { "type": "keyword" },
      "personIntroduction": { 
        "type": "text", 
        "analyzer": "ik_max_word" 
      },
      "followerCount": { "type": "integer" },
      "followingCount": { "type": "integer" },
      "articleCount": { "type": "integer" },
      "createTime": { "type": "date" }
    }
  }
}
```

---

## 5. 后端实现建议

### 5.1 依赖配置 (pom.xml)

```xml
<!-- Elasticsearch -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-data-elasticsearch</artifactId>
</dependency>
```

### 5.2 配置文件 (application.yml)

```yaml
spring:
  elasticsearch:
    uris: http://localhost:9200
    # 如果有认证
    # username: elastic
    # password: your_password
```

### 5.3 Controller 示例

```java
@RestController
@RequestMapping("/api/search")
public class SearchController {

    @Autowired
    private SearchService searchService;

    @GetMapping
    public ResponseVO<?> search(
            @RequestParam String keyword,
            @RequestParam(defaultValue = "article") String type,
            @RequestParam(defaultValue = "relevance") String sort,
            @RequestParam(defaultValue = "1") Integer page,
            @RequestParam(defaultValue = "10") Integer size) {
        
        if ("user".equals(type)) {
            return ResponseVO.success(searchService.searchUsers(keyword, sort, page, size));
        }
        return ResponseVO.success(searchService.searchArticles(keyword, sort, page, size));
    }
}
```

### 5.4 Service 核心逻辑

```java
@Service
public class SearchService {

    @Autowired
    private ElasticsearchRestTemplate esTemplate;

    public PageVO<ArticleSearchVO> searchArticles(String keyword, String sort, int page, int size) {
        // 构建查询
        NativeSearchQueryBuilder queryBuilder = new NativeSearchQueryBuilder();
        
        // 多字段搜索
        BoolQueryBuilder boolQuery = QueryBuilders.boolQuery()
            .should(QueryBuilders.matchQuery("title", keyword).boost(3.0f))
            .should(QueryBuilders.matchQuery("summary", keyword).boost(2.0f))
            .should(QueryBuilders.matchQuery("content", keyword))
            .should(QueryBuilders.matchQuery("authorName", keyword));
        
        queryBuilder.withQuery(boolQuery);
        
        // 排序
        switch (sort) {
            case "latest":
                queryBuilder.withSort(SortBuilders.fieldSort("createTime").order(SortOrder.DESC));
                break;
            case "hottest":
                queryBuilder.withSort(SortBuilders.fieldSort("viewCount").order(SortOrder.DESC));
                break;
            case "liked":
                queryBuilder.withSort(SortBuilders.fieldSort("likeCount").order(SortOrder.DESC));
                break;
            default: // relevance
                queryBuilder.withSort(SortBuilders.scoreSort().order(SortOrder.DESC));
        }
        
        // 分页
        queryBuilder.withPageable(PageRequest.of(page - 1, size));
        
        // 高亮
        queryBuilder.withHighlightFields(
            new HighlightBuilder.Field("title").preTags("<mark>").postTags("</mark>"),
            new HighlightBuilder.Field("summary").preTags("<mark>").postTags("</mark>")
        );
        
        // 执行搜索
        SearchHits<ArticleDocument> hits = esTemplate.search(queryBuilder.build(), ArticleDocument.class);
        
        // 处理结果...
        return pageVO;
    }
}
```

---

## 6. 数据同步方案

### 方案一：双写（推荐简单场景）

在数据库操作后同步更新ES：

```java
@Service
public class ArticleServiceImpl {
    
    @Autowired
    private ArticleEsRepository esRepository;
    
    @Transactional
    public void saveArticle(Article article) {
        // 1. 保存到MySQL
        articleMapper.insert(article);
        
        // 2. 同步到ES
        esRepository.save(convertToDocument(article));
    }
}
```

### 方案二：Canal + MQ（推荐生产环境）

使用 Canal 监听 MySQL binlog，通过消息队列异步同步到 ES。

---

## 7. 错误码

| 错误码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 参数错误（如keyword为空） |
| 500 | 服务器内部错误 |
| 503 | ES服务不可用 |
