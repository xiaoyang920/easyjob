package com.easyjob.auth;

import com.easyjob.security.IdentityTokens.Principal;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.time.Duration;
import java.util.*;
import com.easyjob.auth.AccountStore.Account;
import java.io.Serializable;
import java.util.ArrayList;
import java.util.Map;
import java.util.Set;

@Service
public class Sessions {
    public static final String PREFIX="auth:v2:session:",DEVICES="auth:v2:devices:";
    private static final SecureRandom RANDOM=new SecureRandom();
    private static final DefaultRedisScript<Long> TOUCH=new DefaultRedisScript<>("if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end;redis.call('EXPIRE',KEYS[1],ARGV[2]);return 1",Long.class);
    private static final DefaultRedisScript<Long> TRACK=new DefaultRedisScript<>("redis.call('SET',KEYS[1],ARGV[1],'EX',ARGV[2]);redis.call('ZADD',KEYS[2],ARGV[3],ARGV[4]);redis.call('EXPIRE',KEYS[2],ARGV[5]);while redis.call('ZCARD',KEYS[2])>20 do local old=redis.call('ZPOPMIN',KEYS[2]);redis.call('DEL',ARGV[6]..old[1]);end;return 1",Long.class);
    private final StringRedisTemplate redis;private final AccountStore accounts;private final ObjectMapper json;
    @Value("${auth.idle-seconds:604800}")private long idle;
    @Value("${auth.max-seconds:2592000}")private long maximum;
    public Sessions(StringRedisTemplate redis,AccountStore accounts,ObjectMapper json){this.redis=redis;this.accounts=accounts;this.json=json;}
    public record Session(String credential,String sid,AccountStore.Account account,long remaining){}
    public static String random(){byte[] bytes=new byte[32];RANDOM.nextBytes(bytes);return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);}
    public static String digest(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException(error);}}
    static AuthFailure expired(){return new AuthFailure(401,"登录已过期，请重新登录");}
    public static void enabled(AccountStore.Account user){if(user==null||user.status()!=1)throw expired();}
    public Session create(AccountStore.Account user,String browser){
        enabled(user);String credential=random(),sid=digest(credential);long now=System.currentTimeMillis();
        Map<String, ? extends Serializable> data=Map.of("uid",user.id(),"ver",user.version(),"deadline",now+maximum*1000,"createdAt",now,"userAgent",browser==null?"未知浏览器":browser.substring(0,Math.min(250,browser.length())));
        try{redis.execute(TRACK,List.of(PREFIX+sid,DEVICES+user.id()),json.writeValueAsString(data),Long.toString(Math.min(idle,maximum)),Long.toString(now),sid,Long.toString(maximum),PREFIX);}
        catch(com.fasterxml.jackson.core.JsonProcessingException error){throw new IllegalStateException(error);}
        return new Session(credential,sid,user,maximum);
    }
    private Map<String,Object> read(String sid){
        if(sid==null||!sid.matches("[a-f0-9]{64}"))throw expired();String value=redis.opsForValue().get(PREFIX+sid);if(value==null)throw expired();return parse(value);
    }
    @SuppressWarnings("unchecked")private Map<String,Object> parse(String value){try{return json.readValue(value,Map.class);}catch(Exception invalid){throw expired();}}
    private AccountStore.Account valid(Map<String,Object> data,String uid,long version){
        if(!Objects.toString(data.get("uid")).equals(uid)||((Number)data.get("ver")).longValue()!=version||((Number)data.get("deadline")).longValue()<=System.currentTimeMillis())throw expired();
        Account account=accounts.byId(Long.parseLong(uid));enabled(account);if(account.version()!=version)throw expired();return account;
    }
    public Principal check(String uid,String sid,long version){Account user=valid(read(sid),uid,version);return new Principal(uid,sid,version,List.of(Integer.toString(user.role())));}
    public Session refresh(String credential){
        if(credential==null||!credential.matches("[A-Za-z0-9_-]{43}"))throw expired();String sid=digest(credential),raw=redis.opsForValue().get(PREFIX+sid);if(raw==null)throw expired();
        Map<String, Object> data=parse(raw);Account user=valid(data,Objects.toString(data.get("uid")),((Number)data.get("ver")).longValue());
        long remaining=(((Number)data.get("deadline")).longValue()-System.currentTimeMillis())/1000;if(remaining<=0)throw expired();
        if(!Long.valueOf(1).equals(redis.execute(TOUCH,List.of(PREFIX+sid),raw,Long.toString(Math.min(idle,remaining)))))throw expired();
        return new Session(credential,sid,user,remaining);
    }
    public void logout(String credential){if(credential==null||!credential.matches("[A-Za-z0-9_-]{43}"))return;String sid=digest(credential);String raw=redis.opsForValue().getAndDelete(PREFIX+sid);if(raw!=null){Map<String, Object> data=parse(raw);redis.opsForZSet().remove(DEVICES+data.get("uid"),sid);broadcast(((Number)data.get("uid")).longValue(),sid);}}
    public List<Map<String,Object>> devices(long uid,String current){
        ArrayList<Map<String, Object>> result=new ArrayList<Map<String,Object>>();Set<String> ids=redis.opsForZSet().reverseRange(DEVICES+uid,0,19);if(ids==null)return result;
        for(String sid:ids){String raw=redis.opsForValue().get(PREFIX+sid);if(raw==null){redis.opsForZSet().remove(DEVICES+uid,sid);continue;}Map<String, Object> data=parse(raw);
            if(((Number)data.get("uid")).longValue()!=uid)continue;
            result.add(Map.of("id",sid,"current",sid.equals(current),"userAgent",data.get("userAgent"),"createdAt",data.get("createdAt"),"lastSeen",data.get("createdAt")));}
        return result;
    }
    public void revoke(long uid,String sid){
        Map<String, Object> data=read(sid);if(((Number)data.get("uid")).longValue()!=uid)throw new AuthFailure(404,"设备不存在");redis.delete(PREFIX+sid);redis.opsForZSet().remove(DEVICES+uid,sid);broadcast(uid,sid);
    }
    public void revokeOthers(long uid,String current){Set<String> ids=redis.opsForZSet().range(DEVICES+uid,0,-1);if(ids!=null)for(String sid:ids)if(!sid.equals(current)){if(Boolean.TRUE.equals(redis.hasKey(PREFIX+sid)))revoke(uid,sid);else redis.opsForZSet().remove(DEVICES+uid,sid);}}
    private void broadcast(long uid,String sid){try{redis.convertAndSend("easyjob:auth:revoke",json.writeValueAsString(Map.of("userId",Long.toString(uid),"sid",sid)));}catch(Exception ignored){/* periodic checks close connections if best-effort broadcast is lost */}}
}
