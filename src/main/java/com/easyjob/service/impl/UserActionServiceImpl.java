package com.easyjob.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.component.EsComponent;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.component.RedisComponent;
import com.easyjob.dto.NotificationMessage;
import com.easyjob.entity.Article;
import com.easyjob.entity.UserAction;
import com.easyjob.enums.ActionTypeEnum;
import com.easyjob.enums.NotificationTypeEnum;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.UserActionMapper;
import com.easyjob.mapper.UserMapper;
import com.easyjob.entity.User;
import com.easyjob.service.UserActionService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ArticleListVO;
import com.easyjob.vo.PageVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

@Service
public class UserActionServiceImpl extends ServiceImpl<UserActionMapper, UserAction> implements UserActionService {
    @Autowired
    private UserActionMapper userActionMapper;
    @Autowired
    private ArticleMapper articleMapper;
    @Autowired
    private EsComponent esComponent;
    @Autowired
    private EsVectorStore esVectorStore;
    @Autowired
    private RedisComponent redisComponent;
    @Autowired
    private NotificationServiceImpl notificationService;
    @Autowired
    private UserMapper userMapper;
    @Override
    public void like(Long articleId) {
        UserAction userAction = userActionMapper.selectOne(new LambdaQueryWrapper<UserAction>().eq(UserAction::getArticleId, articleId)
                .eq(UserAction::getUserId, UserContext.getUserId())
                .eq(UserAction::getActionType, ActionTypeEnum.ARTICLE_LIKE.getCode()));
        if(userAction == null){
            Article article = articleMapper.selectById(articleId);
            userAction = new UserAction();
            userAction.setArticleId(articleId);
            userAction.setUserId(UserContext.getUserId());
            userAction.setActionType(ActionTypeEnum.ARTICLE_LIKE.getCode());
            userAction.setActionCount(1);
            userAction.setActionTime(LocalDateTime.now());
            userAction.setArticleUserId(article.getUserId());
            userActionMapper.insert(userAction);
            articleMapper.changeLikeCount(articleId, 1);
            // 同步ES
            esComponent.updateDocCount(articleId.toString(), "likeCount", 1);
            // 同步向量索引热度
            esVectorStore.updateChunkCounts(articleId.toString(), "like_count", 1);
            // 新增点赞时发通知（取消点赞不通知）
            User liker = userMapper.selectById(UserContext.getUserId());
            notificationService.send(NotificationMessage.builder()
                    .userId(article.getUserId())
                    .senderId(UserContext.getUserId())
                    .senderNickname(liker != null ? liker.getNickName() : null)
                    .senderAvatar(liker != null ? liker.getAvatar() : null)
                    .type(NotificationTypeEnum.LIKE.getCode())
                    .articleId(articleId)
                    .articleTitle(article.getTitle())
                    .targetId(articleId)
                    .content("赞了你的文章")
                    .build()
            );
        }else{
            userActionMapper.delete(new LambdaQueryWrapper<UserAction>().eq(UserAction::getArticleId, articleId)
                    .eq(UserAction::getUserId, UserContext.getUserId())
                    .eq(UserAction::getActionType, ActionTypeEnum.ARTICLE_LIKE.getCode()));
            articleMapper.changeLikeCount(articleId, -1);
            // 同步ES
            esComponent.updateDocCount(articleId.toString(), "likeCount", -1);
            // 同步向量索引热度
            esVectorStore.updateChunkCounts(articleId.toString(), "like_count", -1);
        }
        redisComponent.deleteArticleDetail(articleId);
    }
    @Transactional
    @Override
    public void collect(Long articleId) {
        UserAction userAction = userActionMapper.selectOne(new LambdaQueryWrapper<UserAction>().eq(UserAction::getArticleId, articleId)
                .eq(UserAction::getUserId, UserContext.getUserId())
                .eq(UserAction::getActionType, ActionTypeEnum.ARTICLE_COLLECT.getCode()));
        if(userAction == null){
            Article article = articleMapper.selectById(articleId);
            userAction = new UserAction();
            userAction.setArticleId(articleId);
            userAction.setUserId(UserContext.getUserId());
            userAction.setActionType(ActionTypeEnum.ARTICLE_COLLECT.getCode());
            userAction.setActionCount(1);
            userAction.setActionTime(LocalDateTime.now());
            userAction.setArticleUserId(article.getUserId());
            userActionMapper.insert(userAction);
            articleMapper.changeCollectCount(articleId, 1);
            // 同步ES
            esComponent.updateDocCount(articleId.toString(), "collectCount", 1);
            // 同步向量索引热度
            esVectorStore.updateChunkCounts(articleId.toString(), "collect_count", 1);
            // 新增收藏时发通知（取消收藏不通知）
            User collector = userMapper.selectById(UserContext.getUserId());
            notificationService.send(NotificationMessage.builder()
                    .userId(article.getUserId())
                    .senderId(UserContext.getUserId())
                    .senderNickname(collector != null ? collector.getNickName() : null)
                    .senderAvatar(collector != null ? collector.getAvatar() : null)
                    .type(NotificationTypeEnum.COLLECT.getCode())
                    .articleId(articleId)
                    .articleTitle(article.getTitle())
                    .targetId(articleId)
                    .content("收藏了你的文章")
                    .build()
            );
        }else {
            userActionMapper.delete(new LambdaQueryWrapper<UserAction>().eq(UserAction::getArticleId, articleId)
                    .eq(UserAction::getUserId, UserContext.getUserId())
                    .eq(UserAction::getActionType, ActionTypeEnum.ARTICLE_COLLECT.getCode()));
            articleMapper.changeCollectCount(articleId, -1);
            // 同步ES
            esComponent.updateDocCount(articleId.toString(), "collectCount", -1);
            // 同步向量索引热度
            esVectorStore.updateChunkCounts(articleId.toString(), "collect_count", -1);
        }
        redisComponent.deleteArticleDetail(articleId);
    }

    @Override
    public PageVO<ArticleListVO> getUserCollect(Long userId, Integer page, Integer size, Integer type, String order) {
        Page<ArticleListVO> pageParam = new Page<>(page, size);
        // 收藏类型固定为 3
        IPage<ArticleListVO> pageInfo = articleMapper.listUserCollectionOrLike(pageParam, userId, ActionTypeEnum.ARTICLE_COLLECT.getCode(), order);
        PageVO<ArticleListVO> pageVO = PageVO.fromIPage(pageInfo);
        return pageVO;
    }

    @Override
    public PageVO<ArticleListVO> getUserLike(Long userId, Integer page, Integer size, Integer type, String order) {
        Page<ArticleListVO> pageParam = new Page<>(page, size);
        // 点赞类型固定为 2
        IPage<ArticleListVO> pageInfo = articleMapper.listUserCollectionOrLike(pageParam, userId, ActionTypeEnum.ARTICLE_LIKE.getCode(), order);
        PageVO<ArticleListVO> pageVO = PageVO.fromIPage(pageInfo);
        return pageVO;
    }
}
