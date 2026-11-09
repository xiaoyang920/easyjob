package com.easyjob.growth;

import com.easyjob.mapper.GrowthMapper;

import com.easyjob.exception.BusinessException;
import com.easyjob.service.AdminConsoleService;
import com.easyjob.service.ReadingGrowthService;
import com.easyjob.mapper.ReadingGrowthMapper;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.*;
import static com.easyjob.growth.GrowthValues.number;
import java.util.HashSet;
import java.util.List;
import java.util.Map;

@Service
public class GrowthService {
    final GrowthMapper store; final GrowthReservations reservations; final ReadingGrowthMapper reading;
    final AdminConsoleService admin; final TransactionTemplate tx;
    private record Cached(Map<String,Object> row,long until){}
    private final java.util.concurrent.ConcurrentHashMap<String,Cached> activityCache=new java.util.concurrent.ConcurrentHashMap<>();
    public GrowthService(GrowthMapper store,GrowthReservations reservations,ReadingGrowthMapper reading,AdminConsoleService admin,PlatformTransactionManager manager){
        this.store=store;this.reservations=reservations;this.reading=reading;this.admin=admin;this.tx=new TransactionTemplate(manager);
    }
    public record Create(String title,int stock,Instant startsAt,Instant endsAt,Integer paySeconds){}
    @JsonIgnoreProperties(ignoreUnknown=false)
    public record Reservation(String activityId,String reservationId,String userId,String requestId,long expiresAt){}
    public Map<String,Object> create(Long uid,Create input){
        admin.requireAdmin(uid);
        if(input==null||input.title()==null||input.title().isBlank()||input.title().length()>80||input.stock()<1||input.stock()>100000
            ||input.startsAt()==null||input.endsAt()==null||!input.endsAt().isAfter(input.startsAt())||input.endsAt().isAfter(input.startsAt().plusSeconds(604800)))
            throw new BusinessException(400,"活动名称、库存或时间范围无效（最长7天）");
        int seconds=input.paySeconds()==null?120:input.paySeconds();
        if(seconds<10||seconds>600)throw new BusinessException(400,"支付期限应为10至600秒");
        String id=UUID.randomUUID().toString();
        store.createActivity(id, input.title().strip(), input.stock(), input.stock(), Timestamp.from(input.startsAt()), Timestamp.from(input.endsAt()), seconds, uid);
        return activityView(store.activity(id));
    }
    public Map<String,Object> activate(Long uid,String id){
        admin.requireAdmin(uid);Map<String, Object> activity=requiredActivity(id);
        if(!List.of("DRAFT","ACTIVE").contains(activity.get("state")))throw new BusinessException(409,"活动状态不允许上线");
        // Never recreate stock for an already active activity after Redis data loss.
        if(activity.get("state").equals("DRAFT")){
            reservations.prepare(id,(int)number(activity,"total_stock"));
            store.activateDraft(id);
        }else if(!id.equals(reservations.redis.opsForValue().get(reservations.key(id,"ready"))))throw new BusinessException(503,"Redis活动状态缺失，请暂停并对账恢复");
        return activityView(store.activity(id));
    }
    public List<Map<String,Object>> activities(){return store.activities().stream().map(this::activityView).toList();}
    public List<Map<String,Object>> adminActivities(Long uid){admin.requireAdmin(uid);return store.adminActivities().stream().map(this::activityView).toList();}
    public Map<String,Object> audit(Long uid,String id){
        admin.requireAdmin(uid);Map<String, Object> activity=requiredActivity(id);
        List<Map<String, Object>> groups=store.orderStates(id);
        long held=store.heldOrders(id);
        long effects=store.pendingEffects(id);
        Map<Object, Object> receipts=reservations.redis.opsForHash().entries(reservations.key(id,"reservations"));
        HashSet<String> persisted=new HashSet<>(store.activityOrders(id).stream().map(row->row.get("order_id").toString()).toList());
        HashSet<String> resolved=new HashSet<>(persisted);
        for(Map<String, Object> effect:store.releasedOrders(id))resolved.add(effect.get("order_id").toString());
        long unconfirmed=receipts.keySet().stream().filter(key->!resolved.contains(key.toString())).count();
        boolean missing=persisted.stream().anyMatch(key->!receipts.containsKey(key));
        Map<String,Object> report=new LinkedHashMap<>();report.put("activity",activityView(activity));report.put("ordersByState",groups);report.put("databaseStockConsistent",number(activity,"available_stock")==number(activity,"total_stock")-held);
        report.put("redisStock",reservations.redis.opsForValue().get(reservations.key(id,"stock")));report.put("unconfirmedReservations",unconfirmed);report.put("pendingEffects",effects);report.put("missingReceipts",missing);return report;
    }
    public void pause(Long uid,String id){
        admin.requireAdmin(uid);Map<String, Object> a=requiredActivity(id);
        if(!List.of("ACTIVE","PAUSED").contains(a.get("state")))throw new BusinessException(409,"只有已上线活动可以暂停");
        // Disarm Lua before changing SQL; admission caches cannot bypass this marker.
        reservations.redis.opsForValue().set(reservations.key(id,"ready"),"PAUSED");
        store.pauseActivity(id);activityCache.remove(id);
    }
    public void resumeActivity(Long uid,String id){
        admin.requireAdmin(uid);Map<String, Object> report=audit(uid,id);Map<String, Object> activity=requiredActivity(id);
        if(!activity.get("state").equals("PAUSED")||!Boolean.TRUE.equals(report.get("databaseStockConsistent"))||Boolean.TRUE.equals(report.get("missingReceipts"))
            ||!Long.valueOf(0).equals(report.get("unconfirmedReservations"))||!Long.valueOf(0).equals(report.get("pendingEffects"))
            ||!Long.toString(number(activity,"available_stock")).equals(report.get("redisStock")))throw new BusinessException(409,"对账未通过，请先重试未确认记录及补偿；禁止覆盖库存");
        // Concurrent expiry can only make resume conservative; its RELEASE remains idempotent.
        store.resumeActivity(id);
        reservations.redis.opsForValue().set(reservations.key(id,"ready"),id);activityCache.remove(id);
    }
    public Map<String,Object> retryReservation(Long uid,String aid,String id){
        admin.requireAdmin(uid);Map<String, Object> receipt=reservations.reservation(aid,id);
        if(receipt==null)throw new BusinessException(409,"预占凭据缺失，不能凭空恢复订单");
        materialize(new Reservation(aid,id,receipt.get("userId").toString(),receipt.get("requestId").toString(),((Number)receipt.get("expiresAt")).longValue()));
        return result(Long.parseLong(receipt.get("userId").toString()),aid,id);
    }
    public Map<String,Object> activityView(Map<String,Object> a){
        Map<String,Object> view=new LinkedHashMap<>();
        view.put("activityId",a.get("activity_id"));view.put("title",a.get("title"));view.put("coinPrice",a.get("coin_price"));view.put("growthSeconds",a.get("growth_seconds"));
        view.put("totalStock",a.get("total_stock"));view.put("availableStock",a.get("available_stock"));view.put("state",a.get("state"));
        view.put("startsAt",GrowthValues.instant(a.get("starts_at")).toString());view.put("endsAt",GrowthValues.instant(a.get("ends_at")).toString());view.put("paySeconds",a.get("pay_seconds"));return view;
    }
    Map<String,Object> requiredActivity(String id){Map<String, Object> a=store.activity(id);if(a==null)throw new BusinessException(404,"活动不存在");return a;}
    public Map<String,Object> grab(Long uid,String id,String request){
        if(uid==null)throw new BusinessException(401,"请登录");UUID.fromString(request);
        Cached cached=activityCache.get(id);Map<String,Object> a;
        if(cached!=null&&cached.until()>System.currentTimeMillis())a=cached.row();
        else{a=requiredActivity(id);if(activityCache.size()>1000)activityCache.clear();activityCache.put(id,new Cached(a,System.currentTimeMillis()+1000));}
        if(!a.get("state").equals("ACTIVE"))throw new BusinessException(409,"活动未开放");
        String rid=reservations.reserve(id,uid,request,GrowthValues.instant(a.get("starts_at")).toEpochMilli(),GrowthValues.instant(a.get("ends_at")).toEpochMilli(),(int)number(a,"pay_seconds"));
        return Map.of("orderId",rid,"activityId",id,"state","ACCEPTED");
    }
    public Map<String,Object> result(Long uid,String activity,String id){
        Map<String, Object> order=store.order(id);
        if(order!=null){if(number(order,"user_id")!=uid||!order.get("activity_id").equals(activity))throw new BusinessException(404,"订单不存在");return orderView(order);}
        Map<String, Object> r=reservations.reservation(activity,id);
        if(r==null||!r.get("userId").toString().equals(uid.toString()))throw new BusinessException(404,"抢购记录不存在");
        Map<String, Object> existing=store.buyerOrder(activity, uid);
        if(existing!=null)return orderView(existing);
        return Map.of("orderId",id,"activityId",activity,"state","ACCEPTED","expiresAt",Instant.ofEpochMilli(((Number)r.get("expiresAt")).longValue()).toString());
    }
    public List<Map<String,Object>> orders(Long uid){return store.orders(uid).stream().map(this::orderView).toList();}
    public Map<String,Object> wallet(Long uid){Map<String, Object> r=store.wallet(uid);return Map.of("balance",r==null?0:r.get("current_coin_count"));}
    public Map<String,Object> orderView(Map<String,Object> o){
        return Map.of("orderId",o.get("order_id"),"activityId",o.get("activity_id"),"coinCost",o.get("coin_cost"),"growthSeconds",o.get("growth_seconds"),"state",o.get("state"),
                "expiresAt",GrowthValues.instant(o.get("expires_at")).toString(),"reason",o.get("reason"));
    }
    public void materialize(Reservation event){
        UUID.fromString(event.activityId());UUID.fromString(event.reservationId());UUID.fromString(event.requestId());
        long uid=Long.parseLong(event.userId());if(uid<=0)throw new IllegalArgumentException("Invalid event owner");
        // A broker duplicate after commit can finish even if Redis is temporarily unavailable.
        if(store.order(event.reservationId())!=null)return;
        Map<String, Object> r=reservations.reservation(event.activityId(),event.reservationId());
        if(r==null||!event.userId().equals(r.get("userId"))||!event.requestId().equals(r.get("requestId"))||event.expiresAt()!=((Number)r.get("expiresAt")).longValue())
            throw new IllegalStateException("Reservation receipt unavailable");
        tx.executeWithoutResult(status->{
            Map<String, Object> a=requiredActivity(event.activityId());
            // INSERT IGNORE serializes duplicate consumers on the unique order/user claim.
            int inserted=store.createOrder(event.reservationId(), event.activityId(), uid, event.requestId(), a.get("coin_price"), a.get("growth_seconds"), Timestamp.from(Instant.ofEpochMilli(event.expiresAt())));
            if(inserted==0){
                // INSERT IGNORE may wait for another consumer to commit. A normal
                // SELECT still sees this RR transaction's earlier activity snapshot.
                // Use a current locking read before deciding this was a buyer collision.
                if(store.lockOrderIdentity(event.reservationId())==null)
                    store.releaseEvent(event.activityId(),event.reservationId());
                return;
            }
            int reserved=store.reserveStock(event.activityId(), Timestamp.from(Instant.ofEpochMilli(event.expiresAt())));
            if(reserved==0){
                store.rejectOrder(event.reservationId());
                store.releaseEvent(event.activityId(),event.reservationId());
            }else store.scheduleExpiry(UUID.randomUUID().toString(), event.activityId(), event.reservationId());
        });
    }
    public Map<String,Object> pay(Long uid,String id){
        return tx.execute(status->{
            Map<String, Object> o=store.lockOrder(id);
            if(o==null||number(o,"user_id")!=uid)throw new BusinessException(404,"订单不存在");
            if(o.get("state").equals("PAID"))return orderView(o);
            if(!o.get("state").equals("PENDING"))throw new BusinessException(409,"订单已关闭或未成功创建");
            // NOW() in the locking SELECT is evaluated before a lock wait. Check again
            // in a new statement after acquiring the row, or a queued payment can pay late.
            if(store.expiredOrder(id)==1){closeLocked(o);return orderView(store.order(id));}
            int changed=store.debitCoins(o.get("coin_cost"), uid, o.get("coin_cost"));
            if(changed!=1)throw new BusinessException(409,"硬币不足，请在期限内补足后重试");
            store.recordCoinPurchase(uid, id, -number(o,"coin_cost"));
            reading.ensureProgress(uid);Map<String, Object> p=reading.lockProgress(uid);
            long purchased=Math.addExact(number(p,"purchased_millis"),number(o,"growth_seconds")*1000L);
            int level=ReadingGrowthService.levelFor(Math.addExact(number(p,"total_millis"),purchased)/1000,(int)number(p,"earned_level"),reading.findRules());
            store.creditGrowth(purchased, level, uid);
            store.recordGrowthPurchase(uid, id, number(o,"growth_seconds")*1000L);
            store.payOrder(id);
            return orderView(store.order(id));
        });
    }
    void closeLocked(Map<String,Object> o){
        store.closeOrder(o.get("order_id"));
        store.restoreStock(o.get("activity_id"));
        store.releaseEvent(o.get("activity_id").toString(),o.get("order_id").toString());
    }
    public void expire(String id){tx.executeWithoutResult(status->{
        Map<String, Object> o=store.lockExpiredOrder(id);if(o!=null)closeLocked(o);
    });}
}
