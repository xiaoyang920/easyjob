package com.easyjob.controller;

import com.easyjob.dto.ShareDTO;
import com.easyjob.service.ArticleService;
import com.easyjob.vo.ResponseVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/share")
public class ShareController {
    /**
     * 记录分享行为
     */
    @Autowired
    private ArticleService articleService;
    @PostMapping("/record")
    public ResponseVO record(@RequestBody ShareDTO shareDTO) {
        Integer count = articleService.recordArticleShare(shareDTO);
        return ResponseVO.success("分享成功",count);
    }
}
