package com.easyjob.controller;

import com.easyjob.service.ArticleTagService;
import com.easyjob.vo.ResponseVO;
import com.easyjob.vo.TagVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 标签控制器
 * 提供标签搜索、热门标签等接口
 */
@RestController
@RequestMapping("/api/tag")
public class TagController {
    
    @Autowired
    private ArticleTagService articleTagService;
    
    /**
     * 搜索标签（用于输入联想）
     * @param keyword 搜索关键词
     * @param limit 返回数量限制（默认5）
     */
    @GetMapping("/search")
    public ResponseVO<List<TagVO>> searchTags(
            @RequestParam String keyword,
            @RequestParam(defaultValue = "5") Integer limit) {
        List<TagVO> tags = articleTagService.searchTags(keyword, limit);
        return ResponseVO.success(tags);
    }
    
    /**
     * 获取热门标签
     * @param limit 返回数量限制（默认10）
     */
    @GetMapping("/hot")
    public ResponseVO<List<TagVO>> getHotTags(
            @RequestParam(defaultValue = "10") Integer limit) {
        List<TagVO> tags = articleTagService.getHotTags(limit);
        return ResponseVO.success(tags);
    }
    
    /**
     * 根据文章ID获取标签列表
     * @param articleId 文章ID
     */
    @GetMapping("/article/{articleId}")
    public ResponseVO<List<TagVO>> getTagsByArticleId(@PathVariable Long articleId) {
        List<TagVO> tags = articleTagService.getTagsByArticleId(articleId);
        return ResponseVO.success(tags);
    }
}
