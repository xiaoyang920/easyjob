package com.easyjob.agent.component;

import com.easyjob.entity.DocumentChunk;
import com.easyjob.exception.BusinessException;
import com.knuddels.jtokkit.Encodings;
import com.knuddels.jtokkit.api.Encoding;
import com.knuddels.jtokkit.api.EncodingType;
import org.jsoup.Jsoup;
import org.jsoup.nodes.Element;
import org.jsoup.nodes.Node;
import org.jsoup.nodes.TextNode;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;

/** DOM boundaries first; token budget only splits oversized semantic blocks. */
@Component
public class DocumentChunkService {
    public static final String VERSION = "html-dom-v1";
    public static final int TARGET_TOKENS = 500;
    public static final int MAX_TOKENS = 800;
    public static final int SHORT_TOKENS = 100;
    public static final int MAX_CHUNKS = 512;
    private static final Encoding TOKENS = Encodings.newLazyEncodingRegistry().getEncoding(EncodingType.CL100K_BASE);
    private static final Set<String> ATOMIC = Set.of("p", "pre", "ul", "ol", "table", "blockquote");
    private record Block(String text, String type, List<String> path) {}

    public List<DocumentChunk> chunk(String articleId, String title, String html, Long userId, List<String> tags) {
        if (html == null || html.isBlank()) throw new BusinessException("文章内容不能为空");
        Element body = Jsoup.parseBodyFragment(html).body();
        body.select("script,style,noscript,iframe,svg,canvas,[hidden],[aria-hidden=true]").remove();
        List<Block> blocks = new ArrayList<>();
        walk(body, new String[6], title, blocks);
        List<Block> pieces = new ArrayList<>();
        for (Block block : blocks) pieces.addAll(splitBlock(block));
        List<Block> packed = new ArrayList<>();
        boolean sectionBoundary = true;
        for (Block block : pieces) {
            if (block.type.equals("boundary")) { sectionBoundary = true; continue; }
            if (!sectionBoundary && !packed.isEmpty()) {
                Block previous = packed.getLast();
                String merged = previous.text + "\n\n" + block.text;
                boolean shortPrevious = tokenCount(previous.text) < SHORT_TOKENS;
                boolean explanationAfterCode = (previous.type.equals("code") || previous.type.equals("mixed"))
                        && previous.text.endsWith("```") && block.type.equals("paragraph") && tokenCount(block.text) < SHORT_TOKENS;
                if (previous.path.equals(block.path) && (shortPrevious || explanationAfterCode)
                        && embeddingTokens(block.path, merged) <= TARGET_TOKENS) {
                    packed.set(packed.size() - 1, new Block(merged, previous.type.equals(block.type) ? block.type : "mixed", block.path));
                    continue;
                }
            }
            packed.add(block);
            sectionBoundary = false;
        }
        // Image-only/empty editor HTML is valid blog content but has no text to embed.
        if (packed.isEmpty()) return List.of();
        if (packed.size() > MAX_CHUNKS) throw new BusinessException("文章超过分块数量上限，未截断正文，请拆分文章");
        String hash = sourceHash(html);
        List<DocumentChunk> chunks = new ArrayList<>();
        for (int i = 0; i < packed.size(); i++) {
            Block block = packed.get(i);
            DocumentChunk chunk = new DocumentChunk();
            chunk.setArticleId(articleId);
            chunk.setTitle(title);
            chunk.setUserId(userId);
            chunk.setTags(tags == null ? List.of() : tags);
            chunk.setContent(block.text);
            chunk.setSectionPath(block.path);
            chunk.setChunkType(block.type);
            chunk.setChunkIndex(i);
            chunk.setChunkCount(packed.size());
            chunk.setSourceHash(hash);
            chunk.setChunkerVersion(VERSION);
            chunks.add(chunk);
        }
        return chunks;
    }

    private static List<String> path(String title, String[] headings) {
        List<String> path = new ArrayList<>();
        if (title != null && !title.isBlank()) path.add(title.strip());
        for (String heading : headings) if (heading != null && !heading.isBlank()) path.add(heading);
        return List.copyOf(path);
    }

    private static void add(List<Block> blocks, String text, String type, String title, String[] headings) {
        if (!text.isBlank()) blocks.add(new Block(text.strip(), type, path(title, headings)));
    }

    private static void walk(Element container, String[] headings, String title, List<Block> blocks) {
        StringBuilder loose = new StringBuilder();
        for (Node node : container.childNodes()) {
            if (node instanceof TextNode text) {
                loose.append(text.getWholeText());
                continue;
            }
            if (!(node instanceof Element element)) continue;
            String tag = element.normalName();
            if (tag.equals("br")) { loose.append('\n'); continue; }
            if (!tag.matches("h[1-6]") && !ATOMIC.contains(tag) && !element.isBlock()) {
                loose.append(element.wholeText());
                continue;
            }
            add(blocks, normalize(loose.toString()), "paragraph", title, headings);
            loose.setLength(0);
            if (tag.matches("h[1-6]")) {
                int level = tag.charAt(1) - '1';
                headings[level] = normalize(element.wholeText());
                Arrays.fill(headings, level + 1, headings.length, null);
                blocks.add(new Block("", "boundary", path(title, headings)));
            } else if (tag.equals("pre")) {
                Element code = element.selectFirst("code");
                String language = "";
                if (code != null) for (String cls : code.classNames()) {
                    if (cls.matches("language-[a-zA-Z0-9_+.-]+")) language = cls.substring(9);
                }
                String text = (code == null ? element : code).wholeText().replace("\r\n", "\n");
                String fence = "```";
                while (text.contains(fence)) fence += "`";
                if (!text.isBlank()) add(blocks, fence + language + "\n" + text + "\n" + fence, "code", title, headings);
            } else if (tag.equals("ul") || tag.equals("ol")) {
                add(blocks, renderList(element, 0), "list", title, headings);
            } else if (tag.equals("table")) {
                add(blocks, renderTable(element), "table", title, headings);
            } else if (tag.equals("p")) {
                add(blocks, normalize(element.wholeText()), "paragraph", title, headings);
            } else {
                walk(element, headings, title, blocks);
            }
        }
        add(blocks, normalize(loose.toString()), "paragraph", title, headings);
    }

    private static String normalize(String text) {
        return text.replace('\u00a0', ' ').replaceAll("[\\t\\x0B\\f\\r ]+", " ").strip();
    }

    private static String renderList(Element list, int depth) {
        List<String> lines = new ArrayList<>();
        int number = 1;
        for (Element item : list.children()) {
            if (!item.normalName().equals("li")) continue;
            Element clone = item.clone();
            clone.select("ul,ol").remove();
            lines.add("  ".repeat(depth) + (list.normalName().equals("ol") ? number++ + ". " : "- ") + normalize(clone.wholeText()));
            for (Element child : item.select("ul,ol")) if (child.parent().closest("li") == item) {
                lines.add(renderList(child, depth + 1));
            }
        }
        return String.join("\n", lines);
    }

    private static String renderTable(Element table) {
        List<String> lines = new ArrayList<>();
        for (Element tr : table.select("tr")) {
            if (tr.closest("table") != table) continue;
            List<String> cells = tr.children().stream().filter(c -> c.normalName().equals("td") || c.normalName().equals("th"))
                    .map(c -> normalize(c.wholeText()).replace("\n", " ").replace("|", "\\|")).toList();
            if (cells.isEmpty()) continue;
            lines.add("| " + String.join(" | ", cells) + " |");
            if (lines.size() == 1 && !tr.select("th").isEmpty()) lines.add("| " + String.join(" | ", cells.stream().map(c -> "---").toList()) + " |");
        }
        return String.join("\n", lines);
    }

    private static List<Block> splitBlock(Block block) {
        if (block.type.equals("boundary")) return List.of(block);
        if (embeddingTokens(block.path, block.text) <= MAX_TOKENS) return List.of(block);
        int budget = MAX_TOKENS - tokenCount(String.join(" > ", block.path) + "\n\n") - 16;
        if (budget < 64) throw new BusinessException("标题层级过长，无法在分块预算中保留正文");
        String prefix = "", suffix = "", text = block.text;
        if (block.type.equals("code")) {
            int newline = text.indexOf('\n');
            prefix = text.substring(0, newline + 1);
            int closing = text.lastIndexOf('\n');
            suffix = text.substring(closing);
            text = text.substring(newline + 1, closing);
        } else if (block.type.equals("table")) {
            String[] rows = text.split("\n", 3);
            if (rows.length == 3 && rows[1].matches("[| \\-]+")) {
                prefix = rows[0] + "\n" + rows[1] + "\n";
                text = rows[2];
            }
        }
        budget -= tokenCount(prefix + suffix);
        if (budget < 32) throw new BusinessException("代码语言或表头超出分块预算");
        List<Block> result = new ArrayList<>();
        while (!text.isEmpty()) {
            int end = fittingEnd(text, budget);
            if (end < text.length()) {
                boolean linesOnly = !block.type.equals("paragraph");
                int boundary = -1;
                for (int i = 0; i < end; i++) {
                    char c = text.charAt(i);
                    if (c == '\n' || (!linesOnly && "。！？.!?；;".indexOf(c) >= 0)) boundary = i + 1;
                }
                if (boundary > 0) end = boundary;
            }
            String piece = text.substring(0, end);
            result.add(new Block(prefix + (block.type.equals("code") ? piece : piece.stripTrailing()) + suffix, block.type, block.path));
            text = text.substring(end);
            if (!block.type.equals("code")) text = text.stripLeading();
        }
        return result;
    }

    private static int fittingEnd(String text, int budget) {
        int total = text.codePointCount(0, text.length()), low = 1, high = total, best = 0;
        while (low <= high) {
            int mid = (low + high) >>> 1;
            int end = text.offsetByCodePoints(0, mid);
            if (tokenCount(text.substring(0, end)) <= budget) { best = end; low = mid + 1; }
            else high = mid - 1;
        }
        if (best == 0) throw new BusinessException("无法在分块预算中保留正文");
        return best;
    }

    public static int tokenCount(String text) { return TOKENS.countTokensOrdinary(text); }
    private static int embeddingTokens(List<String> path, String text) { return tokenCount(String.join(" > ", path) + "\n\n" + text); }
    public static String sourceHash(String content) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content.getBytes(StandardCharsets.UTF_8))); }
        catch (NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
}
