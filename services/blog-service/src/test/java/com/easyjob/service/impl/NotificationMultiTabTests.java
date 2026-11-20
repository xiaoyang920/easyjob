package com.easyjob.service.impl;

import com.easyjob.dto.NotificationMessage;
import org.junit.jupiter.api.Test;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.io.IOException;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class NotificationMultiTabTests {
    @Test void openingAnotherTabKeepsBothConnectionsAndFansOut() throws Exception {
        SseEmitterService service=spy(new SseEmitterService());SseEmitter first=mock(SseEmitter.class);SseEmitter second=mock(SseEmitter.class);
        doReturn(first,second).when(service).newEmitter();
        service.connect(7L);service.connect(7L);verify(first,never()).complete();clearInvocations(first,second);
        service.sendToUser(7L,new NotificationMessage());
        verify(first).send(any(SseEmitter.SseEventBuilder.class));verify(second).send(any(SseEmitter.SseEventBuilder.class));
        service.disconnect(7L);verify(first).complete();verify(second).complete();
    }
    @Test void closingOneTabCannotRemoveAnotherTabsConnection() throws Exception {
        SseEmitterService service=spy(new SseEmitterService());SseEmitter first=mock(SseEmitter.class);SseEmitter second=mock(SseEmitter.class);
        AtomicReference<Runnable> completion=new AtomicReference<Runnable>();doAnswer(call->{completion.set(call.getArgument(0));return null;}).when(first).onCompletion(any());
        doReturn(first,second).when(service).newEmitter();service.connect(7L);service.connect(7L);
        completion.get().run();clearInvocations(first,second);service.sendToUser(7L,new NotificationMessage());
        verify(first,never()).send(any(SseEmitter.SseEventBuilder.class));verify(second).send(any(SseEmitter.SseEventBuilder.class));
        service.shutdown();
    }
    @Test void oneBrokenEmitterDoesNotInterruptHealthyTabs() throws Exception {
        SseEmitterService service=spy(new SseEmitterService());SseEmitter first=mock(SseEmitter.class);SseEmitter second=mock(SseEmitter.class);
        doReturn(first,second).when(service).newEmitter();service.connect(7L);service.connect(7L);clearInvocations(first,second);
        doThrow(new IOException("closed tab")).when(first).send(any(SseEmitter.SseEventBuilder.class));
        assertDoesNotThrow(()->service.sendToUser(7L,new NotificationMessage()));
        verify(second).send(any(SseEmitter.SseEventBuilder.class));verify(first).completeWithError(any());service.shutdown();
    }
}
