package com.easyjob.service.impl;

import cn.hutool.core.bean.BeanUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.component.EsComponent;
import com.easyjob.component.RedisComponent;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.dto.ArticleCreateDTO;
import com.easyjob.dto.ArticleVectorMessage;
import com.easyjob.dto.ShareDTO;
import com.easyjob.entity.Article;
import com.easyjob.entity.ArticleComment;
import com.easyjob.entity.UserAction;
import com.easyjob.enums.ActionTypeEnum;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleCommentMapper;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.ArticleTagMapper;
import com.easyjob.mapper.UserActionMapper;
import com.easyjob.mapper.UserMapper;
import com.easyjob.service.ArticleService;
import com.easyjob.service.ArticleTagService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ArticleDetailVO;
import com.easyjob.vo.ArticleListVO;
import com.easyjob.vo.PageVO;
import com.easyjob.vo.TagVO;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.easyjob.constants.RedisConstants;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
public class ArticleServiceImpl extends ServiceImpl<ArticleMapper,Article> implements ArticleService {
    @Autowired
    private ArticleMapper articleMapper;
    @Autowired
    private UserMapper userMapper;
    @Autowired
    private UserActionMapper userActionMapper;
    @Autowired
    private EsComponent esComponent;
    @Autowired
    private RedisComponent redisComponent;
    @Autowired
    private ArticleCommentMapper articleCommentMapper;
    @Autowired
    private ArticleTagService articleTagService;
    @Autowired
    private ArticleTagMapper articleTagMapper;
    @Autowired
    private RabbitTemplate rabbitTemplate;
    /**
     * 获取用户文章列表
     * @param userId
     * @param page
     * @param size
     * @param order 排序方式：latest-最新发布，hottest-最多播放，like-最多点赞，collect-最多收藏
     * @return
     */
    @Override
    public Map<String, Object> getUserArticles(Long userId, Integer page, Integer size, String order) {
        // 限制每页最多 20 条，防止一次查询过多
        if (size > 20) {
            size = 20;
        }
        
        // 构建查询条件
        LambdaQueryWrapper<Article> queryWrapper = new LambdaQueryWrapper<Article>()
            .eq(Article::getUserId, userId)
            .eq(Article::getStatus, 1);  // 只查已发布
        
        // 根据order参数设置排序
        if ("hottest".equals(order)) {
            queryWrapper.orderByDesc(Article::getViewCount);
        } else if ("like".equals(order)) {
            queryWrapper.orderByDesc(Article::getLikeCount);
        } else if ("collect".equals(order)) {
            queryWrapper.orderByDesc(Article::getCollectCount);
        } else {
            // 默认按发布时间降序
            queryWrapper.orderByDesc(Article::getPublishTime);
        }
        
        IPage<Article> articleIPage = articleMapper.selectPage(
            new Page<>(page, size),
            queryWrapper
        );
        
        List<ArticleListVO> articleListVOList = articleIPage.getRecords().stream().map(article -> {
            ArticleListVO articleListVO = new ArticleListVO();
            articleListVO.setArticleId(String.valueOf(article.getArticleId()));
            articleListVO.setTitle(article.getTitle());
            articleListVO.setCoverImage(article.getCoverImage());
            articleListVO.setViewCount(article.getViewCount());
            articleListVO.setLikeCount(article.getLikeCount());
            articleListVO.setPublishTime(article.getPublishTime().toString());
            articleListVO.setCollectCount(article.getCollectCount());
            return articleListVO;
        }).collect(Collectors.toList());
        
        Map<String,Object> result = new HashMap<>();
        result.put("total", articleIPage.getTotal());
        result.put("records", articleListVOList);
        result.put("pages", articleIPage.getPages());
        result.put("current", articleIPage.getCurrent());
        return result;
    }
    /**
     * 保存文章
     * @param article
     */
    @Override
    @Transactional
    public void saveArticle(ArticleCreateDTO article) {
        if(article.getCategoryId()== null||article.getCategoryId().isEmpty()){
            throw new BusinessException("请选择分类");
        }
        Article data = BeanUtil.copyProperties(article, Article.class);
        data.setUserId(UserContext.getUserId());
        data.setCreateTime(LocalDateTime.now());
        data.setUpdateTime(LocalDateTime.now());
        if(article.getStatus() == 1){
            data.setPublishTime(LocalDateTime.now());
        }
        articleMapper.insert(data);
        
        // 处理标签关联
        if (article.getTagNames() != null && !article.getTagNames().isEmpty()) {
            articleTagService.handleArticleTags(data.getArticleId(), article.getTagNames());
        }
        
        // 同步到ES搜索索引
        esComponent.saveDoc(data);
        userMapper.changeArticleCount(UserContext.getUserId(), 1);
        
        // 发布状态的文章需要进行向量化处理
        if (article.getStatus() == 1) {
            rabbitTemplate.convertAndSend(
                    RabbitMqConstants.TOPIC_EXCHANGE,
                    RabbitMqConstants.ROUTING_KEY_PUBLISH,
                    new ArticleVectorMessage(data.getArticleId(), "PUBLISH")
            );
        }
    }

    /**
     * 获取文章详情
     * 采用"静态走缓存，动态查数据库"的策略
     * @param articleId
     * @return
     */
    @Override
    public ArticleDetailVO getArticleById(Long articleId) {
        // 1. 先从缓存拿静态详情（标题、内容、作者等）
        ArticleDetailVO articleDetailVO = redisComponent.getArticleDetail(articleId);
            
        if (articleDetailVO == null) {
            // 2. 缓存缺失，查数据库
            articleDetailVO = articleMapper.selectArticleAndUser(articleId);
            if (articleDetailVO == null) {
                return null;
            }
            articleDetailVO.setArticleId(String.valueOf(articleId));
                
            // 3. 回填缓存
            redisComponent.saveArticleDetail(articleId, articleDetailVO);
        }
            
        // 4. 每次都从数据库查询最新的动态计数（点赞、收藏、分享、浏览、评论）
        Article article = articleMapper.selectOne(
                new LambdaQueryWrapper<Article>()
                        .select(Article::getLikeCount, Article::getCollectCount, 
                                Article::getShareCount, Article::getViewCount, Article::getCommentCount)
                        .eq(Article::getArticleId, articleId)
        );
        if (article != null) {
            articleDetailVO.setLikeCount(article.getLikeCount());
            articleDetailVO.setCollectCount(article.getCollectCount());
            articleDetailVO.setShareCount(article.getShareCount());
            articleDetailVO.setViewCount(article.getViewCount());
            articleDetailVO.setCommentCount(article.getCommentCount());
        }
            
        // 5. 查询文章标签列表
        List<TagVO> tags = articleTagMapper.getTagsByArticleId(articleId);
        articleDetailVO.setTags(tags);
    
        // 6. 设置当前用户的个性化状态（这部分不进缓存）
        Long currentUserId = UserContext.getUserId();
        if (currentUserId != null) {
            List<UserAction> actions = userActionMapper.selectList(
                    new LambdaQueryWrapper<UserAction>()
                            .eq(UserAction::getArticleId, String.valueOf(articleId))
                            .eq(UserAction::getUserId, String.valueOf(currentUserId))
                            .eq(UserAction::getCommentId, 0)
                            .in(UserAction::getActionType, 2, 3)
            );
            if (actions != null && !actions.isEmpty()) {
                boolean hasLiked = actions.stream().anyMatch(a -> Integer.valueOf(2).equals(a.getActionType()));
                boolean hasCollected = actions.stream().anyMatch(a -> Integer.valueOf(3).equals(a.getActionType()));
                articleDetailVO.setHasLiked(hasLiked);
                articleDetailVO.setHasCollected(hasCollected);
            }
        }
        // 记录用户浏览历史（Redis 快判断 + MySQL 兜底，保证不重复）
        Long userId = UserContext.getUserId();
        if (userId != null) {
            String viewKey = RedisConstants.REDIS_KEY_ARTICLE_VIEW + userId + ":" + articleId;
            if (!redisComponent.hasKey(viewKey)) {
                // Redis 没命中：可能是第一次，也可能是缓存过期，查 MySQL 兜底
                UserAction existing = userActionMapper.selectOne(
                        new LambdaQueryWrapper<UserAction>()
                                .eq(UserAction::getUserId, userId)
                                .eq(UserAction::getArticleId, articleId)
                                .eq(UserAction::getActionType, ActionTypeEnum.ARTICLE_VIEW.getCode())
                );
                if (existing == null) {
                    // 真的第一次浏览，插入新记录
                    UserAction action = new UserAction();
                    action.setUserId(userId);
                    action.setArticleId(articleId);
                    action.setArticleUserId(article != null ? article.getUserId() : null);
                    action.setActionType(ActionTypeEnum.ARTICLE_VIEW.getCode());
                    action.setActionCount(1);
                    action.setActionTime(LocalDateTime.now());
                    userActionMapper.insert(action);
                } else {
                    // 缓存过期但 MySQL 有记录，只更新时间
                    existing.setActionTime(LocalDateTime.now());
                    userActionMapper.updateById(existing);
                }
                // 重新设 Redis 缓存
                redisComponent.saveView(userId, articleId);
            } else {
                // Redis 命中：24 小时内重复浏览，只更新时间
                userActionMapper.update(null,
                        new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<UserAction>()
                                .eq(UserAction::getUserId, userId)
                                .eq(UserAction::getArticleId, articleId)
                                .eq(UserAction::getActionType, ActionTypeEnum.ARTICLE_VIEW.getCode())
                                .set(UserAction::getActionTime, LocalDateTime.now())
                );
            }
        }
        return articleDetailVO;
    }
    /**
     * 删除文章
     * @param articleId
     */
    @Transactional
    @Override
    public void deleteArticle(Long articleId) {
        // 先删除标签关联
        articleTagService.removeArticleTags(articleId);
        userMapper.changeArticleCount(UserContext.getUserId(), -1);
        articleMapper.delete(new LambdaQueryWrapper<Article>().eq(Article::getArticleId, articleId).eq(Article::getUserId, UserContext.getUserId()));
        esComponent.deleteDoc(articleId);
        rabbitTemplate.convertAndSend(
                RabbitMqConstants.TOPIC_EXCHANGE,
                RabbitMqConstants.ROUTING_KEY_DELETE,
                new ArticleVectorMessage(articleId, "DELETE")
        );
    }
    
    /**
     * 修改文章
     * @param articleId
     * @param article
     */
    @Override
    @Transactional
    public void updateArticle(Long articleId, ArticleCreateDTO article) {
        if(article.getCategoryId()== null||article.getCategoryId().isEmpty()){
            throw new BusinessException("请选择分类");
        }
        if(!article.isTitleValid() || !article.isContentValid()){
            throw new RuntimeException("文章不符合要求");
        }
        Article article1 = BeanUtil.copyProperties(article, Article.class);
        article1.setArticleId(articleId);// 设置articleId以便ES更新
        article1.setUserId(UserContext.getUserId());
        if(article.getStatus() == 1){
            article1.setPublishTime(LocalDateTime.now());
        }
        article1.setUpdateTime(LocalDateTime.now());
        articleMapper.update(article1,
                new LambdaQueryWrapper<Article>().eq(Article::getArticleId, articleId).eq(Article::getUserId, UserContext.getUserId()));
        // 处理标签关联
        if (article.getTagNames() != null) {
            articleTagService.handleArticleTags(articleId, article.getTagNames());
        }
        // 同步ES
        if(article.getStatus() == 1) {
            esComponent.saveDoc(article1);
            rabbitTemplate.convertAndSend(
                    RabbitMqConstants.TOPIC_EXCHANGE,
                    RabbitMqConstants.ROUTING_KEY_UPDATE,
                    new ArticleVectorMessage(articleId,"UPDATE")
            );
        }

    
    }

    /**
     * 获取草稿
     * @param page
     * @param size
     * @return
     */
    @Override
    public Map<String,Object> getDrafts(Integer page, Integer size) {
        IPage<Article> articleIPage = articleMapper.selectPage(
                new Page<>(page, size),
                new LambdaQueryWrapper<Article>()
                        .eq(Article::getUserId, UserContext.getUserId())
                        .eq(Article::getStatus, 0)  // 只查草稿
                        .orderByDesc(Article::getCreateTime)
        );
        List<ArticleListVO> articleListVOList = articleIPage.getRecords().stream().map(article -> {
            ArticleListVO articleListVO = new ArticleListVO();
            articleListVO.setArticleId(String.valueOf(article.getArticleId()));
            articleListVO.setTitle(article.getTitle());
            articleListVO.setCoverImage(article.getCoverImage());
            articleListVO.setSummary(article.getSummary());
            if (article.getCreateTime() != null) {
                articleListVO.setCreateTime(article.getCreateTime().toString());
            }
            if (article.getUpdateTime() != null) {
                articleListVO.setUpdateTime(article.getUpdateTime().toString());
            }
            return articleListVO;
        }).collect(Collectors.toList());
        Map<String,Object> result = new HashMap<>();
        result.put("total", articleIPage.getTotal());
        result.put("records", articleListVOList);
        result.put("pages", articleIPage.getPages());
        result.put("current", articleIPage.getCurrent());
        return result;
    }
    /**
     * 发布文章
     * @param articleId
     */
    @Transactional
    @Override
    public void publish(Long articleId) {
        Article article = articleMapper.selectOne(new LambdaQueryWrapper<Article>().eq(Article::getArticleId, articleId).
                eq(Article::getUserId, UserContext.getUserId()));
        if(article== null){
            throw new BusinessException("文章不存在");
        }
        article.setPublishTime(LocalDateTime.now());
        article.setStatus(1);
        article.setUpdateTime(LocalDateTime.now());
        userMapper.changeArticleCount(UserContext.getUserId(), 1);
        articleMapper.update(article, new LambdaQueryWrapper<Article>().eq(Article::getArticleId, articleId).
                eq(Article::getUserId, UserContext.getUserId()));
        // 同步到ES
        esComponent.saveDoc(article);

        rabbitTemplate.convertAndSend(
                RabbitMqConstants.TOPIC_EXCHANGE,
                RabbitMqConstants.ROUTING_KEY_PUBLISH,
                new ArticleVectorMessage(articleId,"PUBLISH")
        );

    }

    /**
     * 获取公开文章列表（主界面）
     * 不需要登录，返回已发布的文章
     */
    @Override
    public PageVO listArticles(Integer page, Integer size, String sort, Long categoryId, String keyword) {
        // 创建分页对象
        Page<ArticleListVO> pageParam = new Page<>(page, size);
        
        // 调用 Mapper 查询
        IPage<ArticleListVO> articlePage = articleMapper.listArticles(pageParam, sort, categoryId, keyword);
        
        // 转换为 PageVO
        return PageVO.fromIPage(articlePage);
    }
    /**
     * 浏览文章15秒内只统计一次
     * @param articleId
     */
    @Override
    public void increaseViewCount(Long articleId) {
        Long userId = UserContext.getUserId();
        if(userId == null){
            return;
        }
        if(redisComponent.hasViewCount(articleId,userId)){
            return;
        }
        esComponent.updateDocCount(articleId.toString(), "viewCount",1);
        redisComponent.saveViewCount(articleId,userId);
        articleMapper.changeViewCount(articleId, 1);



    }
    /**
     * 记录文章分享(包括评论，但是评论没有分享数量)
     * @param shareDTO
     * @return
     */
    @Override
    @Transactional
    public Integer recordArticleShare(ShareDTO shareDTO) {
        Article article = articleMapper.selectOne(new LambdaQueryWrapper<Article>().eq(Article::getArticleId, shareDTO.getArticleId()));
        if(article == null){
            throw new BusinessException("文章不存在");
        }
        if(shareDTO.getArticleId() == null){
           throw new BusinessException("参数错误");
        }
        
        Long userId = UserContext.getUserId();
        
        //判断是分享文章还是评论
        if(shareDTO.getCommentId() != null){
            //分享评论
            ArticleComment articleComment = articleCommentMapper.selectOne(new LambdaQueryWrapper<ArticleComment>().eq(ArticleComment::getCommentId, shareDTO.getCommentId()));
            if(articleComment == null){
                throw new BusinessException("评论不存在");
            }
            
            // 查询是否已存在分享记录
            UserAction existing = userActionMapper.selectOne(new LambdaQueryWrapper<UserAction>()
                    .eq(UserAction::getUserId, userId)
                    .eq(UserAction::getArticleId, shareDTO.getArticleId())
                    .eq(UserAction::getCommentId, shareDTO.getCommentId())
                    .eq(UserAction::getActionType, ActionTypeEnum.COMMENT_SHARE.getCode()));
            
            if(existing != null){
                // 已存在，更新actionTime
                existing.setActionTime(LocalDateTime.now());
                existing.setActionCount(shareDTO.getShareType());
                userActionMapper.updateById(existing);
            }else{
                // 不存在，插入新记录
                UserAction userAction = new UserAction();
                userAction.setActionType(ActionTypeEnum.COMMENT_SHARE.getCode());
                userAction.setActionCount(shareDTO.getShareType());
                userAction.setUserId(userId);
                userAction.setActionTime(LocalDateTime.now());
                userAction.setArticleId(shareDTO.getArticleId());
                userAction.setCommentId(shareDTO.getCommentId());
                userAction.setArticleUserId(article.getUserId());
                userActionMapper.insert(userAction);
            }
            return articleMapper.getShareCount(shareDTO.getArticleId());
        }else{
            //分享文章
            // 查询是否已存在分享记录（comment_id 可能是 null 或 0）
            UserAction existing = userActionMapper.selectOne(new LambdaQueryWrapper<UserAction>()
                    .eq(UserAction::getUserId, userId)
                    .eq(UserAction::getArticleId, shareDTO.getArticleId())
                    .and(w -> w.isNull(UserAction::getCommentId).or().eq(UserAction::getCommentId, 0L))
                    .eq(UserAction::getActionType, ActionTypeEnum.ARTICLE_SHARE.getCode()));
            
            if(existing != null){
                // 已存在，更新actionTime
                existing.setActionTime(LocalDateTime.now());
                existing.setActionCount(shareDTO.getShareType());
                userActionMapper.updateById(existing);
            }else{
                // 不存在，插入新记录
                UserAction userAction = new UserAction();
                userAction.setActionType(ActionTypeEnum.ARTICLE_SHARE.getCode());
                userAction.setActionCount(shareDTO.getShareType());
                userAction.setUserId(userId);
                userAction.setActionTime(LocalDateTime.now());
                userAction.setArticleId(shareDTO.getArticleId());
                userAction.setCommentId(0L);  // 统一用 0 表示文章分享
                userAction.setArticleUserId(article.getUserId());
                userActionMapper.insert(userAction);
            }
            //增加文章分享数（每次都+1，后续再做风控）
            //todo分享数风控
            articleMapper.changeShareCount(shareDTO.getArticleId(), 1);
            return articleMapper.getShareCount(shareDTO.getArticleId());
        }
    }

}
