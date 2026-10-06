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
            + ":" + digest(user.getPassword());
        redis.opsForValue().set(PREFIX + id, value, Duration.ofSeconds(duration));
        return new Session(credential, id, user, maxSeconds);
    }

    public Session refresh(String credential) {
        if (credential == null || !credential.matches("[A-Za-z0-9_-]{43}")) throw expired();
        String id = digest(credential);
        String value = redis.opsForValue().get(PREFIX + id);
        if (value == null) throw expired();
        String[] fields = value.split(":", -1);
        if (fields.length != 3) throw expired();
        long uid, remaining;
        try {
            uid = Long.parseLong(fields[0]);
            remaining = (Long.parseLong(fields[1]) - System.currentTimeMillis()) / 1000;
        } catch (NumberFormatException e) { throw expired(); }
        if (remaining <= 0) { redis.delete(PREFIX + id); throw expired(); }
        User user = users.selectById(uid);
        if (user == null || !Integer.valueOf(1).equals(user.getStatus())
                || !digest(user.getPassword()).equals(fields[2])) {
            redis.delete(PREFIX + id);
            throw expired();
        }
        long ttl = Math.min(idleSeconds, remaining);
        // Logout racing this refresh cannot recreate the deleted session.
        if (!Long.valueOf(1).equals(redis.execute(TOUCH, List.of(PREFIX + id), value, String.valueOf(ttl))))
            throw expired();
        return new Session(credential, id, user, remaining);
    }

    public boolean valid(String id, Long uid) {
        if (id == null || !id.matches("[a-f0-9]{64}") || uid == null) return false;
        String value = redis.opsForValue().get(PREFIX + id);
        return value != null && value.startsWith(uid + ":");
    }

    public void revoke(String credential) {
        if (credential != null && credential.matches("[A-Za-z0-9_-]{43}")) redis.delete(PREFIX + digest(credential));
    }

    private static BusinessException expired() { return new BusinessException(401, "登录已过期，请重新登录"); }
    private static void requireEnabled(User user) {
        if (user == null || !Integer.valueOf(1).equals(user.getStatus()))
            throw new BusinessException(401, "账号不可用，请联系管理员");
    }
}
