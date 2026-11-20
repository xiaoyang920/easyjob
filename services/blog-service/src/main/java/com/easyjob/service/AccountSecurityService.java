package com.easyjob.service;

import com.easyjob.config.ChatWebSocketHandler;
import com.easyjob.config.ArticleWebSocketHandler;
import com.easyjob.entity.User;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.AccountSecurityMapper;
import com.easyjob.utils.PasswordUtil;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.List;
import java.util.Locale;

@Service
public class AccountSecurityService {
    private final AccountSecurityMapper users;
    private final StringRedisTemplate redis;
    private final EmailService mail;
    private final ChatWebSocketHandler chats;
    private final ArticleWebSocketHandler articles;
    private static final SecureRandom RANDOM=new SecureRandom();
    private static final DefaultRedisScript<Long> LIMIT=new DefaultRedisScript<>(
        "local n=redis.call('INCR',KEYS[1]);if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end;return n",Long.class);
    private static final DefaultRedisScript<Long> VERIFY=new DefaultRedisScript<>(
        "local code=redis.call('GET',KEYS[1]);if not code then return 0 end;"+
        "local n=redis.call('INCR',KEYS[2]);if n==1 then redis.call('EXPIRE',KEYS[2],600) end;"+
        "if n>5 then redis.call('DEL',KEYS[1]);return 0 end;"+
        "if code~=ARGV[1] then if n==5 then redis.call('DEL',KEYS[1]) end;return 0 end;"+
        "redis.call('DEL',KEYS[1],KEYS[2]);return 1",Long.class);
    public AccountSecurityService(AccountSecurityMapper users,StringRedisTemplate redis,EmailService mail,
                                  ChatWebSocketHandler chats,ArticleWebSocketHandler articles){
        this.users=users;this.redis=redis;this.mail=mail;this.chats=chats;this.articles=articles;
    }
    public static void validatePassword(String value){
        if(value==null || value.length()<8 || value.getBytes(StandardCharsets.UTF_8).length>72)
            throw new BusinessException(400,"新密码至少8个字符，且不超过72字节");
    }
    private static String email(String value){
        if(value==null || value.length()>254 || !value.trim().matches("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$"))
            throw new BusinessException(400,"请输入有效邮箱");
        return value.trim().toLowerCase(Locale.ROOT);
    }
    private void limit(String key,int max,int seconds){
        Long n=redis.execute(LIMIT,List.of("auth:security-limit:"+AuthSessionService.digest(key)),Integer.toString(seconds));
        if(n==null || n>max)throw new BusinessException(429,"操作过于频繁，请稍后再试");
    }
    public void sendCode(String input,String address){
        String email=email(input),id=AuthSessionService.digest(email);
        // Gateway rate limiting follows the source IP; this limit follows the email.
        limit("reset-email:"+id,1,60);
        User user=users.findByEmail(email);
        if(user==null || !Integer.valueOf(1).equals(user.getStatus()))return;
        String code=String.format("%06d",RANDOM.nextInt(1000000)),key="auth:password-code:"+id;
        redis.opsForValue().set(key,AuthSessionService.digest(email+":"+code),Duration.ofMinutes(10));
        redis.delete(key+":attempts");
        try{mail.sendVerificationCode(email,code);}
        catch(RuntimeException error){redis.delete(key);throw new BusinessException(503,"邮件服务暂不可用，请稍后重试");}
    }
    @Transactional public void reset(String input,String code,String password,String address){
        String email=email(input);validatePassword(password);limit("reset-attempt:"+AuthSessionService.digest(email),20,600);
        if(code==null || !code.matches("[0-9]{6}"))throw new BusinessException(400,"验证码无效或已过期");
        String key="auth:password-code:"+AuthSessionService.digest(email);
        if(!Long.valueOf(1).equals(redis.execute(VERIFY,List.of(key,key+":attempts"),AuthSessionService.digest(email+":"+code))))
            throw new BusinessException(400,"验证码无效或已过期，请重新获取");
        User candidate=users.findByEmail(email);
        if(candidate==null)throw new BusinessException(400,"验证码无效或已过期");
        replace(users.lockUser(candidate.getUserId()),password);
    }
    @Transactional public void change(Long uid,String current,String password){
        validatePassword(password);limit("change:"+uid,5,300);
        User user=users.lockUser(uid);
        if(user==null || current==null || !matches(current,user.getPassword()))
            throw new BusinessException(400,"当前密码不正确");
        replace(user,password);
    }
    private boolean matches(String input,String stored){
        if(stored==null || input.getBytes(StandardCharsets.UTF_8).length>72)return false;
        return PasswordUtil.isEncoded(stored)?PasswordUtil.matches(input,stored):MessageDigest.isEqual(input.getBytes(StandardCharsets.UTF_8),stored.getBytes(StandardCharsets.UTF_8));
    }
    private void replace(User user,String password){
        if(user==null || !Integer.valueOf(1).equals(user.getStatus()))throw new BusinessException(400,"账号不可用");
        if(users.changePassword(user.getUserId(),PasswordUtil.encode(password))!=1)throw new BusinessException(409,"账号已变化，请重试");
        Runnable close=()->{chats.disconnectUser(user.getUserId());articles.disconnectUser(user.getUserId());};
        if(TransactionSynchronizationManager.isSynchronizationActive())TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization(){@Override public void afterCommit(){close.run();}});
        else close.run();
    }
}
