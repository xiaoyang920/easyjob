package com.easyjob.growth;

import com.easyjob.mapper.GrowthMapper;
import com.easyjob.observability.TraceSupport;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.rabbitmq.client.Channel;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.context.Scope;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.Limit;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import java.util.*;
import java.util.concurrent.TimeUnit;
import static com.easyjob.growth.GrowthMessaging.*;
import com.easyjob.growth.GrowthService.Reservation;
import java.util.List;
import java.util.Map;
import org.springframework.data.redis.connection.stream.MapRecord;

@Component
public class GrowthWorkers {
    private static final Logger log=LoggerFactory.getLogger(GrowthWorkers.class);
    final GrowthMapper store;final GrowthReservations reservations;final GrowthService service;final RabbitTemplate rabbit;final ObjectMapper json;
    public GrowthWorkers(GrowthMapper store,GrowthReservations reservations,GrowthService service,RabbitTemplate rabbit,ObjectMapper json){this.store=store;this.reservations=reservations;this.service=service;this.rabbit=rabbit;this.json=json;rabbit.setMandatory(true);}
    void publish(String routing,Object body,long delay)throws Exception{
        Span span = TraceSupport.start("growth.mq.publish", SpanKind.PRODUCER);
        span.setAttribute("messaging.destination.name", routing);
        try (Scope ignored = span.makeCurrent()) {
            CorrelationData confirm = new CorrelationData(UUID.randomUUID().toString());
            Map<String, String> context = TraceSupport.inject();
            rabbit.convertAndSend(EXCHANGE, routing, body, message -> {
                message.getMessageProperties().setDeliveryMode(org.springframework.amqp.core.MessageDeliveryMode.PERSISTENT);
                if (delay > 0) message.getMessageProperties().setExpiration(Long.toString(delay));
                for (String key : List.of("traceparent", "tracestate")) {
                    if (context.containsKey(key)) message.getMessageProperties().setHeader(key, context.get(key));
                }
                return message;
            }, confirm);
            if (!confirm.getFuture().get(3, TimeUnit.SECONDS).isAck() || confirm.getReturned() != null) {
                throw new IllegalStateException("Growth message not confirmed/routed");
            }
        } catch (Exception error) {
            TraceSupport.failure(span, error);
            throw error;
        } finally {
            span.end();
        }
    }

    private static Map<String, String> traceHeaders(Map<?, ?> values) {
        Map<String, String> carrier = new HashMap<>();
        for (String key : List.of("traceparent", "tracestate")) {
            if (values.get(key) instanceof String value) carrier.put(key, value);
        }
        return carrier;
    }
    @Scheduled(fixedDelay=200,scheduler="growthScheduler")
    public void forward(){
        try{
            // Stream is a durable Redis outbox. Multiple relays may publish a duplicate; consumers are idempotent.
            for(Map<String, Object> a:store.relayActivities()){
                String key=reservations.key(a.get("activity_id").toString(),"events");
                List<MapRecord<String, Object, Object>> records=reservations.redis.opsForStream().range(key,Range.unbounded(),Limit.limit().count(50));
                if(records==null)continue;
                for(MapRecord<String, Object, Object> record:records){
                    Span span = TraceSupport.receive("growth.stream.forward", SpanKind.CONSUMER, traceHeaders(record.getValue()));
                    try (Scope ignored = span.makeCurrent()) {
                        if (record.getValue().get("enqueued_at") instanceof String queued && queued.matches("[0-9]{1,15}")) {
                            span.setAttribute("easyjob.queue.wait_ms", Math.max(0, System.currentTimeMillis() - Long.parseLong(queued)));
                        }
                        Reservation event = json.readValue(record.getValue().get("body").toString(), Reservation.class);
                        publish(ORDERS, event, 0);
                        reservations.redis.opsForStream().delete(key, record.getId());
                    } catch (Exception error) {
                        TraceSupport.failure(span, error);
                        throw error;
                    } finally {
                        span.end();
                    }
                }
            }
        }catch(Exception e){if(e instanceof InterruptedException)Thread.currentThread().interrupt();log.warn("growth_forward_retry error={}",e.getClass().getSimpleName());}
    }
    @RabbitListener(queues=ORDERS,containerFactory="growthListenerFactory")
    public void create(GrowthService.Reservation body,Message message,Channel channel)throws Exception{
        long tag=message.getMessageProperties().getDeliveryTag();
        Span span = TraceSupport.receive("growth.order.materialize", SpanKind.CONSUMER,
                traceHeaders(message.getMessageProperties().getHeaders()));
        try (Scope ignored = span.makeCurrent()) {
            try {
                service.materialize(body);
                channel.basicAck(tag, false);
            } catch (Exception error) {
                TraceSupport.failure(span, error);
                List<Map<String, ?>> deaths = message.getMessageProperties().getXDeathHeader();
                long attempts = 0;
                if (deaths != null) {
                    for (Map<String, ?> death : deaths) {
                        if (ORDERS.equals(death.get("queue"))) attempts = ((Number) death.get("count")).longValue();
                    }
                }
                span.setAttribute("easyjob.retry.count", attempts);
                if (attempts >= 5) {
                    publish(DEAD, body, 0);
                    channel.basicAck(tag, false);
                    log.error("growth_order_dead reservation={} error={}", body.reservationId(), error.getClass().getSimpleName());
                } else {
                    channel.basicNack(tag, false, false);
                }
            }
        } finally { span.end(); }
    }
    @Scheduled(fixedDelay=1000,scheduler="growthScheduler")
    public void closeExpired(){
        try{for(Map<String, Object> o:store.expiredOrders())service.expire(o.get("order_id").toString());}
        catch(Exception e){log.warn("growth_expiry_retry error={}",e.getClass().getSimpleName());}
    }
    @RabbitListener(queues=EXPIRE,containerFactory="growthListenerFactory")
    public void expired(String id,Message message,Channel channel)throws Exception{
        Span span = TraceSupport.receive("growth.order.expire", SpanKind.CONSUMER,
                traceHeaders(message.getMessageProperties().getHeaders()));
        try (Scope ignored = span.makeCurrent()) {
            service.expire(id);
            channel.basicAck(message.getMessageProperties().getDeliveryTag(), false);
        } catch (Exception error) {
            TraceSupport.failure(span, error);
            channel.basicNack(message.getMessageProperties().getDeliveryTag(), false, true);
        } finally { span.end(); }
    }
    @Scheduled(fixedDelay=500,scheduler="growthScheduler")
    public void effects(){
        for(Map<String, Object> e:store.pendingOutbox()){
            String id=e.get("event_id").toString();
            try{
                String aid=e.get("activity_id").toString(),oid=e.get("order_id").toString();
                if("RELEASE".equals(e.get("event_type"))){if(!reservations.release(aid,oid))throw new IllegalStateException("Redis receipt missing; reconcile required");}
                else{
                    Map<String, Object> order=store.order(oid);long delay=Math.max(1,GrowthValues.instant(order.get("expires_at")).toEpochMilli()-System.currentTimeMillis());
                    publish(DELAY,oid,delay);
                }
                store.completeOutbox(id);
            }catch(Exception error){
                store.retryOutbox(error.getClass().getSimpleName(), id);
                log.warn("growth_effect_retry event={} error={}",id,error.getClass().getSimpleName());
            }
        }
    }
}
