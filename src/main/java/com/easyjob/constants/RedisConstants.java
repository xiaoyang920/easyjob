package com.easyjob.constants;

public class RedisConstants {
    // 时间（毫秒）
    public static final long CODE_EXPIRE_5MINUTE = 5 * 60 * 1000L;  // 5分钟
    public static final long CODE_EXPIRE_1MINUTE = 60 * 1000L;      // 1分钟
    public static final long CODE_EXPIRE_10MINUTE = 10 * 60 * 1000L; //10分钟
    public static final long CODE_EXPIRE_15SECOND = 15 * 1000L;     // 15秒
    public static final long CODE_EXPIRE_1HOUR = 60*60 * 1000L;
    public static final long CODE_EXPIRE_24HOUR = CODE_EXPIRE_1HOUR*24;
    public static final long CODE_EXPIRE_2HOUR = 2 * CODE_EXPIRE_1HOUR;  // 2小时
    // redis key 前缀
    public static final String REDIS_KEY_PREFIX = "easyjob:";
    public static final String REDIS_KEY_CHECK_CODE = REDIS_KEY_PREFIX + "checkCode:";
    public static final String REDIS_KEY_CHECK_TIME_CODE = REDIS_KEY_PREFIX + "checkTime:";
    public static final String REDIS_KEY_USER_SPACE_INFO = REDIS_KEY_PREFIX + "userSpaceInfo:";
    public static final String REDIS_KEY_ARTICLE_DETAIL = REDIS_KEY_PREFIX+"articleDetail:";
    public static final String REDIS_KEY_VIEW = REDIS_KEY_PREFIX+"articleView:";
    public static final String REDIS_KEY_CATEGORIES = REDIS_KEY_PREFIX+"categories:";
    public static final String REDIS_KEY_HOT_TAGS = REDIS_KEY_PREFIX+"hotTags:";
    public static final String REDIS_KEY_AI_CONV = REDIS_KEY_PREFIX + "aiConv:";
    // RedisConstants.java
    public static final String REDIS_KEY_AI_ARTICLE_CARDS = REDIS_KEY_PREFIX + "aiArticleCards:";


    public static final String REDIS_KEY_ARTICLE_VIEW = REDIS_KEY_PREFIX+"viewHistory";
}
