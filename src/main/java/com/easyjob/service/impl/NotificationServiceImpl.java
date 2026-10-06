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
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import com.easyjob.enums.NotificationTypeEnum;
import com.easyjob.exception.BusinessException;

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
    @Transactional
    public void send(NotificationMessage msg) {
        boolean review=msg!=null && (NotificationTypeEnum.REVIEW_APPROVED.getCode().equals(msg.getType())
                || NotificationTypeEnum.REVIEW_REJECTED.getCode().equals(msg.getType()));
        if (msg == null || msg.getUserId() == null || (!review && msg.getUserId().equals(msg.getSenderId()))) {
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
        if(notificationMapper.insert(notification)!=1) throw new IllegalStateException("通知保存失败");

        // 回填雪花ID再发 MQ，消费端幂等用
        msg.setNotificationId(notification.getNotificationId());
        msg.setIsRead(notification.getIsRead());
        msg.setCreateTime(notification.getCreateTime());

        // Publish only after the owning business transaction has committed.
        Runnable push=()->{try {rabbitTemplate.convertAndSend(
                RabbitMqConstants.TOPIC_EXCHANGE,
                "notification.push",
                msg
        );} catch(Exception error) {
            // The inbox row remains authoritative and is fetched on reconnection.
            log.warn("通知已保存，实时推送失败: id={}, error={}",msg.getNotificationId(),error.getClass().getSimpleName());
        }};
        if(TransactionSynchronizationManager.isSynchronizationActive())
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization(){
                @Override public void afterCommit(){push.run();}
            });
        else push.run();
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
        return getAll(userId,page,size,null,false);
    }
    public IPage<Notification> getAll(Long userId, Integer page, Integer size,Integer type,boolean unreadOnly) {
        if(page==null || page<1 || page>10000 || size==null || size<1 || size>100
                || (type!=null && (type<1 || type>7))) throw new BusinessException(400,"通知查询参数无效");
        var query=new LambdaQueryWrapper<Notification>().eq(Notification::getUserId,userId)
                .eq(unreadOnly,Notification::getIsRead,0);
        if(Integer.valueOf(6).equals(type)) query.in(Notification::getType,6,7);
        else if(type!=null) query.eq(Notification::getType,type);
        query.orderByDesc(Notification::getCreateTime).orderByDesc(Notification::getNotificationId);
        return notificationMapper.selectPage(
                new Page<>(page, size),
                query
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
