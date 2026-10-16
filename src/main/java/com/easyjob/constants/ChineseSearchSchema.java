package com.easyjob.constants;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.util.List;

/** Additive multi-fields: old mappings, source content, chunk IDs and vectors stay compatible. */
public final class ChineseSearchSchema {
    private static final ObjectMapper JSON = new ObjectMapper();
    public static final String INDEX_ANALYZER = "easyjob_zh_index";
    public static final String SEARCH_ANALYZER = "easyjob_zh_search";
    public static final List<String> ARTICLE_FIELDS = List.of(
            "title.zh^4", "tags", "summary.zh^2", "content.zh^0.5", "title^0.4");

    private ChineseSearchSchema() {}

    public static String settings(String legacy) {
        try (var input = ChineseSearchSchema.class.getResourceAsStream("/elasticsearch/chinese-analysis.json")) {
            if (input == null) {
                throw new IllegalStateException("Missing Chinese search analysis resource");
            }
            ObjectNode result = (ObjectNode) JSON.readTree(legacy);
            ObjectNode supplied = (ObjectNode) JSON.readTree(input);
            ObjectNode analysis = result.withObject("analysis");
            supplied.path("analysis").fields().forEachRemaining(group -> {
                ObjectNode target = analysis.withObject(group.getKey());
                group.getValue().fields().forEachRemaining(entry -> target.set(entry.getKey(), entry.getValue()));
            });
            return JSON.writeValueAsString(result);
        } catch (Exception error) {
            throw new IllegalStateException("Invalid Chinese search analysis settings", error);
        }
    }

    public static String mapping(String legacy, String... fields) {
        try {
            ObjectNode result = (ObjectNode) JSON.readTree(legacy);
            ObjectNode properties = result.withObject("properties");
            for (String field : fields) {
                ObjectNode original = (ObjectNode) properties.get(field);
                if (original == null || !"text".equals(original.path("type").asText())) {
                    throw new IllegalStateException("Expected text field: " + field);
                }
                original.withObject("fields").putObject("zh").put("type", "text")
                        .put("analyzer", INDEX_ANALYZER).put("search_analyzer", SEARCH_ANALYZER);
            }
            return JSON.writeValueAsString(result);
        } catch (Exception error) {
            throw new IllegalStateException("Invalid Chinese search mapping", error);
        }
    }
}
