package com.easyjob.utils;

/**
 * 用户上下文工具类
 * 使用ThreadLocal存储当前请求的用户信息
 */
public class UserContext {

    /**
     * 存储用户ID的ThreadLocal
     */
    private static final ThreadLocal<Long> USER_ID_HOLDER = new ThreadLocal<>();


    /**
     * 设置当前用户ID
     * @param userId 用户ID
     */
    public static void setUserId(Long userId) {
        USER_ID_HOLDER.set(userId);
    }

    /**
     * 获取当前用户ID
     * @return 用户ID，如果未设置则返回null
     */
    public static Long getUserId() {
        return USER_ID_HOLDER.get();
    }


    /**
     * 检查是否已设置用户信息
     * @return true表示已设置，false表示未设置
     */
    public static boolean hasUser() {
        return USER_ID_HOLDER.get() != null;
    }

    public static void clear() {
        USER_ID_HOLDER.remove();
    }
}
