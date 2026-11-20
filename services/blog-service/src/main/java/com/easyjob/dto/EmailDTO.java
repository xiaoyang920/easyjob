package com.easyjob.dto;

import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
public class EmailDTO {
    private String email;
    private String code;
}
