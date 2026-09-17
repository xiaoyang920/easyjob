package com.easyjob.controller;

import com.easyjob.service.ArticleCategoryService;
import com.easyjob.vo.CategoryVO;
import com.easyjob.vo.ResponseVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/category")
public class ArticleCategoryController {
    @Autowired
    private ArticleCategoryService articleCategoryService;
    /**
     * 获取文章分类(包含二级分类)列表
     */
    @RequestMapping("/list")
    public ResponseVO list() {
        List<CategoryVO> categoryVO = articleCategoryService.listAll();
        return ResponseVO.success("获取文章分类列表成功",categoryVO);
    }
}
