package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.ArticleCategory;
import com.easyjob.vo.CategoryVO;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

@Mapper
public interface ArticleCategoryMapper extends BaseMapper<ArticleCategory> {
    List<CategoryVO> listAll();
}
