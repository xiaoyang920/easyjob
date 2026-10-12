package com.easyjob.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.easyjob.agent.component.ArticleIndexOutbox;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.mapper.ArticleIndexOutboxMapper;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.UserActionMapper;
import com.easyjob.mapper.UserMapper;
import com.easyjob.service.impl.NotificationServiceImpl;
import com.easyjob.service.impl.UserActionServiceImpl;
import com.easyjob.utils.UserContext;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.*;
import java.util.regex.Pattern;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Opt-in real InnoDB tests. Creates/drops only its own random local test database. */
@EnabledIfEnvironmentVariable(named="EASYJOB_INTERACTION_DB_TEST", matches="1")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ArticleInteractionMysqlTests {
    String database;
    JdbcTemplate server, jdbc;
    UserActionService service;
    ArticleIndexPublisher publisher;
    static final long ARTICLE = 42L;

    @BeforeAll void initialize() throws Exception {
        String host = System.getenv().getOrDefault("MYSQL_HOST", "127.0.0.1");
        assertTrue(Set.of("127.0.0.1", "localhost", "::1").contains(host), "Only local/disposable MySQL is allowed");
        if (host.equals("::1")) host = "[::1]";
        String port = System.getenv().getOrDefault("MYSQL_PORT", "3306");
        assertTrue(port.matches("[0-9]{1,5}"));
        String base = "jdbc:mysql://" + host + ":" + port + "/";
        String options = "?serverTimezone=Asia/Shanghai&useSSL=false&allowPublicKeyRetrieval=true";
        String user = System.getenv().getOrDefault("MYSQL_USER", "root");
        String password = System.getenv().getOrDefault("MYSQL_PASSWORD", "");
        server = new JdbcTemplate(new DriverManagerDataSource(base + options, user, password));
        database = "easyjob_interaction_test_" + UUID.randomUUID().toString().replace("-", "");
        server.execute("CREATE DATABASE `" + database + "` CHARACTER SET utf8mb4");
        var datasource = new DriverManagerDataSource(base + database + options, user, password);
        jdbc = new JdbcTemplate(datasource);
        // Use the repository's actual table definitions, not H2 approximations of MySQL locking.
        String schema = Files.readString(Path.of("tests/integration/schema.sql"));
        var tables = Pattern.compile("(?ms)^CREATE TABLE `(article_info|user_action|article_index_outbox)` \\(.*?^\\) ENGINE=.*?;").matcher(schema);
        int count = 0;
        while (tables.find()) { jdbc.execute(tables.group()); count++; }
        assertEquals(3, count);

        var factory = new MybatisSqlSessionFactoryBean(); factory.setDataSource(datasource);
        var config = new MybatisConfiguration(); config.setMapUnderscoreToCamelCase(true);
        factory.setConfiguration(config);
        factory.setMapperLocations(new ClassPathResource("mapper/ArticleMapper.xml"),
                new ClassPathResource("mapper/ArticleIndexOutboxMapper.xml"));
        var sessions = factory.getObject(); assertNotNull(sessions);
        sessions.getConfiguration().addMapper(UserActionMapper.class);
        var sql = new SqlSessionTemplate(sessions);
        var manager = new DataSourceTransactionManager(datasource);
        publisher = spy(new ArticleIndexPublisher(new ArticleIndexOutbox(sql.getMapper(ArticleIndexOutboxMapper.class), manager)));
        var target = new UserActionServiceImpl();
        ReflectionTestUtils.setField(target, "articleMapper", sql.getMapper(ArticleMapper.class));
        ReflectionTestUtils.setField(target, "userActionMapper", sql.getMapper(UserActionMapper.class));
        ReflectionTestUtils.setField(target, "articleIndexPublisher", publisher);
        ReflectionTestUtils.setField(target, "notificationService", mock(NotificationServiceImpl.class));
        ReflectionTestUtils.setField(target, "userMapper", mock(UserMapper.class));
        var interceptor = new TransactionInterceptor(); interceptor.setTransactionManager(manager);
        interceptor.setTransactionAttributeSource(new AnnotationTransactionAttributeSource());
        var proxy = new ProxyFactory(target); proxy.addAdvice(interceptor);
        service = (UserActionService) proxy.getProxy();
    }

    @BeforeEach void resetFixtures() {
        reset(publisher);
        jdbc.execute("DELETE FROM user_action"); jdbc.execute("DELETE FROM article_index_outbox");
        jdbc.execute("DELETE FROM article_info");
        jdbc.update("INSERT INTO article_info(article_id,user_id,title,status,deleted,like_count,collect_count,create_time,update_time,publish_time) VALUES (42,7,'isolated interaction test',1,0,0,0,NOW(),NOW(),NOW())");
    }

    @AfterEach void clearContext() { UserContext.clear(); }

    @AfterAll void cleanup() {
        // Never accept an externally supplied database name for cleanup.
        if (server != null && database != null && database.matches("easyjob_interaction_test_[a-f0-9]{32}"))
            server.execute("DROP DATABASE IF EXISTS `" + database + "`");
    }

    List<UserActionService.InteractionResult> concurrent(boolean like, boolean active, boolean sameUser) throws Exception {
        try (var executor = Executors.newFixedThreadPool(8)) {
            var start = new CountDownLatch(1);
            var jobs = new ArrayList<Future<UserActionService.InteractionResult>>();
            for (int i = 0; i < 24; i++) {
                final long uid = sameUser ? 9L : 100L + i;
                jobs.add(executor.submit(() -> {
                    start.await(); UserContext.setUserId(uid);
                    try { return like ? service.like(ARTICLE, active) : service.collect(ARTICLE, active); }
                    finally { UserContext.clear(); }
                }));
            }
            start.countDown();
            var results = new ArrayList<UserActionService.InteractionResult>();
            for (var job : jobs) results.add(job.get(20, TimeUnit.SECONDS));
            return results;
        }
    }

    long scalar(String sql) { return jdbc.queryForObject(sql, Long.class); }

    @Test void twentyFourRetriesFromOneUserCreateExactlyOneLikeAndOutbox() throws Exception {
        var results = concurrent(true, true, true);
        assertTrue(results.stream().allMatch(r -> r.active() && r.count()==1));
        assertEquals(1, scalar("SELECT like_count FROM article_info WHERE article_id=42"));
        assertEquals(1, scalar("SELECT COUNT(*) FROM user_action WHERE article_id=42 AND comment_id=0 AND action_type=2"));
        assertEquals(1, scalar("SELECT COUNT(*) FROM article_index_outbox WHERE article_id=42 AND action='COUNTS'"));
    }

    @Test void concurrentDifferentUsersAndCancellationsKeepCountersEqualToRelationships() throws Exception {
        for (boolean like : new boolean[]{true, false}) {
            concurrent(like, true, false);
            String field = like ? "like_count" : "collect_count";
            int type = like ? 2 : 3;
            assertEquals(24, scalar("SELECT " + field + " FROM article_info WHERE article_id=42"));
            assertEquals(24, scalar("SELECT COUNT(*) FROM user_action WHERE article_id=42 AND action_type=" + type));
            concurrent(like, false, false);
            assertEquals(0, scalar("SELECT " + field + " FROM article_info WHERE article_id=42"));
            assertEquals(0, scalar("SELECT COUNT(*) FROM user_action WHERE article_id=42 AND action_type=" + type));
        }
        assertEquals(96, scalar("SELECT COUNT(*) FROM article_index_outbox"));
    }

    @Test void failureAfterOutboxInsertRollsBackRelationshipCounterAndDeliveryForBothActions() {
        doAnswer(call -> { call.callRealMethod(); throw new IllegalStateException("simulated transaction failure"); })
                .when(publisher).publish(anyLong(), anyString(), anyString());
        UserContext.setUserId(9L);
        assertThrows(IllegalStateException.class, () -> service.like(ARTICLE, true));
        assertThrows(IllegalStateException.class, () -> service.collect(ARTICLE, true));
        assertEquals(0, scalar("SELECT like_count+collect_count FROM article_info WHERE article_id=42"));
        assertEquals(0, scalar("SELECT COUNT(*) FROM user_action"));
        assertEquals(0, scalar("SELECT COUNT(*) FROM article_index_outbox"));
    }

    @Test void repeatedCancellationCannotReduceZeroOrQueueWork() throws Exception {
        concurrent(true, false, true); concurrent(false, false, true);
        assertEquals(0, scalar("SELECT like_count+collect_count FROM article_info WHERE article_id=42"));
        assertEquals(0, scalar("SELECT COUNT(*) FROM user_action"));
        assertEquals(0, scalar("SELECT COUNT(*) FROM article_index_outbox"));
    }
}
