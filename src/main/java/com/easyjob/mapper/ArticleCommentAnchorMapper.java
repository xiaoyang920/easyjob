package com.easyjob.mapper;

import com.easyjob.dto.CommentQuote;
import com.easyjob.entity.ArticleCommentAnchor;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.easyjob.entity.Article;
import com.easyjob.entity.ArticleComment;

@Mapper
public interface ArticleCommentAnchorMapper {
    void insert(@Param("commentId") Long commentId, @Param("quote") CommentQuote quote);
    List<ArticleCommentAnchor> findByComments(@Param("ids") List<Long> ids);
    IPage<ArticleComment> findComments(Page<ArticleComment> page, @Param("articleId") Long articleId);
    IPage<ArticleComment> findSelectedComments(Page<ArticleComment> page, @Param("articleId") Long articleId,
                                               @Param("ids") List<Long> ids);
    List<ArticleCommentAnchor> findMarkers(@Param("articleId") Long articleId, @Param("afterId") Long afterId,
                                          @Param("limit") int limit);
    Article lockArticle(@Param("articleId") Long articleId);
}
