package com.easyjob.service;

import com.easyjob.dto.CommentQuote;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleCommentAnchorMapper;
import com.easyjob.vo.ArticleCommentVO;
import lombok.RequiredArgsConstructor;
import org.jsoup.Jsoup;
import org.jsoup.nodes.Element;
import org.jsoup.nodes.Node;
import org.jsoup.nodes.TextNode;
import org.springframework.stereotype.Service;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.*;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.easyjob.entity.Article;
import com.easyjob.entity.ArticleComment;

@Service
@RequiredArgsConstructor
public class ArticleCommentAnchorService {
    private final ArticleCommentAnchorMapper store;
    private static final Set<String> BLOCKS = Set.of("p","div","section","article","h1","h2","h3","h4","h5","h6",
            "li","ul","ol","pre","blockquote","table","tr","td","th","hr","br","figure","figcaption");
    private static final Set<String> SKIP = Set.of("script","style","button","svg","noscript","template");
    // Exactly the same whitespace set and block boundaries as commentAnchors.ts.
    private static final String SPACE = "[\\t\\n\\x0B\\f\\r \\u00A0\\u1680\\u2000-\\u200A\\u2028\\u2029\\u202F\\u205F\\u3000\\uFEFF]+";

    public static String articleText(String html) {
        var output = new StringBuilder();
        append(Jsoup.parseBodyFragment(html == null ? "" : html).body(), output);
        return output.toString().replaceAll(SPACE," ").trim();
    }
    private static void append(Node node, StringBuilder output) {
        if (node instanceof TextNode text) { output.append(text.getWholeText()); return; }
        if (node instanceof Element element) {
            if (SKIP.contains(element.normalName()) || element.hasAttr("data-annotation-ignore")
                    || element.hasClass("article-code-toolbar")) return;
            boolean block = BLOCKS.contains(element.normalName());
            if(block) output.append(' ');
            for(var child:node.childNodes()) append(child,output);
            if(block) output.append(' ');
        } else for(var child:node.childNodes()) append(child,output);
    }

    /** Validate against the live published body; never trust client quote or hash. */
    public CommentQuote validate(CommentQuote input, String html) {
        if (input == null) return null;
        if (input.getExact() == null || input.getExact().isBlank() || input.getExact().length() > 1000
                || input.getPrefix() == null || input.getSuffix() == null
                || input.getPrefix().length() > 48 || input.getSuffix().length() > 48
                || input.getStart() == null || input.getEnd() == null || input.getStart() < 0
                || input.getEnd() < input.getStart()
                || input.getEnd() - input.getStart() != input.getExact().length())
            throw new BusinessException(400,"引用片段无效，请重新选择正文（最多1000字）");
        String text = articleText(html);
        int start = input.getStart(), end = input.getEnd();
        if (end > text.length() || !text.substring(start,end).equals(input.getExact())
                || !text.substring(0,start).endsWith(input.getPrefix()) || !text.substring(end).startsWith(input.getSuffix()))
            throw new BusinessException(409,"文章内容已更新，请刷新后重新选择原文");
        var quote = new CommentQuote();
        quote.setExact(text.substring(start,end)); quote.setStart(start); quote.setEnd(end);
        int prefixStart = Math.max(0,start-48), suffixEnd = Math.min(text.length(),end+48);
        if(prefixStart > 0 && Character.isLowSurrogate(text.charAt(prefixStart))) prefixStart++;
        if(suffixEnd > end && Character.isHighSurrogate(text.charAt(suffixEnd-1))) suffixEnd--;
        quote.setPrefix(text.substring(prefixStart,start));
        quote.setSuffix(text.substring(end,suffixEnd));
        try { quote.setContentHash(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)))); }
        catch(NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
        return quote;
    }
    public void save(Long commentId, CommentQuote quote) {
        if(quote != null) store.insert(commentId, quote);
    }
    public Article lockArticle(Long articleId) { return store.lockArticle(articleId); }
    public IPage<ArticleComment> page(Long articleId, int page, int size) {
        return store.findComments(new Page<>(page,size),articleId);
    }
    public IPage<ArticleComment> selectedPage(Long articleId,int page,int size,List<Long> ids) {
        return store.findSelectedComments(new Page<>(page,size),articleId,ids);
    }
    public record Marker(String commentId,CommentQuote quote) {}
    public Map<String,Object> markers(Long articleId,Long afterId,int size) {
        var rows=store.findMarkers(articleId,afterId,size+1);
        boolean more=rows.size()>size;
        var selected=rows.stream().limit(size).toList();
        var records=selected.stream().map(row->new Marker(row.getCommentId().toString(),row)).toList();
        return Map.of("records",records,"nextCursor",more?selected.getLast().getCommentId().toString():"");
    }
    public void attach(List<ArticleCommentVO> comments) {
        if(comments.isEmpty()) return;
        var byId = new HashMap<Long,ArticleCommentVO>();
        comments.forEach(c -> byId.put(Long.valueOf(c.getCommentId()),c));
        store.findByComments(new ArrayList<>(byId.keySet())).forEach(anchor -> {
            var comment = byId.get(anchor.getCommentId());
            if(comment != null) comment.setQuote(anchor);
        });
    }
}
