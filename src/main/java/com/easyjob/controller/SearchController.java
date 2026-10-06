package com.easyjob.controller;

import com.easyjob.component.EsComponent;
import com.easyjob.service.UserSearchService;
import com.easyjob.utils.JwtUtil;
import com.easyjob.vo.UserSearchVO;
import org.springframework.web.bind.annotation.RequestHeader;
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
    @Autowired
    private UserSearchService userSearchService;
    @Autowired
    private JwtUtil jwtUtil;
    @Autowired private org.springframework.jdbc.core.JdbcTemplate jdbc;

    @GetMapping("/search/users")
    public ResponseVO<PageVO<UserSearchVO>> searchUsers(@RequestParam String keyword,
            @RequestParam(defaultValue = "1") Integer pageNo,
            @RequestParam(defaultValue = "10") Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        Long viewerId = null;
        // Search is public. A valid optional token only enriches follow status.
        if (authorization != null) {
            try {
                String token = jwtUtil.getTokenFromAuthorization(authorization);
                if (token != null && jwtUtil.validateToken(token)) viewerId = jwtUtil.getUserIdFromToken(token);
            } catch (Exception ignored) { /* Invalid optional credentials remain anonymous. */ }
        }
        return ResponseVO.success(userSearchService.search(keyword, pageNo, pageSize, viewerId));
    }
    
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
        if(!result.getRecords().isEmpty()) {
            var ids=result.getRecords().stream().map(a->Long.valueOf(a.getArticleId())).toList();
            String placeholders=String.join(",",java.util.Collections.nCopies(ids.size(),"?"));
            var rows=jdbc.queryForList("SELECT article_id,required_level,summary FROM article_info WHERE status=1 AND deleted=0 AND article_id IN ("+placeholders+")",ids.toArray());
            var current=new java.util.HashMap<String,java.util.Map<String,Object>>();
            for(var row:rows) current.put(row.get("article_id").toString(),row);
            result.setRecords(result.getRecords().stream().filter(a->current.containsKey(a.getArticleId())).peek(a->{
                var row=current.get(a.getArticleId());
                a.setRequiredLevel(((Number)row.get("required_level")).intValue());
                a.setSummary((String)row.get("summary"));
            }).toList());
        }
        return ResponseVO.success(result);
    }
}
