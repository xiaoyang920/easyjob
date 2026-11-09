# 文章推荐系统实现方案

## 一、建表

```sql
CREATE TABLE user_tag_preference (
    user_id BIGINT NOT NULL,
    tag_id BIGINT NOT NULL,
    score FLOAT NOT NULL DEFAULT 0,
    update_time DATETIME NOT NULL,
    PRIMARY KEY (user_id, tag_id),
    INDEX idx_user_score (user_id, score DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户标签偏好表';
```

## 二、实体类

**文件**：`src/main/java/com/easyjob/entity/UserTagPreference.java`

```java
package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

@Data
@TableName("user_tag_preference")
public class UserTagPreference {
    private Long userId;
    private Long tagId;
    private Float score;
    private LocalDateTime updateTime;
}
```

## 三、Mapper

**文件**：`src/main/java/com/easyjob/mapper/UserTagPreferenceMapper.java`

```java
package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.UserTagPreference;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;

@Mapper
public interface UserTagPreferenceMapper extends BaseMapper<UserTagPreference> {

    /**
     * 批量计算所有用户的标签偏好分（定时任务调用）
     * 先清空再插入，全量刷新
     */
    void refreshAllPreferences();

    /**
     * 获取用户 top N 偏好标签ID
     */
    List<Long> selectTopTagIds(@Param("userId") Long userId, @Param("limit") int limit);
}
```

**文件**：`src/main/resources/mapper/UserTagPreferenceMapper.xml`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE mapper PUBLIC "-//mybatis.org//DTD Mapper 3.0//EN"
        "http://mybatis.org/dtd/mybatis-3-mapper.dtd">
<mapper namespace="com.easyjob.mapper.UserTagPreferenceMapper">

    <!-- 全量刷新偏好分：先删后插 -->
    <update id="refreshAllPreferences">
        TRUNCATE TABLE user_tag_preference;

        INSERT INTO user_tag_preference (user_id, tag_id, score, update_time)
        SELECT
            ua.user_id,
            atr.tag_id,
            SUM(CASE ua.action_type
                WHEN 7 THEN 1
                WHEN 2 THEN 3
                WHEN 3 THEN 5
                WHEN 4 THEN 8
                WHEN 5 THEN 4
                ELSE 0
            END) AS score,
            NOW() AS update_time
        FROM user_action ua
        JOIN article_tag_relation atr ON ua.article_id = atr.article_id
        WHERE ua.action_time > DATE_SUB(NOW(), INTERVAL 30 DAY)
        GROUP BY ua.user_id, atr.tag_id
        HAVING score > 0
    </update>

    <!-- 获取用户 top N 偏好标签 -->
    <select id="selectTopTagIds" resultType="java.lang.Long">
        SELECT tag_id
        FROM user_tag_preference
        WHERE user_id = #{userId}
        ORDER BY score DESC
        LIMIT #{limit}
    </select>

</mapper>
```

## 四、定时任务（每天凌晨 2 点刷新偏好分）

**文件**：`src/main/java/com/easyjob/task/PreferenceRefreshTask.java`

```java
package com.easyjob.task;

import com.easyjob.mapper.UserTagPreferenceMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@Slf4j
public class PreferenceRefreshTask {

    @Autowired
    private UserTagPreferenceMapper preferenceMapper;

    /**
     * 每天凌晨 2 点全量刷新用户标签偏好
     */
    @Scheduled(cron = "0 0 2 * * ?")
    public void refreshPreferences() {
        log.info("开始刷新用户标签偏好...");
        long start = System.currentTimeMillis();
        preferenceMapper.refreshAllPreferences();
        log.info("用户标签偏好刷新完成，耗时 {}ms", System.currentTimeMillis() - start);
    }
}
```

**注意**：启动类需要加 `@EnableScheduling` 注解。

## 五、推荐 Service

**文件**：`src/main/java/com/easyjob/service/RecommendService.java`

```java
package com.easyjob.service;

import com.easyjob.vo.ArticleListVO;
import java.util.List;

public interface RecommendService {
    List<ArticleListVO> recommend(Long userId, int limit);
}
```

**文件**：`src/main/java/com/easyjob/service/impl/RecommendServiceImpl.java`

```java
package com.easyjob.service.impl;

import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.UserTagPreferenceMapper;
import com.easyjob.service.RecommendService;
import com.easyjob.vo.ArticleListVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@Slf4j
public class RecommendServiceImpl implements RecommendService {

    @Autowired
    private UserTagPreferenceMapper preferenceMapper;

    @Autowired
    private ArticleMapper articleMapper;

    @Override
    public List<ArticleListVO> recommend(Long userId, int limit) {
        // 1. 获取用户 top10 偏好标签
        List<Long> topTagIds = preferenceMapper.selectTopTagIds(userId, 10);

        if (topTagIds == null || topTagIds.isEmpty()) {
            // 冷启动：没有偏好数据，返回全站热门
            log.info("用户 {} 无偏好数据，返回热门文章", userId);
            return articleMapper.selectHotArticles(limit);
        }

        // 2. 根据偏好标签推荐文章（排除已浏览的）
        List<ArticleListVO> articles = articleMapper.selectRecommendArticles(
                userId, topTagIds, limit
        );

        // 3. 推荐结果不足，用热门文章补充
        if (articles.size() < limit) {
            List<Long> existIds = new java.util.ArrayList<>();
            for (ArticleListVO a : articles) {
                existIds.add(Long.parseLong(a.getArticleId()));
            }
            List<ArticleListVO> hotArticles = articleMapper.selectHotArticlesExclude(
                    existIds, limit - articles.size()
            );
            articles.addAll(hotArticles);
        }

        return articles;
    }
}
```

## 六、ArticleMapper 新增方法

**文件**：`src/main/java/com/easyjob/mapper/ArticleMapper.java` 新增

```java
/**
 * 根据偏好标签推荐文章（排除已浏览）
 */
List<ArticleListVO> selectRecommendArticles(
        @Param("userId") Long userId,
        @Param("tagIds") List<Long> tagIds,
        @Param("limit") int limit
);

/**
 * 热门文章（冷启动兜底）
 */
List<ArticleListVO> selectHotArticles(@Param("limit") int limit);

/**
 * 热门文章（排除指定ID）
 */
List<ArticleListVO> selectHotArticlesExclude(
        @Param("excludeIds") List<Long> excludeIds,
        @Param("limit") int limit
);
```

**文件**：`src/main/resources/mapper/ArticleMapper.xml` 新增

```xml
<!-- 根据偏好标签推荐文章 -->
<select id="selectRecommendArticles" resultType="com.easyjob.vo.ArticleListVO">
    SELECT
        a.article_id AS articleId,
        a.title,
        a.cover_image AS coverImage,
        a.summary,
        a.view_count AS viewCount,
        a.like_count AS likeCount,
        a.collect_count AS collectCount,
        a.publish_time AS publishTime,
        u.nick_name AS authorName,
        u.avatar AS authorAvatar
    FROM article_info a
    JOIN article_tag_relation atr ON a.article_id = atr.article_id
    JOIN user_info u ON a.user_id = u.user_id
    WHERE a.status = 1
      AND atr.tag_id IN
        <foreach collection="tagIds" item="tagId" open="(" separator="," close=")">
            #{tagId}
        </foreach>
      <!-- 排除已浏览的文章 -->
      AND a.article_id NOT IN (
          SELECT article_id FROM user_action
          WHERE user_id = #{userId} AND action_type = 7
      )
    GROUP BY a.article_id
    ORDER BY
        <!-- 综合排序：偏好匹配度 + 热度 + 时效 -->
        (a.like_count * 2 + a.collect_count * 3 + a.view_count) /
            (1 + DATEDIFF(NOW(), a.publish_time) * 0.1) DESC
    LIMIT #{limit}
</select>

<!-- 热门文章（冷启动） -->
<select id="selectHotArticles" resultType="com.easyjob.vo.ArticleListVO">
    SELECT
        a.article_id AS articleId,
        a.title,
        a.cover_image AS coverImage,
        a.summary,
        a.view_count AS viewCount,
        a.like_count AS likeCount,
        a.collect_count AS collectCount,
        a.publish_time AS publishTime,
        u.nick_name AS authorName,
        u.avatar AS authorAvatar
    FROM article_info a
    JOIN user_info u ON a.user_id = u.user_id
    WHERE a.status = 1
      AND a.publish_time > DATE_SUB(NOW(), INTERVAL 7 DAY)
    ORDER BY (a.like_count * 2 + a.collect_count * 3 + a.view_count) DESC
    LIMIT #{limit}
</select>

<!-- 热门文章（排除指定ID，用于补充） -->
<select id="selectHotArticlesExclude" resultType="com.easyjob.vo.ArticleListVO">
    SELECT
        a.article_id AS articleId,
        a.title,
        a.cover_image AS coverImage,
        a.summary,
        a.view_count AS viewCount,
        a.like_count AS likeCount,
        a.collect_count AS collectCount,
        a.publish_time AS publishTime,
        u.nick_name AS authorName,
        u.avatar AS authorAvatar
    FROM article_info a
    JOIN user_info u ON a.user_id = u.user_id
    WHERE a.status = 1
      <if test="excludeIds != null and excludeIds.size() > 0">
      AND a.article_id NOT IN
        <foreach collection="excludeIds" item="id" open="(" separator="," close=")">
            #{id}
        </foreach>
      </if>
    ORDER BY (a.like_count * 2 + a.collect_count * 3 + a.view_count) DESC
    LIMIT #{limit}
</select>
```

## 七、Controller

**文件**：`src/main/java/com/easyjob/controller/ArticleController.java` 新增

```java
@Autowired
private RecommendService recommendService;

/**
 * 获取推荐文章
 */
@GetMapping("/recommend")
public ResponseVO<?> recommend(
        @RequestParam(defaultValue = "20") Integer limit) {
    Long userId = UserContext.getUserId();
    List<ArticleListVO> articles = recommendService.recommend(userId, limit);
    return ResponseVO.success(articles);
}
```

## 八、冷启动：结合 Agent 用户画像

当 `user_tag_preference` 表没有数据时（新用户），可以从 `user_profile` 的 `tech_stack` 和 `interests` 字段匹配标签：

```java
// RecommendServiceImpl.recommend() 中，topTagIds 为空时
if (topTagIds == null || topTagIds.isEmpty()) {
    // 尝试从 user_profile 的 tech_stack 匹配标签
    UserProfile profile = userProfileMapper.selectById(userId);
    if (profile != null && profile.getTechStack() != null) {
        List<String> techStack = JSON.parseArray(profile.getTechStack(), String.class);
        if (techStack != null && !techStack.isEmpty()) {
            // 根据标签名模糊匹配 tag_id
            topTagIds = articleTagMapper.selectTagIdsByNames(techStack);
        }
    }
    // 还是空就返回热门
    if (topTagIds == null || topTagIds.isEmpty()) {
        return articleMapper.selectHotArticles(limit);
    }
}
```

`ArticleTagMapper` 新增：

```java
List<Long> selectTagIdsByNames(@Param("names") List<String> names);
```

```xml
<select id="selectTagIdsByNames" resultType="java.lang.Long">
    SELECT tag_id FROM article_tag
    WHERE tag_name IN
    <foreach collection="names" item="name" open="(" separator="," close=")">
        #{name}
    </foreach>
</select>
```

## 九、文件清单

| 操作 | 文件路径 |
|------|----------|
| 新建 | `entity/UserTagPreference.java` |
| 新建 | `mapper/UserTagPreferenceMapper.java` |
| 新建 | `resources/mapper/UserTagPreferenceMapper.xml` |
| 新建 | `task/PreferenceRefreshTask.java` |
| 新建 | `service/RecommendService.java` |
| 新建 | `service/impl/RecommendServiceImpl.java` |
| 修改 | `mapper/ArticleMapper.java`（新增 3 个方法） |
| 修改 | `resources/mapper/ArticleMapper.xml`（新增 3 个 SQL） |
| 修改 | `controller/ArticleController.java`（新增推荐接口） |
| 修改 | `mapper/ArticleTagMapper.java`（新增 selectTagIdsByNames） |
| 建表 | `user_tag_preference` |
