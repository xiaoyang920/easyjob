package com.easyjob.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class CommentActionDTO {
    private Integer actionType;
    private Long articleId;
    private Long articleUserId;
}
