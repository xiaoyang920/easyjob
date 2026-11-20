package com.easyjob.vo;

import com.easyjob.exception.BusinessException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.InputStream;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Decoration slot registry shared with the frontend ({@code contracts/decoration-slots.json}).
 * A new artwork for an existing slot needs no code; a new slot needs a contract entry and one frontend renderer.
 */
public record DecorationSpec(Map<String, ImageRule> rules, Map<String, Slot> slots) {
    public static final String WEAR = "wear";
    public static final String COLLECT = "collect";
    private static final Set<String> FORMATS = Set.of("png", "webp", "gif");
    private static final Set<String> SETTING_TYPES = Set.of("slice", "color");
    public static final DecorationSpec SPEC = load();

    public record ImageRule(List<String> formats, boolean animated, boolean square, int minWidth, int maxWidth,
                            int minHeight, int maxHeight, int maxKiB, boolean transparency) {
        public String describe() {
            String size = square ? "边长 %d–%d 像素的正方形".formatted(minWidth, maxWidth)
                    : "宽 %d–%d、高 %d–%d 像素".formatted(minWidth, maxWidth, minHeight, maxHeight);
            return String.join("/", formats).toUpperCase() + (animated ? "（可动图）" : "（静态）") + "，" + size
                    + "，最大 " + maxKiB + " KB" + (transparency ? "，需要透明背景" : "");
        }
    }

    public record ImageField(String key, String label, String rule) {}

    public record ListField(String key, String label, int min, int max, int nameMaxLength, String rule) {}

    /** {@code slice} settings keep an edge of {@code image} unstretched along {@code axis}. */
    public record Setting(String key, String label, String type, String image, String axis) {}

    /** {@code hint} is shown to designers in the admin upload form; {@code layout} holds renderer constants. */
    public record Slot(String label, boolean ready, String usage, String hint, Map<String, Object> layout,
                       List<ImageField> images, ListField list, List<Setting> settings) {
        public boolean wearable() {
            return WEAR.equals(usage);
        }
    }

    /** A slot that accepts new artworks. */
    public Slot readySlot(String key) {
        Slot slot = key == null ? null : slots.get(key);
        if (slot == null || !slot.ready()) throw new BusinessException("装扮部位无效");
        return slot;
    }

    /** Upload rule for one fixed image or for the items of the slot's list. */
    public ImageRule imageRule(String slotKey, String assetKey) {
        Slot slot = readySlot(slotKey);
        String rule = slot.images().stream().filter(field -> field.key().equals(assetKey)).map(ImageField::rule)
                .findFirst().orElse(slot.list() != null && slot.list().key().equals(assetKey) ? slot.list().rule() : null);
        if (rule == null) throw new BusinessException("该部位没有这个图片位置");
        return rules.get(rule);
    }

    private static DecorationSpec load() {
        try (InputStream input = DecorationSpec.class.getResourceAsStream("/decoration-slots.json")) {
            if (input == null) throw new IllegalStateException("Missing decoration slot contract");
            DecorationSpec spec = new ObjectMapper().configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, true)
                    .readValue(input, DecorationSpec.class);
            spec.check();
            return spec;
        } catch (IOException error) {
            throw new ExceptionInInitializerError(error);
        }
    }

    /** Fails at startup when the contract is inconsistent, instead of at the first upload. */
    private void check() {
        rules.forEach((name, rule) -> require(!rule.formats().isEmpty() && FORMATS.containsAll(rule.formats())
                && rule.minWidth() >= 1 && rule.minWidth() <= rule.maxWidth() && rule.minHeight() >= 1
                && rule.minHeight() <= rule.maxHeight() && rule.maxKiB() >= 1
                && (!rule.square() || (rule.minWidth() == rule.minHeight() && rule.maxWidth() == rule.maxHeight()))
                && (rule.animated() || !rule.formats().contains("gif"))
                && !(rule.animated() && rule.transparency()), "rule " + name));
        slots.forEach((key, slot) -> {
            require(key.matches("[a-z][A-Za-z0-9]{0,19}") && slot.label() != null && !slot.label().isBlank()
                    && (WEAR.equals(slot.usage()) || COLLECT.equals(slot.usage())), "slot " + key);
            Set<String> keys = new HashSet<>();
            slot.images().forEach(field -> require(field.key().matches("[a-z][A-Za-z0-9]{0,19}") && keys.add(field.key())
                    && rules.containsKey(field.rule()), "image " + key + "." + field.key()));
            if (slot.list() != null) {
                ListField list = slot.list();
                require(keys.add(list.key()) && rules.containsKey(list.rule()) && list.min() >= 1 && list.min() <= list.max()
                        && list.max() <= 99 && list.nameMaxLength() >= 1, "list " + key);
            }
            require(!slot.images().isEmpty() || slot.list() != null, "slot " + key + " has no images");
            Set<String> settingKeys = new HashSet<>();
            slot.settings().forEach(setting -> require(settingKeys.add(setting.key()) && SETTING_TYPES.contains(setting.type())
                    && (!"slice".equals(setting.type()) || (keys.contains(setting.image())
                    && Set.of("vertical", "horizontal").contains(setting.axis()))), "setting " + key + "." + setting.key()));
        });
    }

    private static void require(boolean condition, String what) {
        if (!condition) throw new IllegalStateException("Invalid decoration contract: " + what);
    }
}
