package com.easyjob.growth;
import com.easyjob.mapper.GrowthMapper;
import com.easyjob.mapper.ReadingGrowthMapper;
import com.easyjob.service.AdminConsoleService;
import org.junit.jupiter.api.*;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

class GrowthMaterializeTests {
    GrowthMapper store;GrowthReservations reservations;GrowthService service;
    final String aid=UUID.randomUUID().toString(),rid=UUID.randomUUID().toString(),request=UUID.randomUUID().toString();
    final long deadline=System.currentTimeMillis()+120000;
    @BeforeEach void setup(){
        store=mock(GrowthMapper.class);reservations=mock(GrowthReservations.class);
        PlatformTransactionManager manager=mock(PlatformTransactionManager.class);when(manager.getTransaction(any())).thenReturn(mock(TransactionStatus.class));
        service=new GrowthService(store,reservations,mock(ReadingGrowthMapper.class),mock(AdminConsoleService.class),manager);
        when(store.order(rid)).thenReturn(null);
        when(store.lockOrderIdentity(rid)).thenReturn(null);
        when(store.activity(aid)).thenReturn(Map.of("coin_price",10,"growth_seconds",1800));
        when(reservations.reservation(aid,rid)).thenReturn(Map.of("userId","7","requestId",request,"expiresAt",deadline));
    }
    @Test void duplicateConsumerUsesCurrentReadAndDoesNotReleaseCommittedReservation(){
        when(store.lockOrderIdentity(rid)).thenReturn(Map.of("order_id",rid));
        service.materialize(new GrowthService.Reservation(aid,rid,"7",request,deadline));
        verify(store).lockOrderIdentity(rid);
        verify(store,never()).releaseEvent(anyString(),anyString());
    }
    @Test void differentReservationForExistingBuyerIsReleased(){
        service.materialize(new GrowthService.Reservation(aid,rid,"7",request,deadline));
        verify(store).releaseEvent(aid,rid);
    }
}
