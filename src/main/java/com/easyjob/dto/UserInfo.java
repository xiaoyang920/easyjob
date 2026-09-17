package com.easyjob.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class UserInfo {
    private String userId;
    private String avatar;
    private String nickName;
    private String currentArticleId;
}
