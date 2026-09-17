package com.easyjob.config;

import com.easyjob.constants.RabbitMqConstants;
import org.springframework.amqp.core.*;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import static com.easyjob.constants.RabbitMqConstants.*;

@Configuration
public class RabbitMqConfig {
    /**
     * 创建消息转换器
     */
    @Bean
    public MessageConverter jsonMessageConverter(){
        return new Jackson2JsonMessageConverter();
    }
    /**
     * 创建Topic Exchange
     */
    @Bean
    public TopicExchange topicExchange(){
        return new TopicExchange(TOPIC_EXCHANGE,true, false);
    }
    /**
     * 创建索引文档队列
     */
    @Bean
    public Queue vectorIndexQueue(){
        return QueueBuilder.durable(QUEUE_VECTOR_INDEX).build();
    }
    /**
     * 创建删除文档队列
     */
    @Bean
    public Queue vectorDeleteQueue(){
        return QueueBuilder.durable(QUEUE_VECTOR_DELETE).build();
    }
    /**
     * 创建索引文档队列绑定关系
     */
    @Bean
    public Binding bindPublish(Queue vectorIndexQueue, TopicExchange topicExchange){
        return BindingBuilder.bind(vectorIndexQueue)
                .to(topicExchange)
                .with(ROUTING_KEY_PUBLISH);
    }
    /**
     * 创建删除文档队列绑定关系
     */
    @Bean
    public Binding bindUpdate(Queue vectorIndexQueue, TopicExchange topicExchange){
        return BindingBuilder.bind(vectorIndexQueue)
                .to(topicExchange)
                .with(ROUTING_KEY_UPDATE);
    }
    /**
     * 创建删除文档队列绑定关系
     */
    @Bean
    public Binding bindDelete(Queue vectorDeleteQueue, TopicExchange topicExchange){
        return BindingBuilder.bind(vectorDeleteQueue)
                .to(topicExchange)
                .with(ROUTING_KEY_DELETE);
    }
    @Bean
    public Queue notificationQueue(){
        return  new Queue(QUEUE_NOTIFICATION, true);
    }
    @Bean
    public Binding notificationBinding(Queue notificationQueue, TopicExchange topicExchange){
        return BindingBuilder.bind(notificationQueue).to(topicExchange)
                .with(ROUTING_KEY_NOTIFICATION);
    }
}
