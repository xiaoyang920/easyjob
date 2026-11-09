package com.easyjob.config;
import org.junit.jupiter.api.*;
import org.springframework.web.socket.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.alibaba.fastjson2.JSONObject;
import java.util.ArrayList;
import org.springframework.web.socket.WebSocketSession;

class ChatMultiSessionTests {
    ChatWebSocketHandler handler=new ChatWebSocketHandler();List<WebSocketSession> sockets=new ArrayList<>();
    WebSocketSession socket(long uid,String sid)throws Exception{WebSocketSession s=mock(WebSocketSession.class);when(s.getAttributes()).thenReturn(Map.of("userId",uid,"authSessionId",sid));when(s.isOpen()).thenReturn(true);sockets.add(s);handler.afterConnectionEstablished(s);return s;}
    @AfterEach void close(){for(WebSocketSession s:sockets)handler.afterConnectionClosed(s,CloseStatus.NORMAL);ChatWebSocketHandler.relay=null;ChatWebSocketHandler.revokeRelay=null;ChatWebSocketHandler.presenceAudience=null;}
    @Test void allTabsReceiveAndClosingOneTabKeepsAnotherOnline()throws Exception{
        WebSocketSession a=socket(7,"device-a");WebSocketSession b=socket(7,"device-b");clearInvocations(a,b);
        ChatWebSocketHandler.sendToUser(7L,"message");verify(a).sendMessage(argThat(m->m.getPayload().equals("message")));verify(b).sendMessage(argThat(m->m.getPayload().equals("message")));
        handler.afterConnectionClosed(a,CloseStatus.NORMAL);assertTrue(ChatWebSocketHandler.isOnline(7L));clearInvocations(b);
        ChatWebSocketHandler.sendToUser(7L,"next");verify(b).sendMessage(argThat(m->m.getPayload().equals("next")));
    }
    @Test void revokingOneDeviceClosesOnlyMatchingSockets()throws Exception{
        WebSocketSession a=socket(7,"device-a");WebSocketSession b=socket(7,"device-b");WebSocketSession other=socket(8,"device-a");
        ChatWebSocketHandler.disconnectSession(7L,"device-a");verify(a).close(CloseStatus.POLICY_VIOLATION);verify(b,never()).close(any());verify(other,never()).close(any());
    }
    @Test void localDeliveryPublishesExactlyOneCrossNodeEnvelope()throws Exception{
        socket(7,"a");socket(7,"b");ArrayList<String> frames=new ArrayList<String>();ChatWebSocketHandler.relay=(uid,data)->frames.add(uid+":"+data);
        ChatWebSocketHandler.sendToUser(7L,"hello");assertEquals(List.of("7:hello"),frames);
    }
    @Test void presenceOnlyReachesAuthorizedContacts()throws Exception{
        ChatWebSocketHandler.presenceAudience=uid->uid==7?Set.of(8L):Set.of(7L);
        socket(8,"friend");socket(9,"stranger");WebSocketSession viewer=socket(7,"viewer");
        verify(viewer).sendMessage(argThat(m->{JSONObject data=com.alibaba.fastjson2.JSON.parseObject(m.getPayload().toString());return "online_users".equals(data.getString("type")) && data.getJSONArray("userIds").contains("8") && !data.getJSONArray("userIds").contains("9");}));
        clearInvocations(viewer);ChatWebSocketHandler.presenceLocal(9L,true);verify(viewer,never()).sendMessage(any());
        ChatWebSocketHandler.presenceLocal(8L,true);verify(viewer).sendMessage(argThat(m->m.getPayload().toString().contains("\"userId\":\"8\"")));
    }
}
