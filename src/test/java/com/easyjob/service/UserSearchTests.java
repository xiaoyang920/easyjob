package com.easyjob.service;

import com.easyjob.component.EsComponent;
import com.easyjob.controller.SearchController;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.UserMapper;
import com.easyjob.utils.JwtUtil;
import com.easyjob.vo.UserSearchVO;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.builder.xml.XMLMapperBuilder;
import org.apache.ibatis.io.Resources;
import org.apache.ibatis.session.Configuration;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.List;
import java.util.HashMap;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class UserSearchTests {
    @Test void escapesLiteralWildcardsAndPaginates() {
        UserMapper mapper = mock(UserMapper.class);
        when(mapper.countSearchUsers("%C!%!_!!%")).thenReturn(12L);
        UserSearchVO user = new UserSearchVO(); user.setUserId("9007199254740993");
        when(mapper.searchUsers("C%_!", "%C!%!_!!%", 7L, 10, 10)).thenReturn(List.of(user));
        var page = new UserSearchService(mapper).search(" C%_! ", 2, 10, 7L);
        assertEquals(12L, page.getTotal()); assertEquals(2L, page.getPages());
        assertEquals("9007199254740993", page.getRecords().getFirst().getUserId());
    }
    @Test void rejectsUnboundedPaginationAndInvalidQueries() {
        UserMapper mapper = mock(UserMapper.class); var service = new UserSearchService(mapper);
        assertThrows(BusinessException.class, () -> service.search(" ", 1, 10, null));
        assertThrows(BusinessException.class, () -> service.search("x".repeat(201), 1, 10, null));
        assertThrows(BusinessException.class, () -> service.search("x", 0, 10, null));
        assertThrows(BusinessException.class, () -> service.search("x", 1, 51, null));
        assertThrows(BusinessException.class, () -> service.search("x", 10001, 10, null));
        verifyNoInteractions(mapper);
    }
    @Test void emptySearchDoesNotIssuePageQuery() {
        UserMapper mapper = mock(UserMapper.class);
        var page = new UserSearchService(mapper).search("Nobody", 1, 10, null);
        assertTrue(page.getRecords().isEmpty()); assertEquals(0L, page.getTotal());
        verify(mapper).countSearchUsers("%Nobody%"); verifyNoMoreInteractions(mapper);
    }
    @Test void publicEndpointAndOptionalCredentialsPreserveFollowStatus() throws Exception {
        UserMapper mapper = mock(UserMapper.class); JwtUtil jwt = mock(JwtUtil.class);
        when(mapper.countSearchUsers("%Alice%")).thenReturn(1L);
        UserSearchVO user = new UserSearchVO(); user.setUserId("7"); user.setNickName("Alice");
        user.setIsFollowing(false);
        when(mapper.searchUsers("Alice", "%Alice%", null, 0, 10)).thenReturn(List.of(user));
        SearchController controller = new SearchController();
        ReflectionTestUtils.setField(controller, "userSearchService", new UserSearchService(mapper));
        ReflectionTestUtils.setField(controller, "jwtUtil", jwt);
        ArticleSearchService articleSearch = mock(ArticleSearchService.class); ReflectionTestUtils.setField(controller, "articleSearch", articleSearch);
        MockMvc mvc = MockMvcBuilders.standaloneSetup(controller).build();
        mvc.perform(get("/api/search/users").param("keyword", "Alice"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.records[0].nickName").value("Alice"))
                .andExpect(jsonPath("$.data.records[0].password").doesNotExist())
                .andExpect(jsonPath("$.data.records[0].email").doesNotExist());
        when(jwt.getTokenFromAuthorization("Bearer bad")).thenReturn("bad");
        when(jwt.validateToken("bad")).thenReturn(false);
        mvc.perform(get("/api/search/users").param("keyword", "Alice").header("Authorization", "Bearer bad"))
                .andExpect(status().isOk());
        when(jwt.getTokenFromAuthorization("Bearer valid")).thenReturn("valid");
        when(jwt.validateToken("valid")).thenReturn(true); when(jwt.getUserIdFromToken("valid")).thenReturn(9L);
        user.setIsFollowing(true);
        when(mapper.searchUsers("Alice", "%Alice%", 9L, 0, 10)).thenReturn(List.of(user));
        mvc.perform(get("/api/search/users").param("keyword", "Alice").header("Authorization", "Bearer valid"))
                .andExpect(jsonPath("$.data.records[0].isFollowing").value(true));
        verifyNoInteractions(articleSearch);
    }
    @Test void realMapperOnlySelectsPublicUsersAndPublishedArticleCounts() throws Exception {
        Configuration config = new Configuration();
        try (var input = Resources.getResourceAsStream("mapper/UserMapper.xml")) {
            new XMLMapperBuilder(input, config, "mapper/UserMapper.xml", config.getSqlFragments()).parse();
        }
        var params = new HashMap<String, Object>(); params.put("pattern", "%Alice%");
        params.put("keyword", "Alice"); params.put("viewerId", null); params.put("offset", 0); params.put("limit", 10);
        String sql = config.getMappedStatement("com.easyjob.mapper.UserMapper.searchUsers").getBoundSql(params).getSql();
        assertTrue(sql.contains("u.status = 1")); assertTrue(sql.contains("a.status = 1"));
        assertTrue(sql.contains("ESCAPE '!'") && sql.contains("LIMIT ? OFFSET ?"));
        assertFalse(sql.contains("email") || sql.contains("password") || sql.contains("u.*"));
        assertFalse(new ObjectMapper().valueToTree(new UserSearchVO()).has("lastLoginIp"));
    }
}
