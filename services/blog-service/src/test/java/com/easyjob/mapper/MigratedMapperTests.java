package com.easyjob.mapper;

import java.io.InputStream;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.ibatis.builder.xml.XMLMapperBuilder;
import org.apache.ibatis.io.Resources;
import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.mapping.SqlCommandType;
import org.apache.ibatis.session.Configuration;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class MigratedMapperTests {
    private Configuration configuration(Class<?> mapper) throws Exception {
        Configuration configuration = new Configuration();
        String resource = "mapper/" + mapper.getSimpleName() + ".xml";
        try (InputStream input = Resources.getResourceAsStream(resource)) {
            new XMLMapperBuilder(input, configuration, resource, configuration.getSqlFragments()).parse();
        }
        return configuration;
    }

    private MappedStatement statement(Configuration configuration, Class<?> mapper, String method) {
        return configuration.getMappedStatement(mapper.getName() + "." + method);
    }

    private String sql(Configuration configuration, Class<?> mapper, String method, Map<String, Object> params) {
        return statement(configuration, mapper, method).getBoundSql(params).getSql().replaceAll("\\s+", " ").trim();
    }

    @Test void allNewMapperMethodsHaveXmlStatementsAndReadsBypassCaches() throws Exception {
        for (Class<?> mapper : List.of(SocialMapper.class, GrowthMapper.class, ProviderBalanceMapper.class, AgentRunMapper.class)) {
            Configuration configuration = configuration(mapper);
            for (Method method : mapper.getDeclaredMethods()) {
                if (method.isDefault() || Modifier.isStatic(method.getModifiers())) continue;
                MappedStatement mapped = statement(configuration, mapper, method.getName());
                assertNotNull(mapped);
                if (mapped.getSqlCommandType() == SqlCommandType.SELECT) {
                    assertFalse(mapped.isUseCache(), mapped.getId());
                    assertTrue(mapped.isFlushCacheRequired(), mapped.getId());
                }
            }
        }
    }

    @Test void contactTypesAreWhitelistedAndSearchTextIsBound() throws Exception {
        Configuration configuration = configuration(SocialMapper.class);
        Map<String, Object> params = new HashMap<>(Map.of("me", 7L, "kind", "friends", "q", "%x' OR 1=1 --%", "size", 20, "offset", 0));
        String friends = sql(configuration, SocialMapper.class, "contacts", params);
        assertTrue(friends.contains("u.status=1"));
        assertTrue(friends.contains("NOT EXISTS"));
        assertTrue(friends.contains("LIKE ? ESCAPE '!'"));
        assertFalse(friends.contains("x' OR 1=1"));
        for (String kind : List.of("friends", "followers", "following", "blocked")) {
            params.put("kind", kind);
            assertFalse(sql(configuration, SocialMapper.class, "contacts", params).contains("AND 1=0"));
            assertTrue(sql(configuration, SocialMapper.class, "countContacts", params).startsWith("SELECT COUNT(*)"));
        }
        params.put("kind", "friends OR 1=1");
        assertTrue(sql(configuration, SocialMapper.class, "contacts", params).contains("AND 1=0"));
    }

    @Test void collectionsRemainBoundAndEmptyCollectionsDoNotExpandTheQuery() throws Exception {
        Configuration configuration = configuration(SocialMapper.class);
        Map<String, Object> params = new HashMap<>(Map.of("me", 7L, "ids", List.of(42L, 43L)));
        for (String method : List.of("findPeople", "publicArticles", "quotedMessages")) {
            String query = sql(configuration, SocialMapper.class, method, params);
            assertTrue(query.matches("(?s).*IN \\(\\s*\\?\\s*,\\s*\\?\\s*\\).*"), query);
            assertFalse(query.contains("42"));
            params.put("ids", List.of());
            assertTrue(sql(configuration, SocialMapper.class, method, params).contains("IN (NULL)"));
            params.put("ids", List.of(42L, 43L));
        }
    }

    @Test void orderLockAndPostWaitExpiryCheckRemainSeparateCurrentReads() throws Exception {
        Configuration configuration = configuration(GrowthMapper.class);
        Map<String, Object> params = Map.of("id", "order", "activity", "activity", "expires", new java.sql.Timestamp(0));
        for (String method : List.of("lockOrder", "lockOrderIdentity", "lockExpiredOrder"))
            assertTrue(sql(configuration, GrowthMapper.class, method, params).endsWith("FOR UPDATE"));
        assertTrue(sql(configuration, GrowthMapper.class, "expiredOrder", params).contains("expires_at<=NOW(3)"));
        assertTrue(sql(configuration, GrowthMapper.class, "reserveStock", params).contains("available_stock>0"));
        assertTrue(sql(configuration, GrowthMapper.class, "reserveStock", params).contains("state='ACTIVE'"));
    }

    @Test void monitorUpdatesKeepLeaseAndAlertFences() throws Exception {
        Configuration configuration = configuration(ProviderBalanceMapper.class);
        Map<String, Object> params = Map.of("key", "monitor", "token", "lease", "alertId", "alert");
        for (String method : List.of("lockLease", "extendLease", "markSent", "finishLease", "retryLease")) {
            String query = sql(configuration, ProviderBalanceMapper.class, method, params);
            assertTrue(query.contains("lease_token=?"), query);
            assertTrue(query.contains("lease_until>UTC_TIMESTAMP(6)"), query);
        }
        assertTrue(sql(configuration, ProviderBalanceMapper.class, "extendLease", params).contains("alert_sent_at IS NULL"));
    }

    @Test void executionLookupsBindOwnerAndExecutionTokenAndCredentialQueryLivesInXml() throws Exception {
        Configuration execution = configuration(AgentRunMapper.class);
        BoundSql query = statement(execution, AgentRunMapper.class, "findExecutingRun").getBoundSql(
            Map.of("runId", "run", "uid", 7L, "token", "execution"));
        assertTrue(query.getSql().contains("run_id=? AND user_id=? AND execution_token=?"));
        assertEquals(List.of("runId", "uid", "token"), query.getParameterMappings().stream().map(value -> value.getProperty()).toList());
        Configuration users = configuration(UserMapper.class);
        assertTrue(sql(users, UserMapper.class, "credentialById", Map.of("id", 7L)).contains("WHERE user_id=?"));
    }
}
