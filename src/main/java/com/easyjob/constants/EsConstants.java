package com.easyjob.constants;

public class EsConstants {
    public static final String LEGACY_MAPPING_TEMPLATE = "{\n" +
            "  \"properties\": {\n" +
            "    \"articleId\": {\n" +
            "      \"type\": \"long\"\n" +
            "    },\n" +
            "    \"userId\": {\n" +
            "      \"type\": \"long\"\n" +
            "    },\n" +
            "    \"title\": {\n" +
            "      \"type\": \"text\",\n" +
            "      \"analyzer\": \"ik_max_word\",\n" +
            "      \"search_analyzer\": \"ik_smart\",\n" +
            "      \"fields\": {\n" +
            "        \"keyword\": {\n" +
            "          \"type\": \"keyword\",\n" +
            "          \"ignore_above\": 256\n" +
            "        }\n" +
            "      }\n" +
            "    },\n" +
            "    \"coverImage\": {\n" +
            "      \"type\": \"keyword\",\n" +
            "      \"index\": false\n" +
            "    },\n" +
            "    \"summary\": {\n" +
            "      \"type\": \"text\",\n" +
            "      \"analyzer\": \"ik_max_word\",\n" +
            "      \"search_analyzer\": \"ik_smart\"\n" +
            "    },\n" +
            "    \"content\": {\n" +
            "      \"type\": \"text\",\n" +
            "      \"analyzer\": \"ik_max_word\",\n" +
            "      \"search_analyzer\": \"ik_smart\"\n" +
            "    },\n" +
            "    \"contentType\": {\n" +
            "      \"type\": \"byte\"\n" +
            "    },\n" +
            "    \"categoryId\": {\n" +
            "      \"type\": \"long\"\n" +
            "    },\n" +
            "    \"tags\": {\n" +
            "      \"type\": \"text\",\n" +
            "      \"analyzer\": \"comma\",\n" +
            "      \"fields\": {\n" +
            "        \"keyword\": {\n" +
            "          \"type\": \"keyword\"\n" +
            "        }\n" +
            "      }\n" +
            "    },\n" +
            "    \"viewCount\": {\n" +
            "      \"type\": \"integer\"\n" +
            "    },\n" +
            "    \"likeCount\": {\n" +
            "      \"type\": \"integer\"\n" +
            "    },\n" +
            "    \"collectCount\": {\n" +
            "      \"type\": \"integer\"\n" +
            "    },\n" +
            "    \"commentCount\": {\n" +
            "      \"type\": \"integer\"\n" +
            "    },\n" +
            "    \"shareCount\": {\n" +
            "      \"type\": \"integer\"\n" +
            "    },\n" +
            "    \"status\": {\n" +
            "      \"type\": \"byte\"\n" +
            "    },\n" +
            "    \"isTop\": {\n" +
            "      \"type\": \"byte\"\n" +
            "    },\n" +
            "    \"isEssence\": {\n" +
            "      \"type\": \"byte\"\n" +
            "    },\n" +
            "    \"isOriginal\": {\n" +
            "      \"type\": \"byte\"\n" +
            "    },\n" +
            "    \"publishTime\": {\n" +
            "      \"type\": \"date\",\n" +
            "      \"format\": \"yyyy-MM-dd HH:mm:ss||yyyy-MM-dd||epoch_millis\"\n" +
            "    },\n" +
            "    \"createTime\": {\n" +
            "      \"type\": \"date\",\n" +
            "      \"format\": \"yyyy-MM-dd HH:mm:ss||yyyy-MM-dd||epoch_millis\"\n" +
            "    },\n" +
            "    \"updateTime\": {\n" +
            "      \"type\": \"date\",\n" +
            "      \"format\": \"yyyy-MM-dd HH:mm:ss||yyyy-MM-dd||epoch_millis\"\n" +
            "    }\n" +
            "  }\n" +
            "}";
    public static final String LEGACY_INDEX_SETTING = "{\n" +
            "  \"analysis\": {\n" +
            "    \"analyzer\": {\n" +
            "      \"comma\": {\n" +
            "        \"type\": \"pattern\",\n" +
            "        \"pattern\": \",\"\n" +
            "      },\n" +
            "      \"ik_smart_pinyin\": {\n" +
            "        \"type\": \"custom\",\n" +
            "        \"tokenizer\": \"ik_smart\"\n" +
            "      }\n" +
            "    }\n" +
            "  }\n" +
            "}";
    public static final String MAPPING_TEMPLATE=ChineseSearchSchema.mapping(LEGACY_MAPPING_TEMPLATE,"title","summary","content");
    public static final String INDEX_SETTING=ChineseSearchSchema.settings(LEGACY_INDEX_SETTING);
}
