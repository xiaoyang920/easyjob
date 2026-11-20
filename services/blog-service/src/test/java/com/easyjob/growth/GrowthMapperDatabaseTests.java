package com.easyjob.growth;

import com.easyjob.mapper.GrowthMapper;
import com.easyjob.mapper.MapperTestSupport;
import com.easyjob.mapper.ReadingGrowthMapper;
import com.easyjob.service.AdminConsoleService;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;

/** Real MySQL, only the disposable schema created by the mapper verification harness. */
@EnabledIfEnvironmentVariable(named="MAPPER_TEST_JDBC_URL", matches=".+/easyjob_mapper_test_[a-f0-9]+.*")
class GrowthMapperDatabaseTests {
    private JdbcTemplate jdbc;
    private GrowthMapper mapper;
    private GrowthService service;
    private DataSourceTransactionManager manager;
    private String activity;
    private String order;

    @BeforeEach void setup() {
        DriverManagerDataSource dataSource = new DriverManagerDataSource(System.getenv("MAPPER_TEST_JDBC_URL"),
            System.getenv("MAPPER_TEST_USER"), System.getenv("MAPPER_TEST_PASSWORD"));
        jdbc = new JdbcTemplate(dataSource);
        for (String table : List.of("growth_outbox", "coin_ledger", "growth_ledger", "growth_order", "growth_activity",
                "user_reading_daily", "user_reading_progress", "user_info")) jdbc.update("DELETE FROM " + table);
        for (long uid : new long[]{7L, 8L}) jdbc.update("""
            INSERT INTO user_info(user_id,email,nick_name,password,status,role,join_time,current_coin_count,total_coin_count,
                sex,theme,article_count,follower_count,following_count,data_source)
            VALUES(?,?,?,'offline-no-login',1,1,NOW(),100,100,2,1,0,0,0,'evaluation')
            """, uid, "mapper-" + uid + "@example.invalid", "fixture-" + uid);
        manager = new DataSourceTransactionManager(dataSource);
        mapper = MapperTestSupport.mapper(dataSource, GrowthMapper.class);
        ReadingGrowthMapper reading = MapperTestSupport.mapper(dataSource, ReadingGrowthMapper.class);
        service = new GrowthService(mapper, mock(GrowthReservations.class), reading, mock(AdminConsoleService.class), manager);
        activity = UUID.randomUUID().toString();
        order = UUID.randomUUID().toString();
        mapper.createActivity(activity, "mapper fixture", 1, 1, Timestamp.from(Instant.now().minusSeconds(10)),
            Timestamp.from(Instant.now().plusSeconds(3600)), 120, 7L);
        mapper.activateDraft(activity);
        mapper.createOrder(order, activity, 7L, UUID.randomUUID().toString(), 10, 1800, Timestamp.from(Instant.now().plusSeconds(120)));
        assertEquals(1, mapper.reserveStock(activity, Timestamp.from(Instant.now().plusSeconds(120))));
    }

    @Test void concurrentPaymentDebitsAndCreditsExactlyOnce() throws Exception {
        try (ExecutorService workers = Executors.newFixedThreadPool(2)) {
            CountDownLatch gate = new CountDownLatch(1);
            Future<Map<String,Object>> first = workers.submit(() -> { gate.await(); return service.pay(7L, order); });
            Future<Map<String,Object>> second = workers.submit(() -> { gate.await(); return service.pay(7L, order); });
            gate.countDown();
            assertEquals("PAID", first.get(20, TimeUnit.SECONDS).get("state"));
            assertEquals("PAID", second.get(20, TimeUnit.SECONDS).get("state"));
        }
        assertEquals(90L, jdbc.queryForObject("SELECT current_coin_count FROM user_info WHERE user_id=7", Long.class));
        assertEquals(1L, jdbc.queryForObject("SELECT COUNT(*) FROM coin_ledger", Long.class));
        assertEquals(1L, jdbc.queryForObject("SELECT COUNT(*) FROM growth_ledger", Long.class));
        assertEquals(1800000L, jdbc.queryForObject("SELECT purchased_millis FROM user_reading_progress WHERE user_id=7", Long.class));
        assertEquals(0L, jdbc.queryForObject("SELECT COUNT(*) FROM user_reading_daily", Long.class));
    }

    @Test void ledgerFailureRollsBackTheRealCoinDebitAndOrderTransaction() {
        jdbc.update("INSERT INTO coin_ledger(user_id,order_id,business_type,delta) VALUES(7,?,'GROWTH_BUY',-10)", order);
        assertThrows(DataIntegrityViolationException.class, () -> service.pay(7L, order));
        assertEquals(100L, jdbc.queryForObject("SELECT current_coin_count FROM user_info WHERE user_id=7", Long.class));
        assertEquals("PENDING", mapper.order(order).get("state"));
        assertEquals(0L, jdbc.queryForObject("SELECT COUNT(*) FROM growth_ledger", Long.class));
    }

    @Test void conditionalStockDecrementCannotOversell() throws Exception {
        String id = UUID.randomUUID().toString();
        mapper.createActivity(id, "stock fixture", 3, 3, Timestamp.from(Instant.now().minusSeconds(10)),
            Timestamp.from(Instant.now().plusSeconds(3600)), 120, 7L);
        mapper.activateDraft(id);
        try (ExecutorService workers = Executors.newFixedThreadPool(6)) {
            List<java.util.concurrent.Callable<Integer>> calls = java.util.stream.IntStream.range(0, 20)
                .mapToObj(index -> (java.util.concurrent.Callable<Integer>) () ->
                    mapper.reserveStock(id, Timestamp.from(Instant.now().plusSeconds(120)))).toList();
            int accepted = 0;
            for (Future<Integer> result : workers.invokeAll(calls)) accepted += result.get(10, TimeUnit.SECONDS);
            assertEquals(3, accepted);
        }
        assertEquals(0L, GrowthValues.number(mapper.activity(id), "available_stock"));
    }

    @Test void lockingIdentityReadSeesCommitBeyondTheEarlierRepeatableReadSnapshot() throws Exception {
        TransactionTemplate transaction = new TransactionTemplate(manager);
        transaction.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        String lateOrder = UUID.randomUUID().toString();
        try (ExecutorService worker = Executors.newSingleThreadExecutor()) {
            transaction.executeWithoutResult(status -> {
                assertNotNull(mapper.activity(activity));
                try {
                    assertEquals(1, worker.submit(() -> mapper.createOrder(lateOrder, activity, 8L,
                        UUID.randomUUID().toString(), 10, 1800, Timestamp.from(Instant.now().plusSeconds(120))))
                        .get(10, TimeUnit.SECONDS));
                } catch (Exception failure) { throw new IllegalStateException(failure); }
                assertNull(mapper.order(lateOrder));
                assertEquals(lateOrder, mapper.lockOrderIdentity(lateOrder).get("order_id"));
            });
        }
    }
}
