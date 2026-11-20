package com.easyjob.vo;

import lombok.Data;

/** Public search result. Never return the account entity or private profile fields. */
@Data
public class UserSearchVO {
    private String userId;
    private String nickName;
    private String avatar;
    private String personIntroduction;
    private Integer articleCount;
    private Integer followerCount;
    private Boolean isFollowing;
}
