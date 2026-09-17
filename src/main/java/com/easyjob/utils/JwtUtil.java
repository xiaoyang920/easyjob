package com.easyjob.utils;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.SignatureAlgorithm;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.Date;
import java.util.HashMap;
import java.util.Map;

/**
 * JWT工具类
 * 在Claims中包含用户ID和用户名
 */
@Component
public class JwtUtil {

    /**
     * 密钥 - 从配置文件读取
     */
    @Value("${easyjob.jwt.secret-key}")
    private String secret;

    /**
     * 过期时间（毫秒）- 默认7天
     */
    @Value("${easyjob.jwt.ttl}")
    private Long expire;

    /**
     * 令牌前缀
     */
    @Value("${easyjob.jwt.token-name}")
    private String tokenName;

    /**
     * 生成JWT令牌（包含用户ID和用户名）
     * @param userId 用户ID
     * @return JWT令牌
     */
    //claims、生成时间、过期时间、令牌拥有者、签名。
    public String generateToken(Long userId) {
        Date now = new Date();
        Date expiration = new Date(now.getTime()+expire);

        Map<String,Long> claims = new HashMap<>();
        claims.put("userId", userId);

        return Jwts.builder()
                .setClaims(claims)
                .setSubject(userId.toString())
                .setIssuedAt(now)
                .setExpiration(expiration)
                .signWith(io.jsonwebtoken.security.Keys.hmacShaKeyFor(secret.getBytes()),SignatureAlgorithm.HS512)
                .compact();
    }
    /**
     * 解析JWT令牌
     * @param token JWT令牌
     * @return 令牌声明
     */
    //先解析令牌parsbuilder(),然后根据密钥解析token获得jwt对象，解析jwt对象获取body。
    public Claims parseToken(String token) {
        return Jwts.parserBuilder()
                .setSigningKey(io.jsonwebtoken.security.Keys.hmacShaKeyFor(secret.getBytes()))
                .build()
                .parseClaimsJws(token)
                .getBody();
    }

    /**
     * 从令牌中获取用户ID
     * @param token JWT令牌
     * @return 用户ID
     */
    public Long getUserIdFromToken(String token) {
        Claims claims = parseToken(token);
        Object userId = claims.get("userId");
        if (userId == null) {
            return null;
        }
        // 处理Integer和Long类型
        if (userId instanceof Integer) {
            return ((Integer) userId).longValue();
        }
        return (Long) userId;
    }


    /**
     * 从令牌中获取过期时间
     * @param token JWT令牌
     * @return 过期时间
     */
    public Date getExpirationDateFromToken(String token) {
        Claims claims = parseToken(token);
        return claims.getExpiration();
    }

    /**
     * 验证令牌是否有效
     * @param token JWT令牌
     * @return 是否有效
     */
    public Boolean validateToken(String token) {
        try {
            Claims claims = parseToken(token);
            // 检查用户名是否匹配且令牌未过期
            return !claims.getExpiration().before(new Date());
        } catch (Exception e) {
            // 解析失败说明令牌无效
            return false;
        }
    }

    /**
     * 检查令牌是否过期
     * @param token JWT令牌
     * @return 是否过期
     */
    public Boolean isTokenExpired(String token) {
        try {
            Date expiration = getExpirationDateFromToken(token);
            return expiration.before(new Date());
        } catch (Exception e) {
            return true;
        }
    }

    /**
     * 从Authorization头中获取令牌
     * @param authorization Authorization头
     * @return 令牌
     */
    public String getTokenFromAuthorization(String authorization) {
        if (authorization != null) {
            // 如果令牌前缀不为空且Authorization头以该前缀开头，则返回前缀后的内容
            if (tokenName != null && !tokenName.isEmpty() && authorization.startsWith(tokenName)) {
                return authorization.substring(tokenName.length()).trim();
            }
            // 否则直接返回Authorization头内容
            return authorization;
        }
        return null;
    }

    /**
     * 获取token的所有声明信息（调试用）
     * @param token JWT令牌
     * @return 所有声明
     */
    public Map<String, Object> getAllClaims(String token) {
        Claims claims = parseToken(token);
        Map<String, Object> result = new HashMap<>();
        result.put("userId", claims.get("userId"));
        result.put("username", claims.get("username"));
        result.put("subject", claims.getSubject());
        result.put("issuedAt", claims.getIssuedAt());
        result.put("expiration", claims.getExpiration());
        return result;
    }
}