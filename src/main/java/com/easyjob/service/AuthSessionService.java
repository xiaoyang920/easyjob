package com.easyjob.service;

import com.easyjob.entity.User;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.UserMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.Base64;
import java.util.HexFormat;
import java.util.List;
import java.util.ArrayList;
import java.util.Map;
import com.alibaba.fastjson2.JSON;
import com.easyjob.config.ChatWebSocketHandler;

/** Opaque browser credential; only its digest is stored in Redis and access JWTs. */
@Service
public class AuthSessionService {
    private static final String PREFIX = "auth:session:";
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final DefaultRedisScript<Long> TOUCH = new DefaultRedisScript<>(
        "if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end " +
        "redis.call('EXPIRE', KEYS[1], ARGV[2]); return 1", Long.class);
    private final StringRedisTemplate redis;
    private final UserMapper users;
    @Value("${easyjob.jwt.refresh-idle-seconds:604800}")
    private long idleSeconds = 604800;
    @Value("${easyjob.jwt.refresh-max-seconds:2592000}")
    private long maxSeconds = 2592000;

    public AuthSessionService(StringRedisTemplate redis, UserMapper users) {
        this.redis = redis;
        this.users = users;
    }

    public record Session(String credential, String id, User user, long remainingSeconds) {}

    private static final String DEVICES = "auth:devices:";
    private static final String DEVICE = "auth:device:";
    private static final DefaultRedisScript<Long> TRACK = new DefaultRedisScript<>(
        "if redis.call('EXISTS',KEYS[1])==0 then return 0 end " +
        "redis.call('SET',KEYS[2],ARGV[1],'EX',ARGV[2]);redis.call('ZADD',KEYS[3],ARGV[3],ARGV[4]);" +
        "redis.call('EXPIRE',KEYS[3],ARGV[2]);" +
        "while redis.call('ZCARD',KEYS[3])>20 do local old=redis.call('ZPOPMIN',KEYS[3]);" +
        "redis.call('DEL','auth:session:'..old[1],'auth:device:'..old[1]);end;return 1", Long.class);

    /** Only digest identifiers and coarse browser metadata are visible to the account owner. */
    public void track(Session session, String userAgent) {
        long now=System.currentTimeMillis();
        String ua=userAgent==null?"未知浏览器":userAgent.substring(0,Math.min(250,userAgent.length()));
        String metadata=JSON.toJSONString(Map.of("userAgent",ua,"createdAt",now,"lastSeen",now));
        redis.execute(TRACK,List.of(PREFIX+session.id(),DEVICE+session.id(),DEVICES+session.user().getUserId()),
                metadata,Long.toString(session.remainingSeconds()),Long.toString(now),session.id());
    }

    public List<Map<String,Object>> devices(Long uid, String current) {
        var ids=redis.opsForZSet().reverseRange(DEVICES+uid,0,19);
        var result=new ArrayList<Map<String,Object>>();
        if(ids!=null)for(String id:ids){
            if(!valid(id,uid)){redis.opsForZSet().remove(DEVICES+uid,id);redis.delete(DEVICE+id);continue;}
            String raw=redis.opsForValue().get(DEVICE+id);
            var info=new java.util.HashMap<String,Object>();
            if(raw!=null) info.putAll(JSON.parseObject(raw));
            info.put("id",id);info.put("current",id.equals(current));result.add(info);
        }
        return result;
    }

    public void revokeDevice(Long uid,String id){
        if(id==null || !id.matches("[a-f0-9]{64}"))throw new BusinessException(400,"设备标识无效");
        String value=redis.opsForValue().get(PREFIX+id);
        if(value!=null && !value.startsWith(uid+":"))throw new BusinessException(404,"设备不存在");
        redis.delete(List.of(PREFIX+id,DEVICE+id));redis.opsForZSet().remove(DEVICES+uid,id);
        ChatWebSocketHandler.disconnectSession(uid,id);
    }

    public void revokeOthers(Long uid,String current){
        var ids=redis.opsForZSet().range(DEVICES+uid,0,-1);
        if(ids!=null)for(String id:ids)if(!id.equals(current))revokeDevice(uid,id);
    }

    public static String digest(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    public Session create(User user) {
        requireEnabled(user);
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        String credential = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        String id = digest(credential);
        long duration = Math.min(idleSeconds, maxSeconds);
        if (duration <= 0) throw new IllegalStateException("Invalid auth session duration");
        String value = user.getUserId() + ":" + (System.currentTimeMillis() + maxSeconds * 1000)
            + ":" + digest(user.getPassword()) + ":" + version(user);
        redis.opsForValue().set(PREFIX + id, value, Duration.ofSeconds(duration));
        return new Session(credential, id, user, maxSeconds);
    }

    public Session refresh(String credential) {
        if (credential == null || !credential.matches("[A-Za-z0-9_-]{43}")) throw expired();
        String id = digest(credential);
        String value = redis.opsForValue().get(PREFIX + id);
        if (value == null) throw expired();
        String[] fields = value.split(":", -1);
        if (fields.length != 3 && fields.length != 4) throw expired();
        long uid, remaining;
        try {
            uid = Long.parseLong(fields[0]);
            remaining = (Long.parseLong(fields[1]) - System.currentTimeMillis()) / 1000;
        } catch (NumberFormatException e) { throw expired(); }
        if (remaining <= 0) { redis.delete(PREFIX + id); throw expired(); }
        User user = users.selectById(uid);
        if (!matches(user, fields)) {
            redis.delete(PREFIX + id);
            throw expired();
        }
        long ttl = Math.min(idleSeconds, remaining);
        // Logout racing this refresh cannot recreate the deleted session.
        if (!Long.valueOf(1).equals(redis.execute(TOUCH, List.of(PREFIX + id), value, String.valueOf(ttl))))
            throw expired();
        String metadata=redis.opsForValue().get(DEVICE+id);
        if(metadata!=null){var info=JSON.parseObject(metadata);info.put("lastSeen",System.currentTimeMillis());
            redis.execute(TRACK,List.of(PREFIX+id,DEVICE+id,DEVICES+uid),info.toJSONString(),Long.toString(remaining),Long.toString(System.currentTimeMillis()),id);}
        else track(new Session(credential,id,user,remaining),"历史登录设备");
        return new Session(credential, id, user, remaining);
    }

    public boolean valid(String id, Long uid) {
        if (id == null || !id.matches("[a-f0-9]{64}") || uid == null) return false;
        String value = redis.opsForValue().get(PREFIX + id);
        if(value==null) return false;
        String[] fields=value.split(":",-1);
        if((fields.length!=3 && fields.length!=4) || !uid.toString().equals(fields[0])) return false;
        try {if(Long.parseLong(fields[1])<=System.currentTimeMillis())return false;}
        catch(NumberFormatException e){return false;}
        return matches(users.selectById(uid),fields);
    }

    public boolean validLegacy(Long uid) {
        User user=uid==null?null:users.selectById(uid);
        return user!=null && Integer.valueOf(1).equals(user.getStatus()) && version(user)==0;
    }
    private static long version(User user){return user.getAuthVersion()==null?0:user.getAuthVersion();}
    private static boolean matches(User user,String[] fields) {
        return user!=null && Integer.valueOf(1).equals(user.getStatus()) && user.getPassword()!=null
                && digest(user.getPassword()).equals(fields[2])
                && Long.toString(version(user)).equals(fields.length==4?fields[3]:"0");
    }

    public void revoke(String credential) {
        if (credential != null && credential.matches("[A-Za-z0-9_-]{43}")) {
            String id=digest(credential),value=redis.opsForValue().get(PREFIX+id);
            redis.delete(PREFIX+id);
            if(value!=null)try{revokeDevice(Long.valueOf(value.split(":",2)[0]),id);}catch(NumberFormatException ignored){}
        }
    }

    private static BusinessException expired() { return new BusinessException(401, "登录已过期，请重新登录"); }
    private static void requireEnabled(User user) {
        if (user == null || !Integer.valueOf(1).equals(user.getStatus()))
            throw new BusinessException(401, "账号不可用，请联系管理员");
    }
}
