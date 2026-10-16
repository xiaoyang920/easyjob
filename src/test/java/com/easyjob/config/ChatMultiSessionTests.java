package com.easyjob.config;
import org.junit.jupiter.api.*;
import org.springframework.web.socket.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ChatMultiSessionTests {
    ChatWebSocketHandler handler=new ChatWebSocketHandler();List<WebSocketSession> sockets=new ArrayList<>();
    WebSocketSession socket(long uid,String sid)throws Exception{var s=mock(WebSocketSession.class);when(s.getAttributes()).thenReturn(Map.of("userId",uid,"authSessionId",sid));when(s.isOpen()).thenReturn(true);sockets.add(s);handler.afterConnectionEstablished(s);return s;}
    @AfterEach void close(){for(var s:sockets)handler.afterConnectionClosed(s,CloseStatus.NORMAL);ChatWebSocketHandler.relay=null;ChatWebSocketHandler.revokeRelay=null;}
    @Test void allTabsReceiveAndClosingOneTabKeepsAnotherOnline()throws Exception{
        var a=socket(7,"device-a");var b=socket(7,"device-b");clearInvocations(a,b);
        ChatWebSocketHandler.sendToUser(7L,"message");verify(a).sendMessage(argThat(m->m.getPayload().equals("message")));verify(b).sendMessage(argThat(m->m.getPayload().equals("message")));
        handler.afterConnectionClosed(a,CloseStatus.NORMAL);assertTrue(ChatWebSocketHandler.isOnline(7L));clearInvocations(b);
        ChatWebSocketHandler.sendToUser(7L,"next");verify(b).sendMessage(argThat(m->m.getPayload().equals("next")));
    }
    @Test void revokingOneDeviceClosesOnlyMatchingSockets()throws Exception{
        var a=socket(7,"device-a");var b=socket(7,"device-b");var other=socket(8,"device-a");
        ChatWebSocketHandler.disconnectSession(7L,"device-a");verify(a).close(CloseStatus.POLICY_VIOLATION);verify(b,never()).close(any());verify(other,never()).close(any());
    }
    @Test void localDeliveryPublishesExactlyOneCrossNodeEnvelope()throws Exception{
        socket(7,"a");socket(7,"b");var frames=new ArrayList<String>();ChatWebSocketHandler.relay=(uid,data)->frames.add(uid+":"+data);
        ChatWebSocketHandler.sendToUser(7L,"hello");assertEquals(List.of("7:hello"),frames);
    }
}
