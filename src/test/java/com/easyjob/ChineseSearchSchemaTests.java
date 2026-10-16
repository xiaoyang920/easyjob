package com.easyjob;

import com.easyjob.constants.AgentEsConstants;
import com.easyjob.constants.ChineseSearchSchema;
import com.easyjob.constants.EsConstants;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import java.util.Properties;
import static org.junit.jupiter.api.Assertions.*;

class ChineseSearchSchemaTests {
    private final ObjectMapper json = new ObjectMapper();

    @Test void articleMappingPreservesLegacyFieldsAndAddsChineseSearch() throws Exception {
        JsonNode old = json.readTree(EsConstants.LEGACY_MAPPING_TEMPLATE).path("properties");
        JsonNode current = json.readTree(EsConstants.MAPPING_TEMPLATE).path("properties");
        assertEquals(old.path("title").path("fields").path("keyword"), current.path("title").path("fields").path("keyword"));
        assertEquals(old.path("articleId"), current.path("articleId"));
        assertEquals(old.path("tags"), current.path("tags"));
        for (String field : new String[]{"title", "summary", "content"}) {
            assertEquals("easyjob_zh_search", current.path(field).at("/fields/zh/search_analyzer").asText());
            assertEquals(old.path(field).path("analyzer"), current.path(field).path("analyzer"));
        }
    }

    @Test void vectorSchemaKeepsIdentityVectorDimensionsAndChunkMetadata() throws Exception {
        JsonNode old = json.readTree(AgentEsConstants.LEGACY_VECTOR_INDEX_MAPPING).path("properties");
        JsonNode current = json.readTree(AgentEsConstants.VECTOR_INDEX_MAPPING).path("properties");
        for (String field : new String[]{"content_vector", "chunk_id", "article_id", "chunk_index", "tags"}) {
            assertEquals(old.path(field), current.path(field));
        }
        for (String field : new String[]{"title", "chunk_content", "section_path"}) {
            assertEquals("easyjob_zh_index", current.path(field).at("/fields/zh/analyzer").asText());
        }
        assertTrue(ChineseSearchSchema.ARTICLE_FIELDS.contains("title.zh^4"));
    }

    @Test void settingsKeepCommaAnalyzerAndApplySynonymsOnlyAtSearchTime() throws Exception {
        JsonNode analysis = json.readTree(EsConstants.INDEX_SETTING).path("analysis");
        assertEquals("pattern", analysis.at("/analyzer/comma/type").asText());
        assertFalse(analysis.at("/analyzer/easyjob_zh_index/filter").toString().contains("synonyms"));
        assertTrue(analysis.at("/analyzer/easyjob_zh_search/filter").toString().contains("synonyms"));
        assertTrue(analysis.at("/filter/easyjob_technical_synonyms/updateable").asBoolean());
        assertEquals(1, json.readTree(AgentEsConstants.VECTOR_INDEX_SETTINGS).path("number_of_shards").asInt());
    }

    @Test void ikTemplateCanBeReadByJavaProperties() throws Exception {
        Properties properties = new Properties();
        try (var stream = getClass().getResourceAsStream("/elasticsearch/IKAnalyzer.cfg.xml")) {
            assertNotNull(stream);
            properties.loadFromXML(stream);
        }
        assertEquals("custom/easyjob-technical.dic", properties.getProperty("ext_dict"));
    }
}
