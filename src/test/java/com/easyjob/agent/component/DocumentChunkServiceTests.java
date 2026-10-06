package com.easyjob.agent.component;

import com.easyjob.entity.DocumentChunk;
import com.easyjob.exception.BusinessException;
import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.stream.Collectors;
import static org.junit.jupiter.api.Assertions.*;

class DocumentChunkServiceTests {
    private final DocumentChunkService service = new DocumentChunkService();
    private List<DocumentChunk> chunks(String html) { return service.chunk("42", "RAG", html, 7L, List.of("Java")); }
    private void bounded(List<DocumentChunk> chunks) {
        for (var chunk : chunks) assertTrue(DocumentChunkService.tokenCount(chunk.getEmbeddingText()) <= 800, chunk.getChunkId());
    }

    @Test void completeParagraphsKeepHeadingHierarchyAndDoNotDuplicateWrapperText() {
        String paragraph = "A meaningful paragraph with enough details. ".repeat(25);
        var result = chunks("<article><h1>检索</h1><div><h2>融合</h2><p>" + paragraph + "</p><p>" + paragraph + "</p></div>"
                + "<h1>生成</h1><p>独立章节</p><script>ignore this</script><p hidden>hidden</p></article>");
        assertEquals(3, result.size());
        assertEquals(List.of("RAG", "检索", "融合"), result.getFirst().getSectionPath());
        assertEquals(List.of("RAG", "生成"), result.getLast().getSectionPath());
        assertEquals(paragraph.strip(), result.getFirst().getContent());
        assertFalse(result.stream().anyMatch(c -> c.getContent().contains("ignore this") || c.getContent().contains("hidden")));
        bounded(result);
    }

    @Test void shortExplanationAndCodeStayTogetherWithoutLosingIndentOrEntities() {
        var result = chunks("<h2>Example</h2><p>下面是示例：</p><pre><code class='language-java'>if (a &lt; b) {\n    run();\n}\n</code></pre><p>输出结果。</p>");
        assertEquals(1, result.size());
        assertTrue(result.getFirst().getContent().contains("```java\nif (a < b) {\n    run();\n}"));
        assertTrue(result.getFirst().getContent().endsWith("输出结果。"));
        assertEquals("mixed", result.getFirst().getChunkType());
        bounded(result);
    }

    @Test void oversizedUnicodeParagraphSplitsAtSentencesWithoutDroppingText() {
        String body = "检索必须保留完整的事实与语义😀。".repeat(250);
        var result = chunks("<h2>原理</h2><p>" + body + "</p>");
        assertTrue(result.size() > 1);
        assertEquals(body, result.stream().map(DocumentChunk::getContent).collect(Collectors.joining()));
        assertTrue(result.stream().allMatch(c -> c.getContent().endsWith("。")));
        bounded(result);
    }

    @Test void oversizedCodeKeepsEveryLineAndUsesSafeFences() {
        String body = "    print('```nested fence```')\n".repeat(300);
        var result = chunks("<pre><code class='language-python'>" + body + "</code></pre>");
        assertTrue(result.size() > 1);
        String rebuilt = result.stream().map(c -> {
            String code = c.getContent();
            assertTrue(code.startsWith("````python\n"));
            assertTrue(code.endsWith("\n````"));
            return code.substring(code.indexOf('\n') + 1, code.lastIndexOf('\n'));
        }).collect(Collectors.joining());
        assertEquals(body, rebuilt);
        bounded(result);
    }

    @Test void longTableRepeatsHeaderAndKeepsEachRow() {
        StringBuilder html = new StringBuilder("<table><tr><th>Key</th><th>Value</th></tr>");
        for (int i = 0; i < 250; i++) html.append("<tr><td>key_").append(i).append("</td><td>value_").append(i).append("</td></tr>");
        var result = chunks(html.append("</table>").toString());
        assertTrue(result.size() > 1);
        assertTrue(result.stream().allMatch(c -> c.getContent().startsWith("| Key | Value |\n| --- | --- |")));
        String text = result.stream().map(DocumentChunk::getContent).collect(Collectors.joining("\n"));
        for (int i = 0; i < 250; i++) assertTrue(text.contains("| key_" + i + " | value_" + i + " |"));
        bounded(result);
    }

    @Test void nestedListSurvivesLayoutWrappers() {
        var result = chunks("<ol><li>first<div><ul><li>nested</li></ul></div></li><li>second</li></ol>");
        assertEquals("1. first\n  - nested\n2. second", result.getFirst().getContent());
    }

    @Test void repeatedHeadingNamesStillCreateDistinctSections() {
        var result = chunks("<h2>示例</h2><p>第一个示例。</p><h2>示例</h2><p>第二个示例。</p>");
        assertEquals(2, result.size());
        assertEquals("第一个示例。", result.getFirst().getContent());
        assertEquals("第二个示例。", result.getLast().getContent());
    }

    @Test void identitiesAreStableAndContentVersionChangesOnEdit() {
        var a = chunks("<p>正文😀</p>").getFirst();
        var b = chunks("<p>正文😀</p>").getFirst();
        var updated = chunks("<p>正文😀更新</p>").getFirst();
        assertEquals(a.getChunkId(), b.getChunkId());
        assertNotEquals(a.getChunkId(), updated.getChunkId());
        assertEquals("42_html-dom-v1_" + DocumentChunkService.sourceHash("<p>正文😀</p>") + "_0", a.getChunkId());
        assertEquals(a.getChunkId(), a.toEsDocument().get("chunk_id"));
        assertEquals(a.getSectionPath(), a.toEsDocument().get("section_path"));
        assertTrue(chunks("<script>only active content</script>").isEmpty());
        assertTrue(chunks("<p><br></p>").isEmpty());
        assertTrue(chunks("<p><img src='image.png'></p>").isEmpty());
    }
}
