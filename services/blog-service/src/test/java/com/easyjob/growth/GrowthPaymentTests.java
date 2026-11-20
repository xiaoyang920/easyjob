package com.easyjob.growth;
import com.easyjob.mapper.GrowthMapper;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ReadingGrowthMapper;
import com.easyjob.service.AdminConsoleService;
import org.junit.jupiter.api.*;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;
import static org.junit.jupiter.api.Assertions.*;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

class GrowthPaymentTests {
    GrowthMapper store;ReadingGrowthMapper reading;PlatformTransactionManager manager;TransactionStatus status;GrowthService service;
    @BeforeEach void setup(){store=mock(GrowthMapper.class);reading=mock(ReadingGrowthMapper.class);manager=mock(PlatformTransactionManager.class);status=mock(TransactionStatus.class);when(manager.getTransaction(any())).thenReturn(status);service=new GrowthService(store,mock(GrowthReservations.class),reading,mock(AdminConsoleService.class),manager);}
    Map<String,Object> order(String state){HashMap<String, Object> o=new HashMap<String,Object>();o.putAll(Map.of("order_id","o","activity_id","a","user_id",7L,"state",state,"expired",0,"coin_cost",10,"growth_seconds",1800,"expires_at",Timestamp.from(Instant.now().plusSeconds(120)),"reason",""));return o;}
    void locked(Map<String,Object> order){when(store.lockOrder("o")).thenReturn(order);}
    @Test void paidRetryDoesNotDebitOrCredit(){locked(order("PAID"));assertEquals("PAID",service.pay(7L,"o").get("state"));verify(store,never()).debitCoins(any(),anyLong(),any());verifyNoInteractions(reading);verify(manager).commit(status);}
    @Test void jdbcDatetimeAndTimestampHaveSameInstant(){LocalDateTime local=java.time.LocalDateTime.of(2026,10,28,16,0);Instant instant=java.time.Instant.parse("2026-10-28T08:00:00Z");assertEquals(instant,GrowthValues.instant(local));assertEquals(instant,GrowthValues.instant(Timestamp.from(instant)));}
    @Test void otherUserCannotPay(){locked(order("PENDING"));assertThrows(BusinessException.class,()->service.pay(8L,"o"));verify(manager).rollback(status);verifyNoInteractions(reading);}
    @Test void insufficientFundsRollBackAndLeavePending(){locked(order("PENDING"));when(store.debitCoins(any(),anyLong(),any())).thenReturn(0);assertThrows(BusinessException.class,()->service.pay(7L,"o"));verifyNoInteractions(reading);verify(manager).rollback(status);}
    @Test void ledgerFailureRollsBackDebit(){locked(order("PENDING"));when(store.debitCoins(any(),anyLong(),any())).thenReturn(1);when(store.recordCoinPurchase(anyLong(),anyString(),anyLong())).thenThrow(new IllegalStateException("fixture"));assertThrows(IllegalStateException.class,()->service.pay(7L,"o"));verifyNoInteractions(reading);verify(manager).rollback(status);}
    @Test void expiryClosesWithoutCharging(){Map<String, Object> o=order("PENDING");o.put("expired",0);locked(o);when(store.expiredOrder("o")).thenReturn(1L);when(store.order("o")).thenReturn(order("CLOSED"));assertEquals("CLOSED",service.pay(7L,"o").get("state"));verify(store).releaseEvent("a","o");verifyNoInteractions(reading);verify(manager).commit(status);}
    @Test void purchaseCombinesGrowthButDoesNotCreditReadingDay(){locked(order("PENDING"));when(store.debitCoins(any(),anyLong(),any())).thenReturn(1);when(reading.lockProgress(7L)).thenReturn(Map.of("total_millis",1800000L,"purchased_millis",0L,"earned_level",0));when(reading.findRules()).thenReturn(List.of(Map.of("level",1,"minSeconds",3600L)));when(store.order("o")).thenReturn(order("PAID"));assertEquals("PAID",service.pay(7L,"o").get("state"));verify(store).creditGrowth(1800000L,1,7L);verify(reading,never()).creditDay(any(),any(),anyLong(),anyLong());verify(manager).commit(status);}
}
