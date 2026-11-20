package com.easyjob.auth;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.*;

@Service
public class VerificationCodes {
    private static final SecureRandom RANDOM=new SecureRandom();
    private static final DefaultRedisScript<Long> LIMIT=new DefaultRedisScript<>("local n=redis.call('INCR',KEYS[1]);if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end;return n",Long.class);
    private static final DefaultRedisScript<Long> VERIFY=new DefaultRedisScript<>("local code=redis.call('GET',KEYS[1]);if not code then return 0 end;local n=redis.call('INCR',KEYS[2]);if n==1 then redis.call('EXPIRE',KEYS[2],600) end;if n>5 then redis.call('DEL',KEYS[1]);return 0 end;if code~=ARGV[1] then if n==5 then redis.call('DEL',KEYS[1]) end;return 0 end;redis.call('DEL',KEYS[1],KEYS[2]);return 1",Long.class);
    private final StringRedisTemplate redis;private final JavaMailSender mail;private final String from;
    public VerificationCodes(StringRedisTemplate redis,JavaMailSender mail,@Value("${spring.mail.username}")String from){this.redis=redis;this.mail=mail;this.from=from;}
    public static String email(String text){if(text==null||text.length()>254||!text.trim().matches("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$"))throw new AuthFailure(400,"请输入有效邮箱");return text.trim().toLowerCase(Locale.ROOT);}
    public void limit(String name,int maximum,int seconds){Long n=redis.execute(LIMIT,List.of("auth:v2:limit:"+Sessions.digest(name)),Integer.toString(seconds));if(n==null||n>maximum)throw new AuthFailure(429,"操作过于频繁，请稍后重试");}
    private String key(String email,String purpose){return "auth:v2:code:"+purpose+":"+Sessions.digest(email);}
    public void send(String email,String purpose,boolean deliver){
        limit("code:"+email+":"+purpose,1,60);if(!deliver)return;
        String code=String.format("%06d",RANDOM.nextInt(1000000)),key=key(email,purpose);redis.opsForValue().set(key,Sessions.digest(email+":"+code),Duration.ofMinutes(10));redis.delete(key+":attempts");
        SimpleMailMessage message=new SimpleMailMessage();message.setFrom(from);message.setTo(email);message.setSubject("EasyJob 邮箱验证码");message.setText("验证码："+code+"，10 分钟内有效。请勿向他人透露。");
        try{mail.send(message);}catch(RuntimeException unavailable){redis.delete(key);throw new AuthFailure(503,"邮件服务暂不可用，请稍后重试");}
    }
    public void consume(String email,String purpose,String code){if(code==null||!code.matches("[0-9]{6}"))throw new AuthFailure(400,"验证码无效或已过期");String key=key(email,purpose);if(!Long.valueOf(1).equals(redis.execute(VERIFY,List.of(key,key+":attempts"),Sessions.digest(email+":"+code))))throw new AuthFailure(400,"验证码无效或已过期");}
}
