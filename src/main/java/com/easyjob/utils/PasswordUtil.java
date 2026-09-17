package com.easyjob.utils;

import com.easyjob.exception.BusinessException;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

//使用Bcrypt对密码进行加密
public class PasswordUtil {
    private static final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();
    /**
     * 对密码进行加密
     * @param password 密码
     * @return 加密后的密码
     */
    public static String encode(String password) {
       if(password==null||password.isEmpty()){
           throw new BusinessException("密码不能为空");
       }
       return encoder.encode(password);
    }
    /**
     * 对密码进行验证
     * @param rawPassword 未加密的密码
     * @param encodedPassword 已加密的密码
     * @return 验证结果
     */
    public static boolean matches(String rawPassword, String encodedPassword) {
        if(rawPassword==null||encodedPassword== null){
            return false;
        }
        return encoder.matches(rawPassword, encodedPassword);
    }
    /**
     * 判断密码是否已加密
     * @param password 密码
     * @return 是否已加密
     */
    public static boolean isEncoded(String password){
        if(password==null||password.isEmpty()){
            return false;
        }
        return password.startsWith("$2a$") || password.startsWith("$2b$") || password.startsWith("$2y$");
    }
}
