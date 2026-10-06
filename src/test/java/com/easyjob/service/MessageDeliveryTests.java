package com.easyjob.service;

import com.easyjob.config.ChatWebSocketHandler;
import com.easyjob.dto.MessageSendDTO;
import com.easyjob.entity.Message;
import com.easyjob.entity.User;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.MessageMapper;
import com.easyjob.mapper.ConversationMapper;
import com.easyjob.service.impl.MessageServiceImpl;
import com.easyjob.utils.UserContext;
import org.junit.jupiter.api.*;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.time.LocalDateTime;
import java.util.Map;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;

class MessageDeliveryTests {
    MessageMapper messages; ConversationMapper conversations; ConversationService conversationService;
    ConversationMemberService members; UserService users; MessageServiceImpl service;
    @BeforeEach void setup() {
        UserContext.setUserId(7L); TransactionSynchronizationManager.initSynchronization();
        service=new MessageServiceImpl(); messages=mock(MessageMapper.class); conversations=mock(ConversationMapper.class);
        conversationService=mock(ConversationService.class); members=mock(ConversationMemberService.class); users=mock(UserService.class);
        ReflectionTestUtils.setField(service,"messageMapper",messages); ReflectionTestUtils.setField(service,"conversationMapper",conversations);
        ReflectionTestUtils.setField(service,"conversationService",conversationService); ReflectionTestUtils.setField(service,"conversationMemberService",members);
        ReflectionTestUtils.setField(service,"userService",users);
        when(members.isMember(11L,7L)).thenReturn(true); when(members.getOneReceiveId(11L,7L)).thenReturn(8L);
        when(conversations.lockConversation(11L)).thenReturn(11L);
        User user=new User(); user.setNickName("real name"); user.setAvatar("/uploads/real.png"); when(users.getById(7L)).thenReturn(user);
        when(messages.insert(any(Message.class))).thenAnswer(call -> { ((Message)call.getArgument(0)).setMessageId(42L); return 1; });
    }
    @AfterEach void clean() { UserContext.clear(); TransactionSynchronizationManager.clear(); }
    MessageSendDTO request() {
        var dto=new MessageSendDTO(); dto.setConversationId(11L); dto.setMessageType(1); dto.setContent("hello");
        dto.setClientMessageId("test-id-1234567890"); dto.setSenderName("forged identity"); return dto;
    }
    @Test void pushWaitsForCommitAndUsesAuthoritativeSender() {
        try (var ws=mockStatic(ChatWebSocketHandler.class)) {
            var vo=service.sendMessage(request()); assertEquals("real name",vo.getSenderName());
            ws.verifyNoInteractions();
            TransactionSynchronizationManager.getSynchronizations().forEach(sync -> sync.afterCommit());
            ws.verify(() -> ChatWebSocketHandler.sendToUser(eq(8L), argThat((Map<String,Object> map) ->
                "real name".equals(map.get("senderName")) && "42".equals(map.get("messageId")))));
        }
    }
    @Test void rollbackDoesNotPushOrCreatePhantomClientMessage() {
        try (var ws=mockStatic(ChatWebSocketHandler.class)) {
            doThrow(new IllegalStateException("transaction failure")).when(members).incrementUnreadCount(11L,7L);
            assertThrows(IllegalStateException.class, () -> service.sendMessage(request()));
            assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty()); ws.verifyNoInteractions();
        }
    }
    @Test void retryDoesNotInsertIncrementUnreadOrPushAgain() {
        Message previous=new Message(); previous.setMessageId(42L); previous.setConversationId(11L); previous.setSenderId(7L);
        previous.setContent("hello"); previous.setMessageType(1); previous.setCreateTime(LocalDateTime.now());
        previous.setClientMessageId(request().getClientMessageId());
        when(messages.findClientMessage(7L,previous.getClientMessageId())).thenReturn(previous);
        assertEquals("42",service.sendMessage(request()).getMessageId());
        verify(messages,never()).insert(any(Message.class)); verifyNoInteractions(conversationService);
        verify(members,never()).incrementUnreadCount(anyLong(),anyLong());
        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());
        var changed=request(); changed.setContent("other");
        assertThrows(BusinessException.class, () -> service.sendMessage(changed));
    }
    @Test void catchUpRequiresMembership() {
        assertThrows(BusinessException.class, () -> service.getMessagesAfter(12L,0L,50));
        verify(messages,never()).selectMessagesAfter(anyLong(),anyLong(),anyInt());
    }
}
