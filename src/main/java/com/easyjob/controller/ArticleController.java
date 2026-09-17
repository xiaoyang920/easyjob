package com.easyjob.controller;

import com.easyjob.component.RedisComponent;
import com.easyjob.dto.ArticleCreateDTO;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.service.ArticleService;
import com.easyjob.service.RecommendService;
import com.easyjob.utils.JwtUtil;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import jakarta.servlet.http.HttpServletRequest;

@RestController
@RequestMapping("/api/article")
@Slf4j
public class ArticleController {
    @Autowired
    private ArticleService articleService;
    
    @Autowired
    private JwtUtil jwtUtil;
    @Autowired
    private RedisComponent redisComponent;
    @Autowired
    private RecommendService recommendService;
    @Autowired
    private ArticleMapper articleMapper;

    /**
     * 获取用户文章列表
     * @param userId
     * @param page
     * @param size
     * @param order
     * @return
     */
    @GetMapping("/user/{userId}")
    public ResponseVO<?> getUserArticles(@PathVariable Long userId, 
                                         @RequestParam(defaultValue = "1") Integer page,
                                         @RequestParam(defaultValue = "10") Integer size,
                                         @RequestParam(defaultValue = "latest") String order) {
        return ResponseVO.success(articleService.getUserArticles(userId, page, size, order));
    }
    /**
     * 发布文章
     * @param article
     * @return
     */
    @PostMapping( "/create")
    public ResponseVO<?> create(@RequestBody ArticleCreateDTO article) {
        articleService.saveArticle(article);
        redisComponent.deleteUserSpaceVO(UserContext.getUserId());
        return ResponseVO.success("发布成功");
    }
    /**
     * 获取文章详情
     * @param articleId
     * @return
     */
    @GetMapping("/detail/{articleId}")
    public ResponseVO<?> get(@PathVariable Long articleId, HttpServletRequest request) {
        // 可选认证：如果有token则设置UserContext，用于获取点赞/收藏状态
        try {
            String authorization = request.getHeader("Authorization");
            if (authorization != null && !authorization.isEmpty()) {
                String token = jwtUtil.getTokenFromAuthorization(authorization);
                if (token != null && jwtUtil.validateToken(token)) {
                    Long userId = jwtUtil.getUserIdFromToken(token);
                    UserContext.setUserId(userId);
                    log.info("文章详情可选认证成功 - userId: {}", userId);
                }
            }
        } catch (Exception e) {
            log.warn("文章详情token解析失败（忽略）: {}", e.getMessage());
        }
        try {
            return ResponseVO.success(articleService.getArticleById(articleId));
        } finally {
            // 清理UserContext
            UserContext.clear();
        }
    }
    /**
     * 删除文章
     * @param articleId
     * @return
     */
    @DeleteMapping("/{articleId}")
    public ResponseVO<?> delete(@PathVariable Long articleId) {
        articleService.deleteArticle(articleId);
        redisComponent.deleteArticleDetail(articleId);
        return ResponseVO.success("删除成功");
    }
    /**
     * 修改文章
     * @param articleId
     * @param article
     * @return
     */
    @PutMapping("/{articleId}")
    public ResponseVO<?> update(@PathVariable Long articleId, @RequestBody ArticleCreateDTO article) {
        articleService.updateArticle(articleId, article);
        redisComponent.deleteArticleDetail(articleId);
        return ResponseVO.success("修改成功");
    }
    /**
     * 获取草稿列表
     * @param page
     * @param size
     * @return
     */
    @GetMapping("/drafts")
    public ResponseVO<?> getDrafts(@RequestParam(defaultValue = "1") Integer page,
                                   @RequestParam(defaultValue = "10") Integer size) {
        return ResponseVO.success(articleService.getDrafts(page, size));
    }

    /**
     * 发布
     * @param articleId
     * @return
     */
    @PostMapping("/{articleId}/publish")
    public ResponseVO<?> publish(@PathVariable Long articleId) {
        articleService.publish(articleId);
        return ResponseVO.success("发布成功");
    }
    /**
     * 获取文章列表（主界面/公开）
     * 不需要登录，返回已发布的文章
     */
    @GetMapping("/list")
    public ResponseVO<?> list(
            @RequestParam(defaultValue = "1") Integer page,
            @RequestParam(defaultValue = "10") Integer size,
            @RequestParam(defaultValue = "latest") String sort,
            @RequestParam(required = false) Long categoryId,
            @RequestParam(required = false) String keyword) {
        
        // 限制 size 最大值
        if (size > 100) {
            size = 100;
        }
        return ResponseVO.success(articleService.listArticles(page, size, sort, categoryId, keyword));
    }

    /**
     * 增加文章浏览数=
     * @param articleId
     * @return
     */
    @PostMapping("/{articleId}/view")
    public ResponseVO<?> increaseViewCount(@PathVariable Long articleId) {
        articleService.increaseViewCount(articleId);
        return ResponseVO.success("浏览数增加成功");
    }
    /**
     * 推荐文章（可选认证：登录返回个性化推荐，未登录返回热门）
     * @param limit
     * @param request
     * @return
     */
    @GetMapping("recommend")
    public ResponseVO<?> recommend(@RequestParam(defaultValue = "20") Integer limit, HttpServletRequest request) {
        // 可选认证：如果有token则设置UserContext
        try {
            String authorization = request.getHeader("Authorization");
            if (authorization != null && !authorization.isEmpty()) {
                String token = jwtUtil.getTokenFromAuthorization(authorization);
                if (token != null && jwtUtil.validateToken(token)) {
                    UserContext.setUserId(jwtUtil.getUserIdFromToken(token));
                }
            }
        } catch (Exception e) {
            log.warn("推荐接口token解析失败（忽略）: {}", e.getMessage());
        }
        try {
            Long userId = UserContext.getUserId();
            if (userId == null) {
                return ResponseVO.success(articleMapper.selectHotArticles(limit));
            }
            return ResponseVO.success(recommendService.recommend(userId, limit));
        } finally {
            UserContext.clear();
        }
    }
}
