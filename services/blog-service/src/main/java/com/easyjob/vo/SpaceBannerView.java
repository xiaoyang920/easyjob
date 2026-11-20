package com.easyjob.vo;

import com.easyjob.exception.BusinessException;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.Set;

public record SpaceBannerView(String ratio, int x, int y) {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Set<String> RATIOS = Set.of("16:9", "21:9", "3:2", "4:3");

    public static SpaceBannerView read(String json, int oldPosition) {
        if (json != null) {
            try {
                SpaceBannerView view = JSON.readValue(json, SpaceBannerView.class);
                if (view != null && view.valid()) return view;
            } catch (JsonProcessingException ignored) {
                // Keep legacy positioning if the stored view cannot be read.
            }
        }
        return new SpaceBannerView("16:9", 50, Math.clamp(oldPosition, 0, 100));
    }

    public String encode() {
        if (!valid()) throw new BusinessException("请选择支持的头图比例，位置须在 0 到 100 之间");
        try {
            return JSON.writeValueAsString(this);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("Could not encode banner view", error);
        }
    }

    private boolean valid() {
        return ratio != null && RATIOS.contains(ratio) && x >= 0 && x <= 100 && y >= 0 && y <= 100;
    }
}
