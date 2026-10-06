package com.easyjob.mapper;

import com.easyjob.vo.ArticleListVO;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.builder.xml.XMLMapperBuilder;
import org.apache.ibatis.executor.Executor;
import org.apache.ibatis.executor.parameter.ParameterHandler;
import org.apache.ibatis.executor.resultset.DefaultResultSetHandler;
import org.apache.ibatis.io.Resources;
import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.RowBounds;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.Statement;
import java.sql.Types;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ArticleAuthorMappingTests {
    @ParameterizedTest
    @ValueSource(strings = {"listArticles", "listUserCollectionOrLike", "selectHotArticles",
            "selectRecommendArticles", "selectHotArticlesExclude", "listRecommendedArticles"})
    void listQueryPreservesAuthorThroughMybatisAndJson(String query) throws Exception {
        Configuration configuration = new Configuration();
        try (var source = Resources.getResourceAsStream("mapper/ArticleMapper.xml")) {
            new XMLMapperBuilder(source, configuration, "mapper/ArticleMapper.xml",
                    configuration.getSqlFragments()).parse();
        }
        Map<String, Object> parameters = new HashMap<>();
        parameters.put("sort", "latest");
        parameters.put("order", "latest");
        parameters.put("categoryId", null);
        parameters.put("keyword", null);
        parameters.put("userId", 7L);
        parameters.put("type", 2);
        parameters.put("limit", 3);
        parameters.put("topTagIds", List.of(1L));
        parameters.put("excludeIds", List.of(99L));
        parameters.put("tagIds", List.of(1L));
        MappedStatement statement = configuration.getMappedStatement(
                "com.easyjob.mapper.ArticleMapper." + query);
        BoundSql sql = statement.getBoundSql(parameters);
        String nicknameColumn = selectedAlias(sql.getSql(), "nick_name");
        String avatarColumn = selectedAlias(sql.getSql(), "avatar");

        // Use the labels from the real mapper SQL and the real MyBatis result handler.
        // The previous VO silently discarded these columns, producing a generic byline.
        ResultSetMetaData metadata = mock(ResultSetMetaData.class);
        String[] labels = {"articleId", nicknameColumn, avatarColumn};
        when(metadata.getColumnCount()).thenReturn(labels.length);
        for (int i = 0; i < labels.length; i++) {
            when(metadata.getColumnLabel(i + 1)).thenReturn(labels[i]);
            when(metadata.getColumnType(i + 1)).thenReturn(Types.VARCHAR);
            when(metadata.getColumnClassName(i + 1)).thenReturn(String.class.getName());
        }
        Map<String, String> values = Map.of("articleId", "42", nicknameColumn, "真实作者",
                avatarColumn, "/uploads/avatars/author.png");
        ResultSet resultSet = mock(ResultSet.class);
        when(resultSet.getMetaData()).thenReturn(metadata);
        when(resultSet.next()).thenReturn(true, false);
        when(resultSet.getString(anyString())).thenAnswer(call -> values.get(call.getArgument(0)));
        Statement jdbc = mock(Statement.class);
        when(jdbc.getResultSet()).thenReturn(resultSet);
        when(jdbc.getUpdateCount()).thenReturn(-1);

        var handler = new DefaultResultSetHandler(mock(Executor.class), statement,
                mock(ParameterHandler.class), null, sql, RowBounds.DEFAULT);
        var records = handler.handleResultSets(jdbc);
        assertEquals(1, records.size());
        ArticleListVO article = (ArticleListVO) records.getFirst();
        var response = new ObjectMapper().valueToTree(article);
        assertEquals("真实作者", response.path("authorName").asText());
        assertEquals("/uploads/avatars/author.png", response.path("authorAvatar").asText());
    }

    private static String selectedAlias(String sql, String column) {
        var match = Pattern.compile("u\\." + column + "\\s+(?:AS\\s+)?(\\w+)",
                Pattern.CASE_INSENSITIVE).matcher(sql);
        assertTrue(match.find(), "Query must select the author's " + column);
        return match.group(1);
    }
}
