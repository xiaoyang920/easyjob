package com.easyjob.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class ShareDTO {
    Long articleId;
    Long commentId;
    Integer shareType;//0-复制链接 1-二维码 2-海报
}
