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
