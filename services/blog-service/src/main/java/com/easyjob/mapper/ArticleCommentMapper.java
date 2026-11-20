package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.ArticleComment;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface ArticleCommentMapper extends BaseMapper<ArticleComment> {
    void changeCommentCount(Long commentId, int i);

    void changeLikeCount(Long commentId, int i);
}
