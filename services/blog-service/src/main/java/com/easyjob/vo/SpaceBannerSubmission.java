package com.easyjob.vo;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.LocalDateTime;

public record SpaceBannerSubmission(String reviewId, String userId, String nickname, String state,
                                    int position, String reason, LocalDateTime createdAt, @JsonIgnore String viewJson) {
    @JsonProperty("view")
    public SpaceBannerView view() {
        return SpaceBannerView.read(viewJson, position);
    }
}
