package com.easyjob.agent.component;

import com.easyjob.dto.ArticleVectorMessage;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.core.ReturnedMessage;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ArticleIndexRelayTests {
    private final ArticleIndexOutbox.Job job = new ArticleIndexOutbox.Job("job-id", 42L, "UPDATE", "article.update", 1, "lease-token");

    @Test void acceptedMessageWaitsForConsumerCompletion() {
        var outbox = mock(ArticleIndexOutbox.class); var rabbit = mock(RabbitTemplate.class);
        when(outbox.claim()).thenReturn(job);
        doAnswer(call -> {
            ArticleVectorMessage message = call.getArgument(2);
            assertEquals(job.id(), message.getIndexJobId());
            ((CorrelationData) call.getArgument(3)).getFuture().complete(new CorrelationData.Confirm(true, null));
            return null;
        }).when(rabbit).convertAndSend(anyString(), anyString(), any(ArticleVectorMessage.class), any(CorrelationData.class));
        assertTrue(new ArticleIndexRelay(outbox, rabbit).relayOnce());
        verify(outbox).dispatched(job);
        verify(outbox, never()).complete(anyString(), anyLong());
    }

    @Test void rejectedOrUnroutedMessageIsRetried() {
        for (boolean returned : new boolean[]{false, true}) {
            var outbox = mock(ArticleIndexOutbox.class); var rabbit = mock(RabbitTemplate.class);
            when(outbox.claim()).thenReturn(job);
            doAnswer(call -> {
                CorrelationData data = call.getArgument(3);
                if (returned) data.setReturned(new ReturnedMessage(new Message(new byte[0], new MessageProperties()), 312, "NO_ROUTE", "exchange", "key"));
                data.getFuture().complete(new CorrelationData.Confirm(returned, "rejected"));
                return null;
            }).when(rabbit).convertAndSend(anyString(), anyString(), any(ArticleVectorMessage.class), any(CorrelationData.class));
            new ArticleIndexRelay(outbox, rabbit).relayOnce();
            verify(outbox).retry(eq(job), any(Exception.class));
            verify(outbox, never()).dispatched(any());
        }
    }

    @Test void connectionFailureLeavesRecoverableIntent() {
        var outbox = mock(ArticleIndexOutbox.class); var rabbit = mock(RabbitTemplate.class);
        when(outbox.claim()).thenReturn(job);
        doThrow(new IllegalStateException("offline")).when(rabbit).convertAndSend(anyString(), anyString(), any(ArticleVectorMessage.class), any(CorrelationData.class));
        new ArticleIndexRelay(outbox, rabbit).relayOnce();
        verify(outbox).retry(eq(job), any(Exception.class));
        verify(outbox, never()).dispatched(any());
    }
}
