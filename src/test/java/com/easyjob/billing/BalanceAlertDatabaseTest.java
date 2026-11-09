package com.easyjob.billing;
import com.easyjob.mapper.ProviderBalanceMapper;
import com.easyjob.mapper.MapperTestSupport;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.math.BigDecimal;
import java.util.UUID;
import java.util.concurrent.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.easyjob.billing.ProviderBalanceStore.Lease;
import com.easyjob.billing.ProviderBalanceStore.Notice;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/** Opt-in real MySQL tests, isolated rows and mocked provider/SMTP (never send email). */
@EnabledIfEnvironmentVariable(named="BALANCE_ALERT_DB_TEST",matches="true")
class BalanceAlertDatabaseTest {
    JdbcTemplate sql; ProviderBalanceMapper mapper; ProviderBalanceStore store; BalanceAlertPolicy policy;
    DeepseekBalanceClient provider; DeepseekBalanceMail mail; DeepseekBalanceMonitor monitor;
    @BeforeEach void setup() {
        DriverManagerDataSource ds=new DriverManagerDataSource(System.getenv("BALANCE_ALERT_DB_URL"),System.getenv("BALANCE_ALERT_DB_USER"),System.getenv("BALANCE_ALERT_DB_PASSWORD"));
        sql=new JdbcTemplate(ds); mapper=MapperTestSupport.mapper(ds,ProviderBalanceMapper.class); store=new ProviderBalanceStore(mapper,new DataSourceTransactionManager(ds));
        policy=new BalanceAlertPolicy("balance-test-"+UUID.randomUUID().toString().replace("-",""),"CNY",new BigDecimal("2.00"),"qa@example.invalid",600);
        provider=mock(DeepseekBalanceClient.class); when(provider.fingerprint()).thenReturn("a".repeat(64));
        mail=mock(DeepseekBalanceMail.class); monitor=new DeepseekBalanceMonitor(store,policy,provider,mail); store.checkSchema();
    }
    @AfterEach void cleanup() { if(sql!=null&&policy!=null) sql.update("DELETE FROM provider_balance_monitor WHERE monitor_key=?",policy.key()); }
    void due() { sql.update("UPDATE provider_balance_monitor SET next_check_at=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)) WHERE monitor_key=?",policy.key()); }
    void balance(String amount) { when(provider.fetch("CNY")).thenReturn(new DeepseekBalanceClient.Balance(new BigDecimal(amount),true)); }
    Object field(String column) { return sql.queryForMap("SELECT * FROM provider_balance_monitor WHERE monitor_key=?",policy.key()).get(column); }
    @Test void deduplicatesAcrossWorkersAndRearmsAfterRecovery() {
        balance("2.00"); assertTrue(monitor.tick()); verifyNoInteractions(mail); assertFalse(monitor.tick());
        due(); balance("1.99"); monitor.tick(); verify(mail,times(1)).send(any()); String first=field("alert_id").toString(); assertNotNull(field("alert_sent_at"));
        due(); balance("1.5"); new DeepseekBalanceMonitor(new ProviderBalanceStore(mapper,new DataSourceTransactionManager(sql.getDataSource())),policy,provider,mail).tick();
        verify(mail,times(1)).send(any()); assertEquals(first,field("alert_id"));
        due(); balance("3"); monitor.tick(); assertEquals("normal",field("alert_state")); assertNull(field("alert_id"));
        due(); balance("1"); monitor.tick(); verify(mail,times(2)).send(any()); assertNotEquals(first,field("alert_id"));
    }
    @Test void failedQueryPreservesLastKnownBalanceAndNeverEmails() {
        balance("4.79"); monitor.tick(); due(); when(provider.fetch("CNY")).thenThrow(new DeepseekBalanceClient.CheckFailed("provider_http_401"));
        monitor.tick(); verifyNoInteractions(mail); assertEquals(0,new BigDecimal("4.79").compareTo((BigDecimal)field("balance_amount")));
        assertEquals("normal",field("alert_state")); assertEquals("provider_http_401",field("last_error_code")); assertFalse(monitor.tick());
    }
    @Test void failedEmailKeepsPendingEpisodeThenRetries() {
        balance("1.00"); doThrow(new RuntimeException("mock SMTP failure")).doNothing().when(mail).send(any());
        monitor.tick(); Object id=field("alert_id"); assertNotNull(id); assertNull(field("alert_sent_at")); assertFalse(monitor.tick());
        due(); monitor.tick(); assertEquals(id,field("alert_id")); assertNotNull(field("alert_sent_at"));
        due(); monitor.tick(); verify(mail,times(2)).send(any());
    }
    @Test void recoveryCancelsPendingEmail() {
        balance("1"); doThrow(new RuntimeException("mock SMTP failure")).when(mail).send(any()); monitor.tick();
        due(); balance("3"); monitor.tick(); assertNull(field("alert_id")); assertEquals("normal",field("alert_state")); verify(mail,times(1)).send(any());
    }
    @Test void concurrentClaimsAndExpiredWorkerAreFenced() throws Exception {
        try(ExecutorService pool=Executors.newFixedThreadPool(2)) {
            CountDownLatch gate=new CountDownLatch(1);
            Callable<ProviderBalanceStore.Lease> claim=()->{gate.await();return store.claim(policy,"a".repeat(64));};
            Future<Lease> a=pool.submit(claim);Future<Lease> b=pool.submit(claim);gate.countDown();
            Lease first=a.get(10,TimeUnit.SECONDS);Lease second=b.get(10,TimeUnit.SECONDS);
            assertTrue((first==null) != (second==null));Lease old=first==null?second:first;
            sql.update("UPDATE provider_balance_monitor SET lease_until=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)) WHERE monitor_key=?",policy.key());
            Lease replacement=store.claim(policy,"a".repeat(64));assertNotNull(replacement);
            assertThrows(ProviderBalanceStore.LeaseLost.class,()->store.record(old,policy,new DeepseekBalanceClient.Balance(BigDecimal.ONE,true)));
            Notice notice=store.record(replacement,policy,new DeepseekBalanceClient.Balance(BigDecimal.ONE,true));
            assertThrows(ProviderBalanceStore.LeaseLost.class,()->store.beforeSend(old,notice));
            assertThrows(ProviderBalanceStore.LeaseLost.class,()->store.sent(old,notice));
            store.beforeSend(replacement,notice);store.sent(replacement,notice);store.finish(replacement,600);
        }
    }
}
