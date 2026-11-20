package com.easyjob.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.easyjob.entity.UserAction;
import com.easyjob.vo.ArticleListVO;
import com.easyjob.vo.PageVO;

import java.util.List;


public interface UserActionService extends IService<UserAction> {
    record InteractionResult(boolean active, int count) {}

    void like(Long articleId);

    void collect(Long articleId);

    InteractionResult like(Long articleId, Boolean active);

    InteractionResult collect(Long articleId, Boolean active);

    PageVO<ArticleListVO> getUserCollect(Long userId, Integer page, Integer size, Integer type, String order);

    PageVO<ArticleListVO> getUserLike(Long userId, Integer page, Integer size, Integer type, String order);
}
