package com.easyjob.entity;

import com.easyjob.dto.CommentQuote;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
public class ArticleCommentAnchor extends CommentQuote {
    private Long commentId;
}
