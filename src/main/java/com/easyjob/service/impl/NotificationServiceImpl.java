package com.easyjob.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.dto.NotificationMessage;
import com.easyjob.entity.Notification;
import com.easyjob.mapper.NotificationMapper;
import com.easyjob.service.NotificationService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

@Service
@Slf4j
public class NotificationServiceImpl extends ServiceImpl<NotificationMapper, Notification> implements NotificationService {
    @Autowired
    private NotificationMapper notificationMapper;
    @Autowired
    private RabbitTemplate rabbitTemplate;

    /**
     * 发送通知（写表 + 发 MQ）
     * 入参用 NotificationMessage（@Builder），业务方按需填字段，
     * 关注类通知 articleId/articleTitle/targetPreview 可为 null。
     * 不给自己发通知。
     */
    public void send(NotificationMessage msg) {
        if (msg == null || msg.getUserId() == null || msg.getUserId().equals(msg.getSenderId())) {
            return;
        }
        // 1. 写 notification 表（持久化，保证不丢）
        Notification notification = new Notification();
        notification.setUserId(msg.getUserId());
        notification.setSenderId(msg.getSenderId());
        notification.setSenderNickname(msg.getSenderNickname());
        notification.setSenderAvatar(msg.getSenderAvatar());
        notification.setType(msg.getType());
        notification.setArticleId(msg.getArticleId());
        notification.setArticleTitle(msg.getArticleTitle());
        notification.setTargetId(msg.getTargetId());
        notification.setTargetPreview(msg.getTargetPreview());
        notification.setContent(msg.getContent());
        notification.setIsRead(0);
        notification.setCreateTime(LocalDateTime.now());
        notificationMapper.insert(notification);

        // 回填雪花ID再发 MQ，消费端幂等用
        msg.setNotificationId(notification.getNotificationId());

        // 2. 发 MQ（异步推送给在线用户）
        rabbitTemplate.convertAndSend(
                RabbitMqConstants.TOPIC_EXCHANGE,
                "notification.push",
                msg
        );
        log.info("通知已发送: receiver={}, type={}", msg.getUserId(), msg.getType());
    }

    /**
     * 获取未读消息（最多 50 条）
     */
    public List<Notification> getUnread(Long userId) {
        return notificationMapper.selectList(new LambdaQueryWrapper<Notification>()
                .eq(Notification::getUserId, userId)
                .eq(Notification::getIsRead, 0)
                .orderByDesc(Notification::getCreateTime)
                .last("limit 50")
        );
    }

    /**
     * 分页获取所有消息
     */
    public IPage<Notification> getAll(Long userId, Integer page, Integer size) {
        return notificationMapper.selectPage(
                new Page<>(page, size),
                new LambdaQueryWrapper<Notification>()
                        .eq(Notification::getUserId, userId)
                        .orderByDesc(Notification::getCreateTime)
        );
    }

    /**
     * 标记单条为已读（带 userId 校验，防越权）
     */
    public void markAsRead(Long notificationId, Long userId) {
        notificationMapper.update(null,
                new LambdaUpdateWrapper<Notification>()
                        .eq(Notification::getNotificationId, notificationId)
                        .eq(Notification::getUserId, userId)
                        .set(Notification::getIsRead, 1)
        );
    }

    /**
     * 全部标记已读
     */
    public void markAllAsRead(Long userId) {
        notificationMapper.update(null,
                new LambdaUpdateWrapper<Notification>()
                        .eq(Notification::getUserId, userId)
                        .eq(Notification::getIsRead, 0)
                        .set(Notification::getIsRead, 1)
        );
    }

    /**
     * 获取未读消息数
     */
    public Integer getUnreadCount(Long userId) {
        return Math.toIntExact(notificationMapper.selectCount(new LambdaQueryWrapper<Notification>()
                .eq(Notification::getUserId, userId)
                .eq(Notification::getIsRead, 0)
        ));
    }
}
