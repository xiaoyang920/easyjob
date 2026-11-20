package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@TableName("user_tag_preference")
@Data
public class UserTagPreference {
    private Long userId;
    private Long tagId;
    private Float score;
    private LocalDateTime updateTime;
}
