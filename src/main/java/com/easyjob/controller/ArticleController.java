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
import jakarta.servlet.http.HttpServletResponse;
import com.easyjob.service.ArticleReadService;
import com.easyjob.utils.ArticleReaderIdentity;

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
    @Autowired private ArticleReadService articleReadService;
    @Autowired private ArticleReaderIdentity readerIdentity;
    @Autowired private com.easyjob.service.ArticleAccessService articleAccess;
    @Autowired private com.easyjob.service.ArticleRevisionService revisions;
    public record SubmitRequest(String expectedRevisionId,Long expectedLockVersion) {}
    public record ReadingLevelRequest(Integer level) {}
    @PutMapping("/{articleId}/reading-level")
    public ResponseVO<?> readingLevel(@PathVariable Long articleId,@RequestBody ReadingLevelRequest request) {
        articleAccess.setRequiredLevel(articleId,UserContext.getUserId(),request.level());
        return ResponseVO.success("阅读等级已更新");
    }

    private Long optionalUser(HttpServletRequest request) {
        return jwtUtil.resolveOptionalUserId(request.getHeader("Authorization"));
    }

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
        Long articleId = articleService.saveArticle(article);
        return ResponseVO.success(java.util.Map.of("articleId", articleId.toString()));
    }
    /**
     * 获取文章详情
     * @param articleId
     * @return
     */
    @GetMapping("/detail/{articleId}")
    public ResponseVO<?> get(@PathVariable Long articleId, HttpServletRequest request, HttpServletResponse response) {
        readerIdentity.resolve(request, response, optionalUser(request));
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
        return ResponseVO.success(articleService.getEditableArticle(articleId));
    }

    @GetMapping("/{articleId}/edit")
    public ResponseVO<?> edit(@PathVariable Long articleId) {
        return ResponseVO.success(articleService.getEditableArticle(articleId));
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
    public ResponseVO<?> publish(@PathVariable Long articleId,@RequestBody SubmitRequest request) {
        return ResponseVO.success(revisions.submit(UserContext.getUserId(),articleId,request.expectedRevisionId(),request.expectedLockVersion()));
    }
    @GetMapping("/{articleId}/revisions") public ResponseVO<?> history(@PathVariable Long articleId){return ResponseVO.success(revisions.history(UserContext.getUserId(),articleId));}
    @GetMapping("/{articleId}/revisions/{revisionId}") public ResponseVO<?> revision(@PathVariable Long articleId,@PathVariable Long revisionId){return ResponseVO.success(revisions.authorDetail(UserContext.getUserId(),articleId,revisionId));}
    @PostMapping("/{articleId}/revisions/{revisionId}/restore") public ResponseVO<?> restore(@PathVariable Long articleId,@PathVariable Long revisionId,@RequestBody SubmitRequest request){return ResponseVO.success(revisions.restore(UserContext.getUserId(),articleId,revisionId,request.expectedRevisionId(),request.expectedLockVersion()));}
    @PostMapping("/{articleId}/revisions/{revisionId}/withdraw") public ResponseVO<?> withdraw(@PathVariable Long articleId,@PathVariable Long revisionId){revisions.withdraw(UserContext.getUserId(),articleId,revisionId);return ResponseVO.success("已撤回审核");}
    @PostMapping("/{articleId}/revisions/{revisionId}/discard") public ResponseVO<?> discard(@PathVariable Long articleId,@PathVariable Long revisionId){revisions.discard(UserContext.getUserId(),articleId,revisionId);return ResponseVO.success("修改版本已丢弃，公开内容未改变");}
    @GetMapping("/work") public ResponseVO<?> work(@RequestParam(required=false) Integer state,@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="10") int size){return ResponseVO.success(revisions.work(UserContext.getUserId(),state,page,size));}
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
            @RequestParam(required = false) java.util.List<Long> tagIds,
            @RequestParam(required = false) String keyword,
            @RequestParam(defaultValue = "false") boolean readableOnly, HttpServletRequest request) {
        
        // 限制 size 最大值
        if (size > 100) {
            size = 100;
        }
        return ResponseVO.success(articleService.listArticles(page, size, sort, categoryId, keyword, tagIds, optionalUser(request), readableOnly));
    }

    /**
     * 增加文章浏览数=
     * @param articleId
     * @return
     */
    @PostMapping("/{articleId}/view")
    public ResponseVO<?> increaseViewCount(@PathVariable Long articleId, HttpServletRequest request, HttpServletResponse response) {
        Long user = optionalUser(request);
        return ResponseVO.success(articleReadService.record(articleId, user, readerIdentity.resolve(request, response, user)));
    }
    /**
     * 推荐文章（可选认证：登录返回个性化推荐，未登录返回热门）
     * @param limit
     * @param request
     * @return
     */
    @GetMapping("recommend")
    public ResponseVO<?> recommend(@RequestParam(defaultValue = "20") Integer limit,
            @RequestParam(required = false) Integer page, @RequestParam(defaultValue = "12") Integer size,
            @RequestParam(required = false) Long categoryId, @RequestParam(required = false) java.util.List<Long> tagIds,
            @RequestParam(defaultValue = "false") boolean readableOnly, HttpServletRequest request) {
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
            if (page != null) return ResponseVO.success(recommendService.recommendPage(userId, page, size, categoryId, tagIds, readableOnly));
            return ResponseVO.success(recommendService.recommendPage(userId, 1, limit, categoryId, tagIds, readableOnly).getRecords());
        } finally {
            UserContext.clear();
        }
    }
}
