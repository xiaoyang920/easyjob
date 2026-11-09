package com.easyjob.service;

import com.easyjob.utils.HtmlContentSanitizer;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class HtmlContentSanitizerTests {
    @Test void retainsBoundedBlockDepthSeparatelyFromFirstLineIndent() {
        assertTrue(HtmlContentSanitizer.clean("<p style='line-height:1.625'>正文</p>",true).contains("line-height: 1.625;"));
        String cleaned = HtmlContentSanitizer.clean("<h3 style='margin-left:64px;text-indent:32px'>标题</h3><p style='margin-left:256px'>正文</p><p style='margin-left:-32px'>a</p><p style='margin-left:16px'>b</p><p style='margin-left:288px'>c</p><span style='margin-left:32px'>d</span><p style='margin-left:32px!important'>e</p>", true);
        assertTrue(cleaned.contains("margin-left: 64px; text-indent: 32px;"));
        assertTrue(cleaned.contains("margin-left: 256px;"));
        assertEquals(2, cleaned.split("margin-left", -1).length - 1);
        assertEquals(cleaned, HtmlContentSanitizer.clean(cleaned, true));
    }
    @Test void retainsOnlyBoundedFirstLineIndentStyles() {
        String html = "<p style='text-indent: 2em;'>正文</p><h2 style='text-indent:4em'>标题</h2><p style='text-indent:999em'>x</p><p style='text-indent:2em;background:url(https://evil.example/a)'>y</p><img src='/a.png' style='text-indent:2em'><p style='position:fixed'>z</p>";
        String cleaned = HtmlContentSanitizer.clean(html, true);
        assertTrue(cleaned.contains("style=\"text-indent: 32px;\""));
        assertTrue(cleaned.contains("style=\"text-indent: 64px;\""));
        assertFalse(cleaned.contains("999")); assertFalse(cleaned.contains("background"));
        assertFalse(cleaned.contains("position")); assertFalse(cleaned.contains("evil.example"));
        assertEquals(3, cleaned.split("style=", -1).length - 1);
        assertEquals(cleaned, HtmlContentSanitizer.clean(cleaned, true));
    }
    @Test void retainsToolbarFormattingButRejectsLayoutAndExternalResources() {
        String html = "<p style='text-indent:64px;line-height:2;text-align:center;position:fixed'><span style='font-size:32px;color:rgb(30, 60, 90);background-color:#ffeeaa;background-image:url(https://evil.example/x)'><strong><s>格式文字</s></strong></span></p>";
        String cleaned = HtmlContentSanitizer.clean(html, true);
        assertTrue(cleaned.contains("text-indent: 64px;")); assertTrue(cleaned.contains("line-height: 2;"));
        assertTrue(cleaned.contains("text-align: center;")); assertTrue(cleaned.contains("font-size: 32px;"));
        assertTrue(cleaned.contains("color: rgb(30, 60, 90);")); assertTrue(cleaned.contains("background-color: #ffeeaa;"));
        assertTrue(cleaned.contains("<strong><s>格式文字</s></strong>"));
        assertFalse(cleaned.contains("position")); assertFalse(cleaned.contains("background-image")); assertFalse(cleaned.contains("evil.example"));
        assertEquals(cleaned, HtmlContentSanitizer.clean(cleaned, true));
    }
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
    @Test void retainsClickableCitationSuperscriptsAndSourceTitlesWhenDraftsAreSaved() {
        String cleaned=HtmlContentSanitizer.clean("<p>正文<sup class='citation-ref'><a class='inline-citation' href='https://example.org/intro?a=1&amp;b=2' title='学校简介' target='_blank' rel='noopener noreferrer'>[1]</a></sup><sup><a href='/article/42' title='平台文章'>[2]</a></sup></p>",true);
        assertTrue(cleaned.contains("<sup><a "));
        assertTrue(cleaned.contains("href=\"https://example.org/intro?a=1&amp;b=2\""));
        assertTrue(cleaned.contains("title=\"学校简介\""));
        assertTrue(cleaned.contains("href=\"/article/42\""));
        assertTrue(cleaned.contains("[1]</a></sup>"));
    }
}
