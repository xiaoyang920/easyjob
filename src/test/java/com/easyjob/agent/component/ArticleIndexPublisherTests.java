package com.easyjob.agent.component;

import com.easyjob.constants.RabbitMqConstants;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.annotation.Transactional;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ArticleIndexPublisherTests {
    @Test void publishingRecordsDurableIntentInTheBusinessTransaction() throws Exception {
        var outbox = mock(ArticleIndexOutbox.class);
        new ArticleIndexPublisher(outbox).publish(42L, "UPDATE", RabbitMqConstants.ROUTING_KEY_UPDATE);
        verify(outbox).enqueue(42L, "UPDATE", RabbitMqConstants.ROUTING_KEY_UPDATE);
        assertNotNull(ArticleIndexPublisher.class.getMethod("publish", Long.class, String.class, String.class).getAnnotation(Transactional.class));
    }
    @Test void anOutboxWriteFailurePropagatesForBusinessRollback() {
        var outbox = mock(ArticleIndexOutbox.class);
        doThrow(new IllegalStateException("DB unavailable")).when(outbox).enqueue(anyLong(), anyString(), anyString());
        assertThrows(IllegalStateException.class, () -> new ArticleIndexPublisher(outbox).publish(42L, "DELETE", RabbitMqConstants.ROUTING_KEY_DELETE));
    }
}
