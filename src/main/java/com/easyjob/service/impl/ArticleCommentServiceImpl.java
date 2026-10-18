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
import com.easyjob.service.ArticleCommentAnchorService;
import com.easyjob.service.ArticleAccessService;
import com.easyjob.entity.Article;
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
    @Autowired
    private ArticleCommentAnchorService anchors;
    @Autowired
    private ArticleAccessService access;
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
        requireReadable(articleMapper.selectById(articleId));
        if(sort == null || sort.isEmpty()) {
            sort = "create_time";
        }
        Page<ArticleComment> pageParam = new Page<>(safePage(page),safeSize(size));
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
        return PageVO.fromIPage(pageData,views(comments));
    }

    @Override
    public PageVO getQuoteComments(Long articleId, Integer page, Integer size) {
        requireReadable(articleMapper.selectById(articleId));
        var result = anchors.page(articleId,safePage(page),safeSize(size));
        return PageVO.fromIPage(result,views(result.getRecords()));
    }
    @Override
    public PageVO getSelectedQuoteComments(Long articleId,Integer page,Integer size,List<Long> ids) {
        requireReadable(articleMapper.selectById(articleId));
        if(ids == null || ids.isEmpty() || ids.size()>50 || ids.stream().anyMatch(id->id == null || id<=0))
            throw new BusinessException(400,"评论定位参数无效");
        var result=anchors.selectedPage(articleId,safePage(page),safeSize(size),ids.stream().distinct().toList());
        return PageVO.fromIPage(result,views(result.getRecords()));
    }
    @Override
    public Map<String,Object> getQuoteMarkers(Long articleId,Long afterId,Integer size) {
        requireReadable(articleMapper.selectById(articleId));
        if(afterId == null || afterId < 0) throw new BusinessException(400,"评论位置游标无效");
        return anchors.markers(articleId,afterId,size == null?200:Math.max(1,Math.min(200,size)));
    }

    private List<ArticleCommentVO> views(List<ArticleComment> comments) {
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
        anchors.attach(list);
        return list;
    }
    private int safePage(Integer page) { return page == null ? 1 : Math.max(1,page); }
    private int safeSize(Integer size) { return size == null ? 20 : Math.max(1,Math.min(50,size)); }
    private Article requireReadable(Article article) {
        if(article == null || !Integer.valueOf(1).equals(article.getStatus()) || Integer.valueOf(1).equals(article.getDeleted()))
            throw new BusinessException(404,"文章不存在或不可访问");
        if(!access.canRead(UserContext.getUserId(),article.getUserId(),article.getRequiredLevel() == null ? 0 : article.getRequiredLevel()))
            throw new BusinessException(403,"尚未达到文章阅读等级");
        return article;
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
        var parent = articleCommentMapper.selectById(commentId);
        if(parent == null || !Integer.valueOf(0).equals(parent.getStatus())) throw new BusinessException(404,"评论不存在");
        requireReadable(articleMapper.selectById(parent.getArticleId()));
        Page<ArticleComment> pageParam = new Page<>(safePage(page),safeSize(size));
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
        if(UserContext.getUserId() == null) throw new BusinessException(401,"请先登录");
        if (!commentCreateDTO.isContentValid()) {
            throw new BusinessException("评论内容无效");
        }
        Article liveArticle = requireReadable(anchors.lockArticle(commentCreateDTO.getArticleId()));
        if(!commentCreateDTO.isTopLevelComment() && commentCreateDTO.getQuote() != null)
            throw new BusinessException(400,"回复沿用所属评论的原文，不另建引用");
        var quote = anchors.validate(commentCreateDTO.getQuote(),liveArticle.getContent());
        ArticleComment articleComment = new ArticleComment();
        //传入dto中的属性
        articleComment.setArticleUserId(liveArticle.getUserId());
        articleComment.setArticleId(commentCreateDTO.getArticleId());
        articleComment.setContent(commentCreateDTO.getContent());
        articleComment.setImgPath(commentCreateDTO.getImgPath());
        articleComment.setReplyCount(0);
        articleComment.setStatus(0);
        articleComment.setLikeCount(0);
        articleComment.setTopType(0);
        //设置创建时间
        articleComment.setCreateTime(LocalDateTime.now());
        articleComment.setUpdateTime(LocalDateTime.now());
        //设置评论者的冗余字段
        User user = userMapper.selectById(UserContext.getUserId());
        if(user == null) throw new BusinessException(401,"请重新登录");
        articleComment.setUserId(UserContext.getUserId());
        articleComment.setUserNickName(user.getNickName());
        articleComment.setUserAvatar(user.getAvatar());
        //判断是否是顶级评论
        if(commentCreateDTO.getParentId()== null||commentCreateDTO.getParentId()==0){
            articleComment.setParentId(0L);
            articleComment.setReplyCount(0);
            //插入顶级评论
            articleCommentMapper.insert(articleComment);
            anchors.save(articleComment.getCommentId(),quote);
            //更新文章的评论数
            articleMapper.changeCommentCount(commentCreateDTO.getArticleId(),1);

        }else {
            //不是顶级评论，则是回复，获取父级评论（必须是顶级评论）
            ArticleComment parentComment = articleCommentMapper.selectById(commentCreateDTO.getParentId());
            if(parentComment==null || !Objects.equals(parentComment.getArticleId(),liveArticle.getArticleId())
                    || !Integer.valueOf(0).equals(parentComment.getStatus())){
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
        String articleTitle = liveArticle.getTitle();
        String preview = truncate(commentCreateDTO.getContent(), 100);

        // 给文章作者（评论了你的文章）
        notificationService.send(NotificationMessage.builder()
                .userId(liveArticle.getUserId())
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
                && !commentCreateDTO.getReplyUserId().equals(liveArticle.getUserId())) {
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
        var created = convertToVO(articleComment);
        created.setQuote(quote);
        return created;
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
        Long actor = UserContext.getUserId();
        if(actor == null || (!actor.equals(articleComment.getUserId()) && !access.isAdmin(actor)))
            throw new BusinessException(403,"只能删除自己的评论");
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
