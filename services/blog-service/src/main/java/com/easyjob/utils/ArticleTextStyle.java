package com.easyjob.utils;

import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.regex.Matcher;

/** Bounded text formatting and document outline offsets. No arbitrary layout or URL CSS. */
public final class ArticleTextStyle {
    private ArticleTextStyle() {}
    private static final Set<String> BLOCKS = Set.of("p","h1","h2","h3","h4","h5","h6","blockquote","li","td","th");
    public static final Set<String> TAGS = Set.of("p","h1","h2","h3","h4","h5","h6","blockquote","li","td","th","span","strong","b","em","i","u","s","del","code");
    private static final Set<String> COLORS = Set.of("black","white","red","green","blue","yellow","gray","grey","orange","purple","transparent");
    private static final Pattern INDENT = Pattern.compile("^(\\d+)(px|em)?$");
    private static final Pattern RGB = Pattern.compile("^(rgb|rgba)\\(\\s*(\\d{1,3})\\s*,\\s*(\\d{1,3})\\s*,\\s*(\\d{1,3})(?:\\s*,\\s*(0(?:\\.\\d+)?|1(?:\\.0+)?))?\\s*\\)$");

    private static String indent(String value) {
        Matcher match = INDENT.matcher(value);
        if (!match.matches()) return "";
        try {
            long amount = Long.parseLong(match.group(1));
            if ("em".equals(match.group(2))) amount = Math.multiplyExact(amount, 16);
            if (match.group(2) == null && amount != 0) return "";
            return amount >= 0 && amount <= 256 && amount % 16 == 0 ? amount + "px" : "";
        } catch (ArithmeticException | NumberFormatException ignored) { return ""; }
    }
    private static boolean color(String value) {
        if (value.matches("^#(?:[\\da-f]{3}|[\\da-f]{4}|[\\da-f]{6}|[\\da-f]{8})$") || COLORS.contains(value)) return true;
        Matcher match = RGB.matcher(value);
        if (!match.matches()) return false;
        for (int group = 2; group <= 4; group++) if (Integer.parseInt(match.group(group)) > 255) return false;
        return "rgba".equals(match.group(1)) ? match.group(5) != null : match.group(5) == null;
    }
    public static String clean(String tag, String style) {
        tag = tag.toLowerCase(Locale.ROOT);
        if (!TAGS.contains(tag)) return "";
        LinkedHashMap<String, String> result = new LinkedHashMap<String,String>();
        for (String declaration : style.split(";")) {
            int separator = declaration.indexOf(':');
            if (separator < 0) continue;
            String name = declaration.substring(0, separator).trim().toLowerCase(Locale.ROOT);
            String value = declaration.substring(separator + 1).trim().toLowerCase(Locale.ROOT), allowed = "";
            if ("text-indent".equals(name) && BLOCKS.contains(tag)) allowed = indent(value);
            else if ("margin-left".equals(name) && tag.matches("^(p|h[1-6]|blockquote)$") && value.matches("^(?:0|32|64|96|128|160|192|224|256)px$")) allowed = value;
            else if ("font-size".equals(name) && value.matches("^(?:1\\d|[2-6]\\d|7[0-2])px$")) allowed = value;
            else if (("color".equals(name) || "background-color".equals(name)) && color(value)) allowed = value;
            else if ("line-height".equals(name) && BLOCKS.contains(tag) && value.matches("^(?:[12](?:\\.\\d{1,3})?|3(?:\\.0{1,3})?)$")) allowed = value;
            else if ("text-align".equals(name) && BLOCKS.contains(tag) && value.matches("^(left|right|center|justify)$")) allowed = value;
            if (!allowed.isEmpty()) result.put(name, allowed);
        }
        return result.entrySet().stream().map(entry -> entry.getKey() + ": " + entry.getValue() + ";").collect(Collectors.joining(" "));
    }
}
