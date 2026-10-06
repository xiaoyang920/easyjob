package com.easyjob.utils;

import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.safety.Safelist;

/** One write policy for editor articles and generated drafts. */
public final class HtmlContentSanitizer {
    private HtmlContentSanitizer() {}

    public static String clean(String html, boolean images) {
        var allow = Safelist.relaxed().addTags("pre", "code", "thead", "tbody", "tfoot", "hr")
                .addAttributes("code", "class").addAttributes("pre", "class")
                .addAttributes("th", "colspan", "rowspan").addAttributes("td", "colspan", "rowspan")
                .addProtocols("a", "href", "http", "https", "mailto")
                .preserveRelativeLinks(true);
        if (!images) allow.removeTags("img");
        // Resolve relative upload URLs for protocol checking, then retain their relative form.
        return Jsoup.clean(html == null ? "" : html, "https://easyjob.invalid/", allow,
                new Document.OutputSettings().prettyPrint(false));
    }
}
