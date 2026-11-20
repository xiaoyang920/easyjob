package com.easyjob.growth;

import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.config.SimpleRabbitListenerContainerFactory;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.context.annotation.*;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;

@Configuration
public class GrowthMessaging {
    public static final String EXCHANGE="growth.orders", ORDERS="growth.orders.create", RETRY="growth.orders.retry", DEAD="growth.orders.dead", DELAY="growth.orders.delay", EXPIRE="growth.orders.expire";
    @Bean public Declarables growthTopology(){
        DirectExchange exchange=new DirectExchange(EXCHANGE,true,false);
        Queue orders=QueueBuilder.durable(ORDERS).deadLetterExchange(EXCHANGE).deadLetterRoutingKey(RETRY).build();
        Queue retry=QueueBuilder.durable(RETRY).ttl(3000).deadLetterExchange(EXCHANGE).deadLetterRoutingKey(ORDERS).build();
        Queue dead=QueueBuilder.durable(DEAD).build();
        Queue delay=QueueBuilder.durable(DELAY).deadLetterExchange(EXCHANGE).deadLetterRoutingKey(EXPIRE).build();
        Queue expire=QueueBuilder.durable(EXPIRE).build();
        return new Declarables(exchange,orders,retry,dead,delay,expire,
            BindingBuilder.bind(orders).to(exchange).with(ORDERS),BindingBuilder.bind(retry).to(exchange).with(RETRY),
            BindingBuilder.bind(dead).to(exchange).with(DEAD),BindingBuilder.bind(delay).to(exchange).with(DELAY),BindingBuilder.bind(expire).to(exchange).with(EXPIRE));
    }
    @Bean public SimpleRabbitListenerContainerFactory growthListenerFactory(ConnectionFactory connection,MessageConverter converter){
        SimpleRabbitListenerContainerFactory f=new SimpleRabbitListenerContainerFactory();f.setConnectionFactory(connection);f.setMessageConverter(converter);
        f.setConcurrentConsumers(2);f.setMaxConcurrentConsumers(4);f.setPrefetchCount(20);f.setAcknowledgeMode(AcknowledgeMode.MANUAL);return f;
    }
    @Bean public ThreadPoolTaskScheduler growthScheduler(){ThreadPoolTaskScheduler scheduler=new ThreadPoolTaskScheduler();scheduler.setPoolSize(3);scheduler.setThreadNamePrefix("growth-maintenance-");return scheduler;}
}
