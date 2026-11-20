package com.easyjob.utils;

import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.safety.Safelist;
import org.jsoup.nodes.Element;

/** One write policy for editor articles and generated drafts. */
public final class HtmlContentSanitizer {
    private HtmlContentSanitizer() {}

    public static String clean(String html, boolean images) {
        Safelist allow = Safelist.relaxed().addTags("pre", "code", "thead", "tbody", "tfoot", "hr", "s", "del")
                .addAttributes("code", "class").addAttributes("pre", "class")
                .addAttributes("th", "colspan", "rowspan").addAttributes("td", "colspan", "rowspan")
                .addProtocols("a", "href", "http", "https", "mailto")
                .preserveRelativeLinks(true);
        if (!images) allow.removeTags("img");
        Document document = Jsoup.parseBodyFragment(html == null ? "" : html, "https://easyjob.invalid/");
        // Retain only bounded toolbar presentation. Never allow arbitrary CSS.
        for (Element element : document.getAllElements()) {
            if (!element.hasAttr("style")) continue;
            String style = ArticleTextStyle.clean(element.normalName(), element.attr("style"));
            if (!style.isEmpty()) element.attr("style", style);
            else element.removeAttr("style");
        }
        for (String tag : ArticleTextStyle.TAGS) allow.addAttributes(tag, "style");
        // Resolve relative upload URLs for protocol checking, then retain their relative form.
        document.outputSettings().prettyPrint(false);
        return Jsoup.clean(document.body().html(), "https://easyjob.invalid/", allow,
                new Document.OutputSettings().prettyPrint(false));
    }
}
