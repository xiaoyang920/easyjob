package com.easyjob.auth;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.Map;

@Component
public class RevocationPublisher {
    private final JdbcTemplate sql;private final RabbitTemplate rabbit;
    public RevocationPublisher(JdbcTemplate sql,RabbitTemplate rabbit){this.sql=sql;this.rabbit=rabbit;}
    @Scheduled(fixedDelay=3000,initialDelay=5000)public void publish(){
        String token=UUID.randomUUID().toString();
        try{
            sql.update("UPDATE auth_outbox SET lease_token=?,lease_until=TIMESTAMPADD(SECOND,30,UTC_TIMESTAMP(6)) WHERE published_at IS NULL AND next_attempt_at<=UTC_TIMESTAMP(6) AND (lease_until IS NULL OR lease_until<UTC_TIMESTAMP(6)) ORDER BY created_at LIMIT 20",token);
            for(Map<String, Object> row:sql.queryForList("SELECT event_id,user_id,sid,auth_version FROM auth_outbox WHERE lease_token=?",token)){
                String id=row.get("event_id").toString();try{
                    Map<String, String> data=Map.of("eventId",id,"userId",row.get("user_id").toString(),"sid",Objects.toString(row.get("sid"),""),"version",row.get("auth_version").toString());
                    CorrelationData correlation=new CorrelationData(id);rabbit.convertAndSend("easyjob.auth.revoked","",data,correlation);
                    if(!correlation.getFuture().get(5,TimeUnit.SECONDS).isAck())throw new IllegalStateException("Broker did not acknowledge");
                    sql.update("UPDATE auth_outbox SET published_at=UTC_TIMESTAMP(6),lease_token=NULL,lease_until=NULL WHERE event_id=? AND lease_token=?",id,token);
                }catch(Exception failure){sql.update("UPDATE auth_outbox SET attempts=attempts+1,next_attempt_at=TIMESTAMPADD(SECOND,30,UTC_TIMESTAMP(6)),lease_token=NULL,lease_until=NULL WHERE event_id=? AND lease_token=?",id,token);}
            }
        }catch(Exception failure){org.slf4j.LoggerFactory.getLogger(getClass()).warn("Auth revocation publication deferred: {}",failure.getClass().getSimpleName());}
    }
}
