package com.easyjob.service;

import com.easyjob.dto.NotificationMessage;
import com.easyjob.entity.Notification;
import com.easyjob.mapper.NotificationMapper;
import com.easyjob.service.impl.NotificationServiceImpl;
import org.junit.jupiter.api.*;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class NotificationTests {
    NotificationMapper mapper=mock(NotificationMapper.class);
    RabbitTemplate rabbit=mock(RabbitTemplate.class);
    NotificationServiceImpl service=new NotificationServiceImpl();
    @BeforeEach void setup(){
        ReflectionTestUtils.setField(service,"notificationMapper",mapper);
        ReflectionTestUtils.setField(service,"rabbitTemplate",rabbit);
        when(mapper.insert(any(Notification.class))).thenAnswer(call->{((Notification)call.getArgument(0)).setNotificationId(123L);return 1;});
    }
    @AfterEach void cleanup(){if(TransactionSynchronizationManager.isSynchronizationActive())TransactionSynchronizationManager.clearSynchronization();}
    NotificationMessage msg(int type,long sender){return NotificationMessage.builder().userId(7L).senderId(sender).type(type).content("审核结果").build();}
    @Test void reviewNotificationIsInsertedBeforeCommitButPushedOnlyAfterCommit(){
        TransactionSynchronizationManager.initSynchronization();var message=msg(6,9);
        service.send(message);verify(mapper).insert(any(Notification.class));verifyNoInteractions(rabbit);
        assertEquals(123L,message.getNotificationId());assertEquals(0,message.getIsRead());assertNotNull(message.getCreateTime());
        TransactionSynchronizationManager.getSynchronizations().forEach(s->s.afterCommit());
        verify(rabbit).convertAndSend(anyString(),eq("notification.push"),eq(message));
    }
    @Test void rollbackDoesNotPushAnUncommittedResult(){
        TransactionSynchronizationManager.initSynchronization();service.send(msg(7,9));
        TransactionSynchronizationManager.getSynchronizations().forEach(s->s.afterCompletion(1));
        verifyNoInteractions(rabbit);
    }
    @Test void adminReviewOfOwnArticleStillNotifiesButSelfLikesStaySilent(){
        service.send(msg(7,7));verify(mapper).insert(any(Notification.class));
        clearInvocations(mapper,rabbit);service.send(msg(2,7));verifyNoInteractions(mapper,rabbit);
    }
    @Test void brokerFailureDoesNotTurnCommittedReviewIntoAnApiFailure(){
        doThrow(new IllegalStateException("broker unavailable")).when(rabbit).convertAndSend(anyString(),anyString(),any(Object.class));
        TransactionSynchronizationManager.initSynchronization();service.send(msg(6,9));
        assertDoesNotThrow(()->TransactionSynchronizationManager.getSynchronizations().forEach(s->s.afterCommit()));
    }
    @Test void failedInboxInsertDoesNotRegisterDelivery(){
        when(mapper.insert(any(Notification.class))).thenReturn(0);
        TransactionSynchronizationManager.initSynchronization();
        assertThrows(IllegalStateException.class,()->service.send(msg(6,9)));
        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());verifyNoInteractions(rabbit);
    }
}
