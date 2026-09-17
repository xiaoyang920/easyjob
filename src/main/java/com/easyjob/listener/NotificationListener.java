package com.easyjob.listener;

import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.dto.NotificationMessage;
import com.easyjob.service.impl.SseEmitterService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

@Component
@Slf4j
public class NotificationListener {
    @Autowired
    SseEmitterService sseEmitterService;
    @RabbitListener(queues = RabbitMqConstants.QUEUE_NOTIFICATION)
    public void handleNotification(NotificationMessage msg){
        log.info("收到通知消息: receiver={}, type={}", msg.getUserId(), msg.getType());
        // 推送给在线用户（如果不在线就忽略，用户下次登录会拉取）
        sseEmitterService.sendToUser(msg.getUserId(), msg);
    }
}
