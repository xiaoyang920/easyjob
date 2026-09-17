package com.easyjob.constants;

public class RabbitMqConstants {
    /**
     * Topic Exchange
     */
    public static final String TOPIC_EXCHANGE = "easyjob.topic";
    /**
     * 索引文档队列(发布、更新)
     */
    public static final String QUEUE_VECTOR_INDEX = "article.vector.index";
    /**
     * 删除文档队列
     */
    public static final String QUEUE_VECTOR_DELETE = "article.vector.delete";
    // 通知队列
    public static final String QUEUE_NOTIFICATION = "notification.push";
    /**
     * 路由键
     */
    public static final String ROUTING_KEY_PUBLISH = "article.publish";
    public static final String ROUTING_KEY_UPDATE = "article.update";
    public static final String ROUTING_KEY_DELETE = "article.delete";
    /**
     * 通知路由键
     */
    public static final String ROUTING_KEY_NOTIFICATION = "notification.#";
}
