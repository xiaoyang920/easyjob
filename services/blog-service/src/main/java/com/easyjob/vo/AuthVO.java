package com.easyjob.vo;

import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
public class AuthVO {
    private String token;
    private String userId;
    private String email;
    private String nickName;
    private String avatar;
}
