package com.easyjob.service;

import com.easyjob.utils.HtmlContentSanitizer;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class HtmlContentSanitizerTests {
    @Test void stripsExecutableMarkupAndJavascriptProtocols() {
        String cleaned = HtmlContentSanitizer.clean("<script>alert(1)</script><img src='/uploads/a.png' onerror='alert(2)'><a href='javascript:alert(3)'>x</a><iframe src='https://example.com'></iframe><p style='background:url(javascript:x)' onclick='x'>text</p>", true);
        assertFalse(cleaned.contains("script")); assertFalse(cleaned.contains("onerror"));
        assertFalse(cleaned.contains("iframe")); assertFalse(cleaned.contains("onclick"));
        assertFalse(cleaned.contains("style=")); assertTrue(cleaned.contains("src=\"/uploads/a.png\""));
    }
    @Test void retainsCodeTablesAndNormalLinksButDraftsCannotEmbedImages() {
        String html = "<pre><code class='language-java'>a &lt; b</code></pre><table><tbody><tr><td colspan='2'>cell</td></tr></tbody></table><a href='https://example.org'>source</a><img src='/uploads/x.jpg'>";
        String article = HtmlContentSanitizer.clean(html, true);
        assertTrue(article.contains("language-java")); assertTrue(article.contains("colspan=\"2\""));
        assertTrue(article.contains("href=\"https://example.org\""));
        assertFalse(HtmlContentSanitizer.clean(html, false).contains("<img"));
    }
}
