package com.easyjob.vo;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.List;
import java.util.Map;

/** A designer-made decoration. Which images and settings it carries is defined by its slot in {@link DecorationSpec}. */
public record SpaceArtwork(String artworkId, String slot, String name, String artist, int version,
                           @JsonIgnore String assetsJson, @JsonIgnore String settingsJson) {
    public static final String PENDANT = "avatarPendant";
    public static final String CHAT_BUBBLE = "chatBubble";
    public static final String STICKER_PACK = "stickerPack";
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final TypeReference<Map<String, Object>> OBJECT_MAP = new TypeReference<>() {};

    /** The artwork a user currently wears in one slot. */
    public record Worn(Long userId, SpaceArtwork artwork) {}

    /**
     * Plain-map form for payloads serialised outside Jackson (the chat WebSocket uses fastjson),
     * so they carry exactly the public JSON shape.
     */
    public Map<String, Object> asPayload() {
        return JSON.convertValue(this, OBJECT_MAP);
    }

    /** Fixed images by contract key, plus the ordered items of the slot's list (for example the stickers of a pack). */
    public record Assets(Map<String, String> images, List<Item> items) {
        public record Item(String key, String name, String url) {}

        public String encode() {
            return write(this);
        }
    }

    public static boolean isId(String value) {
        return value != null && value.matches("art:[a-f0-9]{24}");
    }

    @JsonProperty("assets")
    public Assets assets() {
        try {
            Assets assets = JSON.readValue(assetsJson, Assets.class);
            return new Assets(assets.images() == null ? Map.of() : assets.images(),
                    assets.items() == null ? List.of() : assets.items());
        } catch (JsonProcessingException | IllegalArgumentException invalid) {
            throw new IllegalStateException("Invalid stored artwork assets " + artworkId, invalid);
        }
    }

    @JsonProperty("settings")
    public Map<String, Object> settings() {
        if (settingsJson == null) return Map.of();
        try {
            return JSON.readValue(settingsJson, OBJECT_MAP);
        } catch (JsonProcessingException invalid) {
            throw new IllegalStateException("Invalid stored artwork settings " + artworkId, invalid);
        }
    }

    public static String encodeSettings(Map<String, Object> settings) {
        return settings.isEmpty() ? null : write(settings);
    }

    private static String write(Object value) {
        try {
            return JSON.writeValueAsString(value);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("Could not encode artwork data", error);
        }
    }
}
