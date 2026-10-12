package com.easyjob.mapper;

import org.apache.ibatis.builder.xml.XMLMapperBuilder;
import org.apache.ibatis.io.Resources;
import org.apache.ibatis.session.Configuration;
import org.junit.jupiter.api.Test;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import static org.junit.jupiter.api.Assertions.*;

class PersistenceLayerTests {
    private Configuration mapper(String name) throws Exception {
        var config=new Configuration();
        String resource="mapper/"+name+".xml";
        try(var input=Resources.getResourceAsStream(resource)) {
            new XMLMapperBuilder(input,config,resource,config.getSqlFragments()).parse();
        }
        return config;
    }
    private String sql(Configuration config,String name,String method,Map<String,Object> params) {
        return config.getMappedStatement("com.easyjob.mapper."+name+"."+method)
            .getBoundSql(params).getSql().replaceAll("\\s+"," ").trim();
    }
    @Test void javaBusinessCodeCannotReintroduceJdbcOrSqlAnnotations() throws Exception {
        var forbidden=Pattern.compile("JdbcTemplate|ConnectionCallback|prepareStatement\\s*\\(|@(org\\.apache\\.ibatis\\.annotations\\.)?(Select|Update|Insert|Delete)\\s*\\(|\\.last\\s*\\(");
        var violations=new ArrayList<String>();
        try(var files=Files.walk(Path.of("src/main/java"))) {
            for(var file:files.filter(p->p.toString().endsWith(".java")).toList())
                if(forbidden.matcher(Files.readString(file)).find())violations.add(file.toString());
        }
        assertEquals(List.of(),violations,"Use Mapper XML for handwritten persistence statements");
    }
    @Test void operationQueuesOnlyUseLiteralTablesAndStateValuesRemainBound() throws Exception {
        String name="AdminOperationsMapper";var config=mapper(name);
        for(var queue:List.of("article","memory")) {
            var params=new HashMap<String,Object>();params.put("queue",queue);params.put("state","dead");params.put("size",20);params.put("offset",0);
            String table=queue.equals("article")?"article_index_outbox":"agent_background_job";
            assertTrue(sql(config,name,"findJobs",params).contains("FROM "+table+" WHERE status=?"));
            assertTrue(sql(config,name,"countJobs",params).contains("FROM "+table+" WHERE status=?"));
            params.put("state","all");assertFalse(sql(config,name,"countJobs",params).contains("WHERE status"));
            params.put("queue","article;DROP TABLE user_info");
            assertFalse(sql(config,name,"countJobs",params).contains("DROP"));
        }
    }
    @Test void searchEmptyIdsNeverTurnIntoAnUnrestrictedArticleQuery() throws Exception {
        var config=mapper("ArticleSearchMapper");
        assertTrue(sql(config,"ArticleSearchMapper","findCurrentArticles",Map.of("ids",List.of())).endsWith("AND 1=0"));
        String sql=sql(config,"ArticleSearchMapper","findCurrentArticles",Map.of("ids",List.of(42L,43L)));
        assertTrue(sql.contains("status=1 AND deleted=0"));assertTrue(sql.contains("article_id IN"));
        assertFalse(sql.contains("42") || sql.contains("43"));
    }
    @Test void advisoryLocksBypassBothQueryCaches() throws Exception {
        var config=mapper("ArticleIndexLockMapper");
        for(var method:List.of("acquire","release")) {
            var statement=config.getMappedStatement("com.easyjob.mapper.ArticleIndexLockMapper."+method);
            assertFalse(statement.isUseCache());assertTrue(statement.isFlushCacheRequired());
        }
    }
}
