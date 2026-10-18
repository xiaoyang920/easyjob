package com.easyjob.dto;

import lombok.Data;

/** Text quote selector. Offsets use UTF-16 units, matching browser Range offsets. */
@Data
public class CommentQuote {
    private String exact;
    private String prefix;
    private String suffix;
    private Integer start;
    private Integer end;
    private String contentHash;
}
