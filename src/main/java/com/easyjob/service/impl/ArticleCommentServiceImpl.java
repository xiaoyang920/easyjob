package com.easyjob.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.dto.CommentActionDTO;
import com.easyjob.dto.CommentCreateDTO;
import com.easyjob.dto.NotificationMessage;
import com.easyjob.entity.ArticleComment;
import com.easyjob.entity.User;
import com.easyjob.entity.UserAction;
import com.easyjob.enums.ActionTypeEnum;
import com.easyjob.enums.NotificationTypeEnum;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleCommentMapper;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.UserActionMapper;
import com.easyjob.mapper.UserMapper;
import com.easyjob.service.ArticleCommentService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ArticleCommentVO;
import com.easyjob.vo.CommentActionVO;
import com.easyjob.vo.PageVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.stream.Collectors;


@Service
public class ArticleCommentServiceImpl extends ServiceImpl<ArticleCommentMapper, ArticleComment> implements ArticleCommentService {
    @Autowired
    private ArticleCommentMapper articleCommentMapper;
    @Autowired
    private UserMapper userMapper;
    @Autowired
    private ArticleMapper articleMapper;
    @Autowired
    private UserActionMapper userActionMapper;
    @Autowired
    private NotificationServiceImpl notificationService;
    /**
     * 获取文章评论列表
     * @param articleId
     * @param page
     * @param size
     * @param sort
     * @return
     */
    @Override
    public PageVO getCommentList(Long articleId, Integer page, Integer size, String sort) {
        if(sort.isEmpty()) {
            sort = "create_time";
        }
        Page<ArticleComment> pageParam = new Page<>(page,size);
        LambdaQueryWrapper<ArticleComment> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper
               .eq(ArticleComment::getArticleId,articleId)
               .eq(ArticleComment::getStatus,0)
               .eq(ArticleComment::getParentId,0);
        if(sort.equals("like_count")){
            queryWrapper.orderByDesc(ArticleComment::getLikeCount);
        }else {
            queryWrapper.orderByDesc(ArticleComment::getCreateTime);
        }
        IPage<ArticleComment> pageData = articleCommentMapper.selectPage(pageParam, queryWrapper);
        List<ArticleComment> comments = pageData.getRecords();
        
        // 批量查询当前用户的点赞/点踩状态
        Long currentUserId = UserContext.getUserId();
        Map<Long, Integer> actionTypeMap = new HashMap<>();
        
        if (currentUserId != null && !comments.isEmpty()) {
            List<Long> commentIds = comments.stream()
                    .map(ArticleComment::getCommentId)
                    .collect(Collectors.toList());
            
            // 一次查询所有状态
            List<UserAction> actions = userActionMapper.selectList(
                    new LambdaQueryWrapper<>(UserAction.class)
                            .in(UserAction::getCommentId, commentIds)
                            .eq(UserAction::getUserId, currentUserId)
                            .in(UserAction::getActionType, Arrays.asList(
                                    ActionTypeEnum.COMMENT_LIKE.getCode(),
                                    ActionTypeEnum.COMMENT_DISLIKE.getCode()
                            ))
            );
            
            // 存入 Map（每个评论最多一条记录）
            for (UserAction action : actions) {
                actionTypeMap.put(action.getCommentId(), action.getActionType());
            }
        }
        
        // 转换成VO并填充状态
        List<ArticleCommentVO> list = comments.stream()
                .map(comment -> {
                    ArticleCommentVO vo = convertToVO(comment);
                    Integer actionType = actionTypeMap.get(comment.getCommentId());
                    vo.setHasLiked(actionType != null && actionType.equals(ActionTypeEnum.COMMENT_LIKE.getCode()));
                    vo.setHasDisliked(actionType != null && actionType.equals(ActionTypeEnum.COMMENT_DISLIKE.getCode()));
                    return vo;
                })
                .toList();
        return PageVO.fromIPage(pageData,list);
    }
    /**
     * 获取评论回复列表(顶级评论)
     * @param commentId 顶级评论ID
     * @param page
     * @param size
     * @return
     */
    @Override
    public PageVO getReplies(Long commentId, Integer page, Integer size) {
        Page<ArticleComment> pageParam = new Page<>(page,size);
        IPage<ArticleComment> pageData = articleCommentMapper.selectPage(pageParam,
                new LambdaQueryWrapper<>(ArticleComment.class)
                        .eq(ArticleComment::getParentId,commentId)
                        .eq(ArticleComment::getStatus,0)
                        .orderByAsc(ArticleComment::getCreateTime)
        );
        List<ArticleComment> replies = pageData.getRecords();
        
        // 批量查询当前用户的点赞/点踩状态
        Long currentUserId = UserContext.getUserId();
        Map<Long, Integer> actionTypeMap = new HashMap<>();
        
        if (currentUserId != null && !replies.isEmpty()) {
            List<Long> replyIds = replies.stream()
                    .map(ArticleComment::getCommentId)
                    .collect(Collectors.toList());
            
            // 一次查询所有状态
            List<UserAction> actions = userActionMapper.selectList(
                    new LambdaQueryWrapper<>(UserAction.class)
                            .in(UserAction::getCommentId, replyIds)
                            .eq(UserAction::getUserId, currentUserId)
                            .in(UserAction::getActionType, Arrays.asList(
                                    ActionTypeEnum.COMMENT_LIKE.getCode(),
                                    ActionTypeEnum.COMMENT_DISLIKE.getCode()
                            ))
            );
            
            // 存入 Map
            for (UserAction action : actions) {
                actionTypeMap.put(action.getCommentId(), action.getActionType());
            }
        }
        
        // 转换成VO并填充状态
        List<ArticleCommentVO> list = replies.stream()
                .map(reply -> {
                    ArticleCommentVO vo = convertToVO(reply);
                    Integer actionType = actionTypeMap.get(reply.getCommentId());
                    vo.setHasLiked(actionType != null && actionType.equals(ActionTypeEnum.COMMENT_LIKE.getCode()));
                    vo.setHasDisliked(actionType != null && actionType.equals(ActionTypeEnum.COMMENT_DISLIKE.getCode()));
                    return vo;
                })
                .toList();
        return PageVO.fromIPage(pageData, list);
    }



    /**
     * 创建评论
     *
     * @param commentCreateDTO
     * @return
     */
    @Override
    @Transactional
    public ArticleCommentVO create(CommentCreateDTO commentCreateDTO) {
        if (!commentCreateDTO.isContentValid()) {
            throw new BusinessException("评论内容无效");
        }
        ArticleComment articleComment = new ArticleComment();
        //传入dto中的属性
        articleComment.setArticleUserId(commentCreateDTO.getArticleUserId());
        articleComment.setArticleId(commentCreateDTO.getArticleId());
        articleComment.setContent(commentCreateDTO.getContent());
        articleComment.setImgPath(commentCreateDTO.getImgPath());
        articleComment.setReplyCount(0);
        //设置创建时间
        articleComment.setCreateTime(LocalDateTime.now());
        articleComment.setUpdateTime(LocalDateTime.now());
        //设置评论者的冗余字段
        User user = userMapper.selectById(UserContext.getUserId());
        articleComment.setUserId(UserContext.getUserId());
        articleComment.setUserNickName(user.getNickName());
        articleComment.setUserAvatar(user.getAvatar());
        //判断是否是顶级评论
        if(commentCreateDTO.getParentId()== null||commentCreateDTO.getParentId()==0){
            articleComment.setParentId(0L);
            articleComment.setReplyCount(0);
            //插入顶级评论
            articleCommentMapper.insert(articleComment);
            //更新文章的评论数
            articleMapper.changeCommentCount(commentCreateDTO.getArticleId(),1);

        }else {
            //不是顶级评论，则是回复，获取父级评论（必须是顶级评论）
            ArticleComment parentComment = articleCommentMapper.selectById(commentCreateDTO.getParentId());
            if(parentComment==null){
                throw new BusinessException("父级评论不存在");
            }
            // 所有二级评论的 parentId 都指向顶级评论
            Long topCommentId = parentComment.getParentId() == 0 
                    ? parentComment.getCommentId()  // 父评论是顶级评论
                    : parentComment.getParentId();   // 父评论是二级评论，取其parentId
            articleComment.setParentId(topCommentId);
            //回复的冗余字段
            // 设置被回复者信息（只有回复二级评论时才有值）
            if (commentCreateDTO.getReplyUserId() != null) {
                User replyUser = userMapper.selectById(commentCreateDTO.getReplyUserId());
                if (replyUser != null) {
                    articleComment.setReplyUserId(replyUser.getUserId());
                    articleComment.setReplyNickName(replyUser.getNickName());
                    articleComment.setReplyAvatar(replyUser.getAvatar());
                }
            }
            articleCommentMapper.insert(articleComment);
            //更新顶级评论的回复数
            articleCommentMapper.changeCommentCount(topCommentId,1);
        }
        // ---- 发通知 ----
        // 查文章标题（冗余进通知）
        com.easyjob.entity.Article articleForNotify = articleMapper.selectById(commentCreateDTO.getArticleId());
        String articleTitle = articleForNotify != null ? articleForNotify.getTitle() : null;
        String preview = truncate(commentCreateDTO.getContent(), 100);

        // 给文章作者（评论了你的文章）
        notificationService.send(NotificationMessage.builder()
                .userId(commentCreateDTO.getArticleUserId())
                .senderId(UserContext.getUserId())
                .senderNickname(user.getNickName())
                .senderAvatar(user.getAvatar())
                .type(NotificationTypeEnum.COMMENT_REPLY.getCode())
                .articleId(commentCreateDTO.getArticleId())
                .articleTitle(articleTitle)
                .targetId(articleComment.getCommentId())
                .targetPreview(preview)
                .content("评论了你的文章")
                .build()
        );
        // 如果是回复别人的评论，再通知被回复者（去重避免文章作者=被回复者时重复发）
        if (commentCreateDTO.getReplyUserId() != null
                && !commentCreateDTO.getReplyUserId().equals(UserContext.getUserId())
                && !commentCreateDTO.getReplyUserId().equals(commentCreateDTO.getArticleUserId())) {
            notificationService.send(NotificationMessage.builder()
                    .userId(commentCreateDTO.getReplyUserId())
                    .senderId(UserContext.getUserId())
                    .senderNickname(user.getNickName())
                    .senderAvatar(user.getAvatar())
                    .type(NotificationTypeEnum.COMMENT_REPLY.getCode())
                    .articleId(commentCreateDTO.getArticleId())
                    .articleTitle(articleTitle)
                    .targetId(articleComment.getCommentId())
                    .targetPreview(preview)
                    .content("回复了你的评论")
                    .build()
            );
        }
        return convertToVO(articleComment);
    }
    /**
     * 删除评论
     *
     * @param commentId
     */
    @Override
    @Transactional
    public void removeComment(Long commentId) {
        //评论是否存在
        ArticleComment articleComment = articleCommentMapper.selectById(commentId);
        if (articleComment == null) {
            throw new BusinessException("评论不存在");
        }
        //检查pid是否是0,不是0代表是2级评论，直接删，并且更新父评论的回复数
        if (articleComment.getParentId() != 0) {
            articleCommentMapper.deleteById(commentId);
            articleCommentMapper.changeCommentCount(articleComment.getParentId(),-1);
        }else {
            //顶级评论，连带子评论一起删掉,更新文章的评论数
            articleCommentMapper.delete(new LambdaQueryWrapper<>(ArticleComment.class).eq(ArticleComment::getParentId,commentId));
            articleCommentMapper.deleteById(commentId);
            articleMapper.changeCommentCount(articleComment.getArticleId(),-1);
        }


    }
    /**
     * 评论行为
     * @param commentId
     * @return
     */
    @Override
    @Transactional
    public CommentActionVO action(Long commentId, CommentActionDTO commentActionDTO) {
        Long userId = UserContext.getUserId();

        // 1. 查询当前用户对该评论的已有操作
        UserAction existLike = userActionMapper.selectOne(
                new LambdaQueryWrapper<>(UserAction.class)
                        .eq(UserAction::getCommentId, commentId)
                        .eq(UserAction::getUserId, userId)
                        .eq(UserAction::getActionType, ActionTypeEnum.COMMENT_LIKE.getCode())
        );

        UserAction existDislike = userActionMapper.selectOne(
                new LambdaQueryWrapper<>(UserAction.class)
                        .eq(UserAction::getCommentId, commentId)
                        .eq(UserAction::getUserId, userId)
                        .eq(UserAction::getActionType, ActionTypeEnum.COMMENT_DISLIKE.getCode())
        );

        boolean hasLiked = false;
        boolean hasDisliked = false;

        // 2. 处理点赞
        if (commentActionDTO.getActionType().equals(ActionTypeEnum.COMMENT_LIKE.getCode())) {
            // 如果已点踩，先取消点踩
            if (existDislike != null) {
                userActionMapper.deleteById(existDislike.getActionId());
            }

            // 如果已点赞，取消点赞
            if (existLike != null) {
                userActionMapper.deleteById(existLike.getActionId());
                articleCommentMapper.changeLikeCount(commentId, -1);
                hasLiked = false;
            } else {
                // 新增点赞
                UserAction newLike = new UserAction();
                newLike.setActionType(ActionTypeEnum.COMMENT_LIKE.getCode());
                newLike.setCommentId(commentId);
                newLike.setUserId(userId);
                newLike.setArticleId(commentActionDTO.getArticleId());
                newLike.setArticleUserId(commentActionDTO.getArticleUserId());
                newLike.setActionCount(1);
                newLike.setActionTime(LocalDateTime.now());
                userActionMapper.insert(newLike);
                articleCommentMapper.changeLikeCount(commentId, 1);
                hasLiked = true;
            }
            hasDisliked = false;
        }

        // 3. 处理点踩（同理）
        else if (commentActionDTO.getActionType().equals(ActionTypeEnum.COMMENT_DISLIKE.getCode())) {
            // 如果已点赞，先取消点赞
            if (existLike != null) {
                userActionMapper.deleteById(existLike.getActionId());
                articleCommentMapper.changeLikeCount(commentId, -1);
            }

            // 如果已点踩，取消点踩
            if (existDislike != null) {
                userActionMapper.deleteById(existDislike.getActionId());
                hasDisliked = false;
            } else {
                // 新增点踩
                UserAction newDislike = new UserAction();
                newDislike.setActionType(ActionTypeEnum.COMMENT_DISLIKE.getCode());
                newDislike.setCommentId(commentId);
                newDislike.setUserId(userId);
                newDislike.setArticleId(commentActionDTO.getArticleId());
                newDislike.setArticleUserId(commentActionDTO.getArticleUserId());
                newDislike.setActionCount(1);
                newDislike.setActionTime(LocalDateTime.now());
                userActionMapper.insert(newDislike);
                hasDisliked = true;
            }
            hasLiked = false;
        } else {
            throw new BusinessException("无效的操作类型");
        }

        // 4. 查询最新的点赞数
        ArticleComment comment = articleCommentMapper.selectById(commentId);
        Integer likeCount = comment != null ? comment.getLikeCount() : 0;

        if(hasLiked&&comment!=null){
            User liker = userMapper.selectById(userId);
            // 查文章标题（通知列表需要，冗余存）
            com.easyjob.entity.Article articleForNotify = articleMapper.selectById(comment.getArticleId());
            notificationService.send(NotificationMessage.builder()
                    .userId(comment.getUserId())
                    .senderId(userId)
                    .senderNickname(liker != null ? liker.getNickName() : null)
                    .senderAvatar(liker != null ? liker.getAvatar() : null)
                    .type(NotificationTypeEnum.LIKE.getCode())
                    .articleId(comment.getArticleId())
                    .articleTitle(articleForNotify != null ? articleForNotify.getTitle() : null)
                    .targetId(comment.getCommentId())
                    .targetPreview(truncate(comment.getContent(), 100))
                    .content("赞了你的评论")
                    .build()
            );
        }
        return new CommentActionVO(hasLiked, hasDisliked, likeCount);
    }

    /**
     * 实体转 VO（私有方法）
     */
    private ArticleCommentVO convertToVO(ArticleComment entity) {
        ArticleCommentVO vo = new ArticleCommentVO();

        // ID 字段：Long → String
        vo.setCommentId(String.valueOf(entity.getCommentId()));
        vo.setArticleId(String.valueOf(entity.getArticleId()));
        vo.setParentId(String.valueOf(entity.getParentId()));
        vo.setUserId(String.valueOf(entity.getUserId()));

        // 字符串字段：直接复制
        vo.setContent(entity.getContent());
        vo.setImgPath(entity.getImgPath());
        vo.setUserNickName(entity.getUserNickName());
        vo.setUserAvatar(entity.getUserAvatar());

        // 被回复者信息（可能为 null）
        if (entity.getReplyUserId() != null) {
            vo.setReplyUserId(String.valueOf(entity.getReplyUserId()));
            vo.setReplyNickName(entity.getReplyNickName());
            vo.setReplyAvatar(entity.getReplyAvatar());
        }

        // 数值字段
        vo.setTopType(entity.getTopType());
        vo.setLikeCount(entity.getLikeCount());
        vo.setReplyCount(entity.getReplyCount());

        // 时间字段：LocalDateTime → String
        if (entity.getCreateTime() != null) {
            vo.setCreateTime(entity.getCreateTime().format(
                    DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
            ));
        }
        if (entity.getUpdateTime() != null) {
            vo.setUpdateTime(entity.getUpdateTime().format(
                    DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
            ));
        }
        
        // 点赞/点踩状态由调用方填充，默认为 false
        vo.setHasLiked(false);
        vo.setHasDisliked(false);

        return vo;
    }

    /**
     * 截断字符串（通知 target_preview 用），null 安全
     */
    private static String truncate(String s, int max) {
        if (s == null) return null;
        return s.length() <= max ? s : s.substring(0, max);
    }
}
