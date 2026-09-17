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
        //先从redis中获取，如果为空则从数据库中获取
        List<CategoryVO> categoryVOList = redisComponent.getCategories();
        if(categoryVOList != null&& !categoryVOList.isEmpty()){
            log.info("从redis中获取文章分类列表");
            return categoryVOList;
        }
        categoryVOList = articleCategoryMapper.listAll();
        redisComponent.saveCategories(categoryVOList);
        return categoryVOList;
    }
}
