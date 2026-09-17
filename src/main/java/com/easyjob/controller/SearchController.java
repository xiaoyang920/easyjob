package com.easyjob.controller;

import com.easyjob.component.EsComponent;
import com.easyjob.vo.ArticleSearchVO;
import com.easyjob.vo.PageVO;
import com.easyjob.vo.ResponseVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Slf4j
@RequestMapping("/api")
public class SearchController {
    
    @Autowired
    private EsComponent esComponent;
    
    /**
     * 搜索文章
     * @param keyword 关键词
     * @param orderType 排序类型: 0=点赞数, 1=时间, 2=评论数, 3=收藏数, null=相关度
     * @param pageNo 页码
     * @param pageSize 每页数量
     * @param highlight 是否高亮
     * @return 搜索结果
     */
    @GetMapping("/search")
    public ResponseVO<PageVO<ArticleSearchVO>> search(
            @RequestParam String keyword,
            @RequestParam(required = false) Integer orderType,
            @RequestParam(defaultValue = "1") Integer pageNo,
            @RequestParam(defaultValue = "20") Integer pageSize,
            @RequestParam(defaultValue = "true") Boolean highlight) {
        
        PageVO<ArticleSearchVO> result = esComponent.search(highlight, keyword, orderType, pageNo, pageSize);
        return ResponseVO.success(result);
    }
}
