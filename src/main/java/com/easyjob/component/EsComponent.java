package com.easyjob.component;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch._types.SortOptions;
import co.elastic.clients.elasticsearch._types.SortOrder;
import co.elastic.clients.elasticsearch.core.SearchResponse;
import co.elastic.clients.json.JsonData;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.easyjob.constants.EsConstants;
import com.easyjob.dto.ArticleEsDTO;
import com.alibaba.fastjson2.JSON;
import com.easyjob.entity.Article;
import com.easyjob.entity.User;
import com.easyjob.enums.SearchOrderTypeEnum;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.UserMapper;
import com.easyjob.utils.StringTools;
import com.easyjob.vo.ArticleSearchVO;
import com.easyjob.vo.PageVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import java.io.IOException;
import java.io.StringReader;
import java.util.*;
import java.util.function.Function;
import java.util.stream.Collectors;

import static com.easyjob.constants.EsConstants.INDEX_SETTING;
import static com.easyjob.constants.EsConstants.MAPPING_TEMPLATE;


@Slf4j
@Component
public class EsComponent {

    private static final String INDEX_NAME = "article";

    @Autowired
    private UserMapper userMapper;
    
    @Autowired
    private ElasticsearchClient client;


    /**
     * 创建索引
     */
    public void createIndex() {
        try {
            // 检查索引是否已存在
            boolean exists = client.indices().exists(e -> e.index(INDEX_NAME)).value();

            if (exists) {
                log.info("ES索引 [article] 已存在，跳过创建");
                return;
            }
            // 创建索引请求
            client.indices().create(c -> c
                    .index(INDEX_NAME)
                    // 1. 设置 settings (如果你有 settings 的 JSON 常量)
                    .settings(s -> s.withJson(new StringReader(INDEX_SETTING)))
                    // 2. 设置 mappings (使用你在 EsConstants 里定义的 MAPPING_TEMPLATE)
                    .mappings(m -> m.withJson(new StringReader(EsConstants.MAPPING_TEMPLATE)))
            );
            log.info("ES索引 [article] 创建成功");
        } catch (Exception e) {
            log.error("创建ES索引失败", e);
        }
    }
    /**
     * 保存或更新文档到ES
     * @param article 文章实体
     */
    public void saveDoc(Article article){
        try {

            ArticleEsDTO articleEsDTO = new ArticleEsDTO(article);
            String docId = article.getArticleId().toString();
            boolean exists = client.exists(e -> e.index(INDEX_NAME).id(docId)).value();
            // 判断文档是否存在
            if(exists){
                client.update(u->u
                        .index(INDEX_NAME)
                        .id(docId)
                        .script(s -> s.source("def previous = ctx._source.viewCount; ctx._source.putAll(params.document); if (previous != null && (ctx._source.viewCount == null || ctx._source.viewCount < previous)) { ctx._source.viewCount = previous; }")
                            .params("document", JsonData.of(articleEsDTO))),
                        ArticleEsDTO.class
                );
            }else {
                // Rebuilt documents keep the authoritative counters from MySQL.
                client.index(i -> i
                        .index(INDEX_NAME)
                        .id(docId)
                        .document(articleEsDTO)
                );
                log.info("文档添加成功，articleId={}", docId);
            }
        } catch (IOException e) {
            log.error("保存到es失败，articleId={}", article.getArticleId(), e);
            throw new BusinessException("保存到es失败");
        }
    }

    /**
     * 删除文档
     * @param articleId 文章ID
     */
    public void deleteDoc(Long articleId){
        try {
            client.delete(d->d
                    .index(INDEX_NAME)
                    .id(articleId.toString())
            );
            log.info("文档删除成功，articleId={}", articleId);
        } catch (Exception e) {
            log.error("删除文档失败，articleId={}", articleId, e);
            throw new BusinessException("删除文档失败");
        }
    }

    /**
     * 增量更新文档的数值字段
     * @param articleId 文章ID
     * @param fieldName 字段名（viewCount、likeCount、collectCount等）
     * @param count 增量值（正数增加，负数减少）
     */
    public boolean syncViewCount(String articleId, int count) {
        try {
            client.update(u -> u.index(INDEX_NAME).id(articleId).script(s -> s
                    .source("if (ctx._source.viewCount == null || ctx._source.viewCount < params.count) { ctx._source.viewCount = params.count; }")
                    .params("count", co.elastic.clients.json.JsonData.of(count))), ArticleEsDTO.class);
            return true;
        } catch (Exception exception) {
            log.warn("阅读量已提交MySQL，ES计数更新暂未完成: articleId={}, type={}", articleId, exception.getClass().getSimpleName());
            return false;
        }
    }

    public void updateDocCount(String articleId, String fieldName, Integer count){
        try {
            // 脚本：count 字段 += params.count；null 时初始化为 0
            String scriptSource =
                    "if (ctx._source." + fieldName + " == null) { ctx._source." + fieldName + " = 0; } " +
                    "ctx._source." + fieldName + " += params.count";

            String scriptJson = String.format(
                "{\"script\":{\"source\":\"%s\",\"params\":{\"count\":%d}}}",
                scriptSource, count
            );

            client.update(u -> u
                    .index(INDEX_NAME)
                    .id(articleId)
                    .withJson(new StringReader(scriptJson)),
                    ArticleEsDTO.class);

            log.info("更新ES计数字段成功，articleId={}, field={}, count={}", articleId, fieldName, count);
        } catch (co.elastic.clients.elasticsearch._types.ElasticsearchException ese) {
            // 文档不存在时 ES 抛 document_missing_exception：
            // MySQL 里有文章但 ES 还没同步（MQ 索引消息丢失/未消费）。
            // 不做 upsert 创建残缺文档，避免 MySQL 和 ES 的字段不一致；
            // 等这篇文章重新被同步到 ES 后，后续浏览会正常累加。
            String msg = ese.getMessage() != null ? ese.getMessage() : "";
            if (msg.contains("document_missing_exception")) {
                log.warn("ES 中缺失文档，跳过计数更新，建议触发该文章的重新索引 | articleId={}, field={}",
                        articleId, fieldName);
            } else {
                log.warn("更新ES计数字段失败（已忽略），articleId={}, field={}, count={}, err={}",
                        articleId, fieldName, count, msg);
            }
        } catch (IOException e) {
            log.error("更新ES计数字段IO异常，articleId={}, field={}, count={}", articleId, fieldName, count, e);
            // 本地开发期不阻塞主业务；生产环境想严格校验可改回 throw
        }
    }

    /**
     * 搜索文章
     * @param highlight 是否高亮
     * @param keyword 关键词
     * @param orderType 排序类型
     * @param pageNo 页码
     * @param pageSize 每页数量
     * @return 分页结果
     */
    public PageVO<ArticleSearchVO> search(Boolean highlight, String keyword, Integer orderType, Integer pageNo, Integer pageSize){
        try {
            // 获取排序类型枚举
            SearchOrderTypeEnum searchOrderTypeEnum = SearchOrderTypeEnum.getByType(orderType);
            SearchResponse<ArticleEsDTO> response = client.search(s -> {
                        s.index(INDEX_NAME)
                                .from((pageNo - 1) * pageSize) // 分页：跳过多少条
                                .size(pageSize)                // 分页：取多少条
                                // --- 查询条件 (Query) ---
                                .query(q -> {
                                    if (StringTools.isEmpty(keyword)) {
                                        return q.matchAll(m -> m); // 关键词为空，查全部
                                    } else {
                                        return q.multiMatch(m -> m.query(keyword).fields("title", "tags")); // 多字段匹配
                                    }
                                })
                                // --- 高亮设置 (Highlight) ---
                                ;
                        if (highlight) {
                            s.highlight(h -> h.fields("title", f -> f
                                    .preTags("<span class='highlight'>")
                                    .postTags("</span>")
                            ));
                        }
                        if (searchOrderTypeEnum != null) {
                            // 第一个排序：业务排序（如发布时间）
                            s.sort(f -> f.field(fld -> fld.field(searchOrderTypeEnum.getField()).order(SortOrder.Desc)));
                        }

                        // 第二个排序：默认按相关性评分降序
                        s.sort(f -> f.field(fld -> fld.field("_score").order(SortOrder.Desc)));
                        return s;
                    }, ArticleEsDTO.class
            );
            // 3. 处理结果 (从 response 中提取命中记录)
            long total = response.hits().total().value();
            List<ArticleEsDTO> articles = response.hits().hits().stream()
                    .map(hit -> {
                        ArticleEsDTO a = hit.source();
                        // 处理高亮文本替换
                        if (highlight && hit.highlight().containsKey("title")) {
                            a.setTitle(hit.highlight().get("title").get(0));
                        }
                        return a;
                    }).collect(Collectors.toList());
            Set<Long> userIdSet = articles.stream()
                    .map(ArticleEsDTO::getUserId) // 假设你的 DTO 里 userId 是 Long 类型
                    .filter(Objects::nonNull)
                    .collect(Collectors.toSet());

            // 批量查询用户信息
            Map<Long, User> userMap = new HashMap<>();
            if (!userIdSet.isEmpty()) {
                List<User> userList = userMapper.selectList(
                    new LambdaQueryWrapper<User>().in(User::getUserId, userIdSet)
                );
                userMap = userList.stream()
                    .collect(Collectors.toMap(User::getUserId, Function.identity(), (v1, v2) -> v1));
            }
            
            // 转换为 VO
            List<ArticleSearchVO> voList = new ArrayList<>();
            for (ArticleEsDTO article :articles) {
                ArticleSearchVO vo = new ArticleSearchVO();
                vo.setArticleId(article.getArticleId().toString());
                vo.setTitle(article.getTitle());
                vo.setCoverImage(article.getCoverImage());
                vo.setSummary(article.getSummary());
                vo.setTags(article.getTags());
                vo.setIsOriginal(article.getIsOriginal());
                vo.setViewCount(article.getViewCount());
                vo.setLikeCount(article.getLikeCount());
                vo.setCollectCount(article.getCollectCount());
                vo.setCommentCount(article.getCommentCount());
                vo.setPublishTime(article.getPublishTime());
                
                // 设置作者信息
                if (article.getUserId() != null) {
                    Long userIdLong = article.getUserId();
                    vo.setUserId(userIdLong);
                    User user = userMap.get(userIdLong);
                    if (user != null) {
                        vo.setAuthorName(user.getNickName());
                        vo.setAuthorAvatar(user.getAvatar());
                    }
                }
                
                voList.add(vo);
            }
            
            // 计算总页数
            int totalPages = (int) ((total + pageSize - 1) / pageSize);
            
            return new PageVO<>(voList, total, (long) pageSize, (long) pageNo, (long) totalPages);
            
        } catch (Exception e){
            log.error("搜索失败", e);
            throw new BusinessException("搜索失败");
        }
    }
}
