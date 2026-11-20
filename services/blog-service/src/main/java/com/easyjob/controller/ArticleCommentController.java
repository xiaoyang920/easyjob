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
import jakarta.servlet.http.HttpServletRequest;
import com.easyjob.utils.JwtUtil;
import com.easyjob.utils.UserContext;
import java.util.function.Supplier;

@RestController
@RequestMapping("/api/comment")
public class ArticleCommentController {
    @Autowired
    private ArticleCommentService articleCommentService;
    @Autowired private JwtUtil jwtUtil;
    private ResponseVO read(HttpServletRequest request, Supplier<PageVO> query) {
        Long previous = UserContext.getUserId();
        try {
            UserContext.setUserId(jwtUtil.resolveOptionalUserId(request.getHeader("Authorization")));
            return ResponseVO.success("获取评论成功",query.get());
        } finally {
            if(previous == null) UserContext.clear(); else UserContext.setUserId(previous);
        }
    }
    /**
     * 获取文章评论列表
     */
    @GetMapping("/list")
    public ResponseVO list(Long articleId, Integer page, Integer size,String sort, HttpServletRequest request) {
        return read(request,()->articleCommentService.getCommentList(articleId, page, size, sort));
    }
    @GetMapping("/quotes")
    public ResponseVO quotes(@RequestParam Long articleId,
                             @RequestParam(defaultValue="1") Integer page,
                             @RequestParam(defaultValue="20") Integer size,
                             @RequestParam(required=false) java.util.List<Long> ids, HttpServletRequest request) {
        return read(request,()->ids == null ? articleCommentService.getQuoteComments(articleId,page,size)
                :articleCommentService.getSelectedQuoteComments(articleId,page,size,ids));
    }
    @GetMapping("/quote-markers")
    public ResponseVO markers(@RequestParam Long articleId,@RequestParam(defaultValue="0") Long afterId,
                              @RequestParam(defaultValue="200") Integer size,HttpServletRequest request) {
        Long previous=UserContext.getUserId();
        try {
            UserContext.setUserId(jwtUtil.resolveOptionalUserId(request.getHeader("Authorization")));
            return ResponseVO.success(articleCommentService.getQuoteMarkers(articleId,afterId,size));
        } finally { if(previous == null) UserContext.clear(); else UserContext.setUserId(previous); }
    }
    /**
     * 获取文章回复评论列表
     */
    @GetMapping("/replies")
    public ResponseVO replies(Long commentId, Integer page, Integer size, HttpServletRequest request) {
        return read(request,()->articleCommentService.getReplies(commentId,page,size));
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
