package com.easyjob.vo;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class CommentActionVO {
    private Boolean hasLiked;
    private Boolean hasDisliked;
    private Integer likeCount;
}
