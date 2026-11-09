package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;

import org.apache.ibatis.annotations.Param;
import java.sql.Timestamp;
import java.util.List;
import java.util.Map;

/** Fixed statements with bound parameters; locking reads bypass MyBatis caches. */
@Mapper
public interface GrowthMapper {
    int createActivity(@Param("id") String id, @Param("title") String title, @Param("stock") int stock, @Param("available") int available, @Param("starts") Timestamp starts, @Param("ends") Timestamp ends, @Param("seconds") int seconds, @Param("uid") Long uid);
    int activateDraft(@Param("id") String id);
    List<Map<String, Object>> activities();
    List<Map<String, Object>> adminActivities();
    List<Map<String, Object>> orderStates(@Param("id") String id);
    long heldOrders(@Param("id") String id);
    long pendingEffects(@Param("id") String id);
    List<Map<String, Object>> activityOrders(@Param("id") String id);
    List<Map<String, Object>> releasedOrders(@Param("id") String id);
    int pauseActivity(@Param("id") String id);
    int resumeActivity(@Param("id") String id);
    Map<String, Object> buyerOrder(@Param("activity") String activity, @Param("uid") Long uid);
    List<Map<String, Object>> orders(@Param("uid") Long uid);
    Map<String, Object> wallet(@Param("uid") Long uid);
    int createOrder(@Param("id") String id, @Param("activity") String activity, @Param("uid") long uid, @Param("request") String request, @Param("price") Object price, @Param("seconds") Object seconds, @Param("expires") Timestamp expires);
    Map<String, Object> lockOrderIdentity(@Param("id") String id);
    int reserveStock(@Param("activity") String activity, @Param("expires") Timestamp expires);
    int rejectOrder(@Param("id") String id);
    int scheduleExpiry(@Param("event") String event, @Param("activity") String activity, @Param("order") String order);
    Map<String, Object> lockOrder(@Param("id") String id);
    long expiredOrder(@Param("id") String id);
    int debitCoins(@Param("price") Object price, @Param("uid") Long uid, @Param("minimum") Object minimum);
    int recordCoinPurchase(@Param("uid") Long uid, @Param("order") String order, @Param("delta") long delta);
    int creditGrowth(@Param("purchased") long purchased, @Param("level") int level, @Param("uid") Long uid);
    int recordGrowthPurchase(@Param("uid") Long uid, @Param("order") String order, @Param("delta") long delta);
    int payOrder(@Param("id") String id);
    int closeOrder(@Param("id") Object id);
    int restoreStock(@Param("id") Object id);
    Map<String, Object> lockExpiredOrder(@Param("id") String id);
    List<Map<String, Object>> relayActivities();
    List<Map<String, Object>> expiredOrders();
    List<Map<String, Object>> pendingOutbox();
    int completeOutbox(@Param("id") String id);
    int retryOutbox(@Param("error") String error, @Param("id") String id);
    Map<String, Object> activity(@Param("id") String id);
    Map<String, Object> order(@Param("id") String id);
    int insertReleaseEvent(@Param("event") String event, @Param("activity") String activity, @Param("order") String order);

    default void releaseEvent(String activity, String order) {
        insertReleaseEvent(java.util.UUID.randomUUID().toString(), activity, order);
    }
}
