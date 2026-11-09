package com.easyjob.growth;

import com.easyjob.observability.TraceSupport;
import com.easyjob.mapper.GrowthMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rabbitmq.client.Channel;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.context.Scope;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.Limit;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import java.util.*;
import java.util.concurrent.TimeUnit;
import static com.easyjob.growth.GrowthMessaging.*;

@Component
public class GrowthWorkers {
    private static final Logger log = LoggerFactory.getLogger(GrowthWorkers.class);
    final GrowthMapper store;
    final GrowthReservations reservations;
    final GrowthService service;
    final RabbitTemplate rabbit;
    final ObjectMapper json;

    public GrowthWorkers(GrowthMapper store, GrowthReservations reservations,
                         GrowthService service, RabbitTemplate rabbit, ObjectMapper json) {
        this.store = store; this.reservations = reservations;
        this.service = service; this.rabbit = rabbit; this.json = json;
        rabbit.setMandatory(true);
    }

    private Map<String, String> headers(Message message) {
        Map<String, String> carrier = new HashMap<>();
        for (String key : List.of("traceparent", "tracestate")) {
            Object value = message.getMessageProperties().getHeaders().get(key);
            if (value instanceof String text) carrier.put(key, text);
        }
        return carrier;
    }

    private void waitTime(Span span, Object timestamp) {
        try {
            if (timestamp == null) return;
            long elapsed = System.currentTimeMillis() - Long.parseLong(timestamp.toString());
            span.setAttribute("easyjob.queue.wait_ms", Math.max(0, elapsed));
        } catch (NumberFormatException ignored) {
            // Trace metadata must not change message processing.
        }
    }

    void publish(String routing, Object body, long delay) throws Exception {
        Span span = TraceSupport.start("growth.mq.publish", SpanKind.PRODUCER);
        try (Scope scope = span.makeCurrent()) {
            span.setAttribute("messaging.system", "rabbitmq");
            span.setAttribute("messaging.destination.name", routing);
            Map<String, String> carrier = TraceSupport.inject();
            CorrelationData confirm = new CorrelationData(UUID.randomUUID().toString());
            rabbit.convertAndSend(EXCHANGE, routing, body, message -> {
                MessageProperties properties = message.getMessageProperties();
                properties.setDeliveryMode(org.springframework.amqp.core.MessageDeliveryMode.PERSISTENT);
                carrier.forEach(properties::setHeader);
                properties.setHeader("easyjob.enqueued_ms", System.currentTimeMillis());
                if (delay > 0) properties.setExpiration(Long.toString(delay));
                return message;
            }, confirm);
            if (!confirm.getFuture().get(3, TimeUnit.SECONDS).isAck() || confirm.getReturned() != null)
                throw new IllegalStateException("Growth message not confirmed/routed");
        } catch (Exception error) {
            TraceSupport.failure(span, error); throw error;
        } finally { span.end(); }
    }

    @Scheduled(fixedDelay = 200, scheduler = "growthScheduler")
    public void forward() {
        try {
            for (Map<String, Object> activity : store.relayActivities()) {
                String key = reservations.key(activity.get("activity_id").toString(), "events");
                List<MapRecord<String, Object, Object>> records = reservations.redis.opsForStream()
                    .range(key, Range.unbounded(), Limit.limit().count(50));
                if (records == null) continue;
                for (MapRecord<String, Object, Object> record : records) {
                    Map<Object, Object> values = record.getValue();
                    Map<String, String> carrier = Map.of("traceparent", Objects.toString(values.get("traceparent"), ""),
                                         "tracestate", Objects.toString(values.get("tracestate"), ""));
                    Span span = TraceSupport.receive("growth.stream.forward", SpanKind.CONSUMER, carrier);
                    try (Scope scope = span.makeCurrent()) {
                        span.setAttribute("messaging.system", "redis");
                        span.setAttribute("messaging.destination.name", "growth.events");
                        waitTime(span, values.get("enqueued_at"));
                        GrowthService.Reservation event = json.readValue(values.get("body").toString(), GrowthService.Reservation.class);
                        span.setAttribute("easyjob.order.id", event.reservationId());
                        publish(ORDERS, event, 0);
                        // Delete only after broker confirmation. Duplicate relays remain possible.
                        reservations.redis.opsForStream().delete(key, record.getId());
                    } catch (Exception error) {
                        TraceSupport.failure(span, error); throw error;
                    } finally { span.end(); }
                }
            }
        } catch (Exception error) {
            if (error instanceof InterruptedException) Thread.currentThread().interrupt();
            log.warn("growth_forward_retry error={}", error.getClass().getSimpleName());
        }
    }

    @RabbitListener(queues = ORDERS, containerFactory = "growthListenerFactory")
    public void create(GrowthService.Reservation body, Message message, Channel channel) throws Exception {
        Span span = TraceSupport.receive("growth.order.materialize", SpanKind.CONSUMER, headers(message));
        try (Scope scope = span.makeCurrent()) {
            span.setAttribute("messaging.system", "rabbitmq");
            span.setAttribute("messaging.destination.name", ORDERS);
            span.setAttribute("easyjob.order.id", body.reservationId());
            waitTime(span, message.getMessageProperties().getHeaders().get("easyjob.enqueued_ms"));
            long tag = message.getMessageProperties().getDeliveryTag();
            try {
                service.materialize(body);
                channel.basicAck(tag, false);
            } catch (Exception error) {
                TraceSupport.failure(span, error);
                List<Map<String, ?>> deaths = message.getMessageProperties().getXDeathHeader();
                long attempts = 0;
                if (deaths != null) for (Map<String, ?> death : deaths)
                    if (ORDERS.equals(death.get("queue"))) attempts = ((Number) death.get("count")).longValue();
                span.setAttribute("easyjob.retry.count", attempts);
                if (attempts >= 5) {
                    publish(DEAD, body, 0); channel.basicAck(tag, false);
                    log.error("growth_order_dead reservation={} error={}", body.reservationId(), error.getClass().getSimpleName());
                } else channel.basicNack(tag, false, false);
            }
        } finally { span.end(); }
    }

    @Scheduled(fixedDelay = 1000, scheduler = "growthScheduler")
    public void closeExpired() {
        try {
            for (Map<String, Object> order : store.expiredOrders()) {
                Span span = TraceSupport.linked("growth.order.expire.scan", Map.of());
                try (Scope scope = span.makeCurrent()) {
                    span.setAttribute("easyjob.order.id", order.get("order_id").toString());
                    service.expire(order.get("order_id").toString());
                } catch (Exception error) {
                    TraceSupport.failure(span, error); throw error;
                } finally { span.end(); }
            }
        } catch (Exception error) {
            log.warn("growth_expiry_retry error={}", error.getClass().getSimpleName());
        }
    }

    @RabbitListener(queues = EXPIRE, containerFactory = "growthListenerFactory")
    public void expired(String id, Message message, Channel channel) throws Exception {
        Span span = TraceSupport.linked("growth.order.expire.message", headers(message));
        try (Scope scope = span.makeCurrent()) {
            span.setAttribute("easyjob.order.id", id);
            waitTime(span, message.getMessageProperties().getHeaders().get("easyjob.enqueued_ms"));
            try { service.expire(id); channel.basicAck(message.getMessageProperties().getDeliveryTag(), false); }
            catch (Exception error) {
                TraceSupport.failure(span, error);
                channel.basicNack(message.getMessageProperties().getDeliveryTag(), false, true);
            }
        } finally { span.end(); }
    }

    @Scheduled(fixedDelay = 500, scheduler = "growthScheduler")
    public void effects() {
        for (Map<String, Object> event : store.pendingOutbox()) {
            String id = event.get("event_id").toString();
            Span span = TraceSupport.linked("growth.outbox.effect", Map.of());
            try (Scope scope = span.makeCurrent()) {
                String activity = event.get("activity_id").toString(), order = event.get("order_id").toString();
                span.setAttribute("easyjob.order.id", order);
                span.setAttribute("easyjob.event.id", id);
                try {
                    if ("RELEASE".equals(event.get("event_type"))) {
                        if (!reservations.release(activity, order))
                            throw new IllegalStateException("Redis receipt missing; reconcile required");
                    } else {
                        Map<String, Object> row = store.order(order);
                        long delay = Math.max(1, GrowthValues.instant(row.get("expires_at")).toEpochMilli() - System.currentTimeMillis());
                        publish(DELAY, order, delay);
                    }
                    store.completeOutbox(id);
                } catch (Exception error) {
                    TraceSupport.failure(span, error);
                    store.retryOutbox(error.getClass().getSimpleName(), id);
                    log.warn("growth_effect_retry event={} error={}", id, error.getClass().getSimpleName());
                }
            } finally { span.end(); }
        }
    }
}
