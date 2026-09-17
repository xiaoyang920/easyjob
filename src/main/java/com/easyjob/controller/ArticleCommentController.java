package com.easyjob.controller;

import com.easyjob.dto.ArticleCreateDTO;
import com.easyjob.dto.CommentActionDTO;
import com.easyjob.dto.CommentCreateDTO;
import com.easyjob.service.ArticleCommentService;
import com.easyjob.vo.ArticleCommentVO;
import com.easyjob.vo.CommentActionVO;
import com.easyjob.vo.PageVO;
import com.easyjob.vo.ResponseVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/comment")
public class ArticleCommentController {
    @Autowired
    private ArticleCommentService articleCommentService;
    /**
     * 获取文章评论列表
     */
    @GetMapping("/list")
    public ResponseVO list(Long articleId, Integer page, Integer size,String sort) {
        PageVO pageVO = articleCommentService.getCommentList(articleId, page, size, sort);
        return ResponseVO.success("获取文章评论列表成功",pageVO);
    }
    /**
     * 获取文章回复评论列表
     */
    @GetMapping("/replies")
    public ResponseVO replies(Long commentId, Integer page, Integer size) {
        PageVO pageVO = articleCommentService.getReplies(commentId, page, size);
        return ResponseVO.success("获取文章回复评论列表成功",pageVO);
    }
    /**
     * 创建文章评论
     */
    @PostMapping("/create")
    public ResponseVO create(@RequestBody CommentCreateDTO commentCreateDTO) {
        ArticleCommentVO articleCommentVO = articleCommentService.create(commentCreateDTO);
        return ResponseVO.success("创建文章评论成功",articleCommentVO);
    }
    /**
     * 删除文章评论
     */
    @DeleteMapping("/{commentId}")
    public ResponseVO delete(@PathVariable Long commentId) {
        articleCommentService.removeComment(commentId);
        return ResponseVO.success("删除文章评论成功");
    }
    @PostMapping("/{commentId}/action")
    public ResponseVO like(@PathVariable Long commentId, @RequestBody CommentActionDTO commentActionDTO) {
        CommentActionVO commentActionVO = articleCommentService.action(commentId, commentActionDTO);
        return ResponseVO.success("操作成功",commentActionVO);
    }
}
