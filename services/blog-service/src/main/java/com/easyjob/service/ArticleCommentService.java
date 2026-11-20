package com.easyjob.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.easyjob.dto.ArticleCreateDTO;
import com.easyjob.dto.CommentActionDTO;
import com.easyjob.dto.CommentCreateDTO;
import com.easyjob.entity.ArticleComment;
import com.easyjob.vo.ArticleCommentVO;
import com.easyjob.vo.CommentActionVO;
import com.easyjob.vo.PageVO;

public interface ArticleCommentService extends IService<ArticleComment> {
    PageVO getCommentList(Long articleId, Integer page, Integer size, String sort);

    PageVO getReplies(Long commentId, Integer page, Integer size);
    PageVO getQuoteComments(Long articleId, Integer page, Integer size);
    PageVO getSelectedQuoteComments(Long articleId,Integer page,Integer size,java.util.List<Long> ids);
    java.util.Map<String,Object> getQuoteMarkers(Long articleId,Long afterId,Integer size);

    ArticleCommentVO create(CommentCreateDTO commentCreateDTO);

    void removeComment(Long commentId);

    CommentActionVO action(Long commentId, CommentActionDTO commentActionDTO);
}
