package com.easyjob.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.component.RedisComponent;
import com.easyjob.entity.ArticleCategory;
import com.easyjob.mapper.ArticleCategoryMapper;
import com.easyjob.service.ArticleCategoryService;
import com.easyjob.vo.CategoryVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@Slf4j
public class ArticleCategoryServiceImpl extends ServiceImpl<ArticleCategoryMapper, ArticleCategory> implements ArticleCategoryService {
    @Autowired
    private ArticleCategoryMapper articleCategoryMapper;
    @Autowired
    private RedisComponent redisComponent;
    @Override
    public List<CategoryVO> listAll() {
        // 分类体积小，直接读取可避免新增分类后旧缓存或并发回填影响可见性。
        return articleCategoryMapper.listAll();
    }
}
