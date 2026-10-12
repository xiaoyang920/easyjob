package com.easyjob.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.dto.NotificationMessage;
import com.easyjob.entity.Article;
import com.easyjob.entity.UserAction;
import com.easyjob.enums.ActionTypeEnum;
import com.easyjob.enums.NotificationTypeEnum;
import com.easyjob.exception.BusinessException;
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
    private ArticleIndexPublisher articleIndexPublisher;
    @Autowired
    private NotificationServiceImpl notificationService;
    @Autowired
    private UserMapper userMapper;

    @Override
    @Transactional
    public void like(Long articleId) {
        changeInteraction(articleId, null, true);
    }

    @Override
    @Transactional
    public void collect(Long articleId) {
        changeInteraction(articleId, null, false);
    }

    @Override
    @Transactional
    public InteractionResult like(Long articleId, Boolean active) {
        return changeInteraction(articleId, active, true);
    }

    @Override
    @Transactional
    public InteractionResult collect(Long articleId, Boolean active) {
        return changeInteraction(articleId, active, false);
    }

    private InteractionResult changeInteraction(Long articleId, Boolean desired, boolean like) {
        Long userId = UserContext.getUserId();
        if (userId == null) throw new BusinessException(401, "请先登录");
        if (articleId == null || articleId <= 0) throw new BusinessException(400, "文章ID无效");

        // Hold the article row lock until the relationship, counter and outbox commit together.
        Article article = articleMapper.lockForInteraction(articleId);
        if (article == null || !Integer.valueOf(1).equals(article.getStatus())
                || !Integer.valueOf(0).equals(article.getDeleted())) {
            throw new BusinessException(404, "文章不存在或未公开");
        }
        int actionType = like ? ActionTypeEnum.ARTICLE_LIKE.getCode() : ActionTypeEnum.ARTICLE_COLLECT.getCode();
        var relationship = new LambdaQueryWrapper<UserAction>()
                .eq(UserAction::getArticleId, articleId)
                .eq(UserAction::getCommentId, 0L)
                .eq(UserAction::getUserId, userId)
                .eq(UserAction::getActionType, actionType);
        UserAction existing = userActionMapper.selectOne(relationship);
        boolean wasActive = existing != null;
        boolean active = desired == null ? !wasActive : desired;
        Integer currentCount = like ? article.getLikeCount() : article.getCollectCount();
        int count = currentCount == null ? 0 : Math.max(0, currentCount);
        if (active == wasActive) return new InteractionResult(active, count);

        if (active) {
            var action = new UserAction();
            action.setArticleId(articleId);
            action.setCommentId(0L);
            action.setUserId(userId);
            action.setArticleUserId(article.getUserId());
            action.setActionType(actionType);
            action.setActionCount(1);
            action.setActionTime(LocalDateTime.now());
            if (userActionMapper.insert(action) != 1) throw new BusinessException(409, "操作未成功，请重试");
        } else if (userActionMapper.delete(relationship) != 1) {
            throw new BusinessException(409, "状态已变更，请刷新后重试");
        }
        int delta = active ? 1 : -1;
        if (like) articleMapper.changeLikeCount(articleId, delta);
        else articleMapper.changeCollectCount(articleId, delta);

        // Search popularity is an asynchronous projection; never invalidate the cached article body.
        articleIndexPublisher.publish(articleId, RabbitMqConstants.ACTION_COUNTS, RabbitMqConstants.ROUTING_KEY_UPDATE);
        if (active) notifyAuthor(article, userId, like);
        return new InteractionResult(active, Math.max(0, count + delta));
    }

    private void notifyAuthor(Article article, Long userId, boolean like) {
        if (userId.equals(article.getUserId())) return;
        User sender = userMapper.selectById(userId);
        notificationService.send(NotificationMessage.builder()
                .userId(article.getUserId())
                .senderId(userId)
                .senderNickname(sender != null ? sender.getNickName() : null)
                .senderAvatar(sender != null ? sender.getAvatar() : null)
                .type(like ? NotificationTypeEnum.LIKE.getCode() : NotificationTypeEnum.COLLECT.getCode())
                .articleId(article.getArticleId())
                .articleTitle(article.getTitle())
                .targetId(article.getArticleId())
                .content(like ? "赞了你的文章" : "收藏了你的文章")
                .build());
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
