package com.easyjob.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.easyjob.entity.ArticleCategory;
import com.easyjob.vo.CategoryVO;

import java.util.List;

public interface ArticleCategoryService extends IService<ArticleCategory> {
    List<CategoryVO> listAll();
}
