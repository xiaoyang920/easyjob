"""Render evidence IDs at the delivery boundary; keep audited Markdown unchanged."""
import html
import re
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

REFERENCE = re.compile(r'\[((?:[a-z][a-z0-9_]*:)?(?:web)?\d+)\]')
SOURCE_LINE = re.compile(r'^(?:来源|依据|参考来源|Sources?)\s*[:：]\s*', re.I)
FOOTNOTE = re.compile(r'^\^\d+$')


def source_href(source):
    article_id = str(source.get('articleId') or '')
    if re.fullmatch(r'[1-9]\d*', article_id):
        return '/article/' + article_id
    url = source.get('url') or ''
    try:
        parsed = urlsplit(url)
        if (parsed.scheme in ('http', 'https') and parsed.hostname
                and not parsed.username and not parsed.password
                and not re.search(r'[\x00-\x20\x7f]', url)):
            return url
    except ValueError:
        pass
    return None


def render_cited_markdown(content, citations=(), *, show_citations=True):
    """Hide generated evidence markers only after verification, never in audit input.

    Code, explicit author links and ordinary footnotes are article content. Scoped
    evidence IDs remain recognizable when an old preview has lost its source map.
    """
    links = {source['id']: (index + 1, source_href(source), source.get('title') or '查看来源')
             for index, source in enumerate(citations) if source.get('id')}

    def hidden_reference(cid):
        return not show_citations and (cid in links or ':' in cid)

    def badge(cid):
        token = Token('html_inline', '', 0)
        token.meta['citation_id'] = cid
        if not show_citations:
            return token
        number, href, title = links[cid]
        token.content = ('<sup class="citation-ref"><a class="inline-citation" href="'
                         + html.escape(href, quote=True) + '" title="'
                         + html.escape(title, quote=True) + '" target="_blank" rel="noopener noreferrer">['
                         + str(number) + ']</a></sup>')
        return token

    def citation_rule(state, silent):
        match = REFERENCE.match(state.src, state.pos)
        if not match or not (hidden_reference(match[1]) or match[1] in links and links[match[1]][1]):
            return False
        # An author's explicit Markdown link keeps its own destination.
        if state.src[match.end():match.end() + 1] == '(' or state.linkLevel:
            return False
        if not silent:
            state.tokens.append(badge(match[1]))
        state.pos = match.end()
        return True

    md = MarkdownIt('commonmark', {'html': False}).enable('table')
    md.inline.ruler.before('link', 'evidence_citation', citation_rule)
    tokens = md.parse(content)
    output = []
    i = 0
    while i < len(tokens):
        if (i + 2 < len(tokens) and tokens[i].type == 'paragraph_open'
                and tokens[i + 1].type == 'inline' and tokens[i + 2].type == 'paragraph_close'):
            inline = tokens[i + 1]
            line = SOURCE_LINE.sub('', inline.content.strip())
            ids = REFERENCE.findall(line)
            if (SOURCE_LINE.match(inline.content.strip()) and ids
                    and not REFERENCE.sub('', line).strip(' \t\n。.;；、,，')
                    and all(hidden_reference(cid) or cid in links and links[cid][1] for cid in ids)):
                if len(output) >= 3 and [token.type for token in output[-3:]] == ['paragraph_open', 'inline', 'paragraph_close']:
                    previous = output[-2]
                    # Some models emit [^1] with a prose footnote definition. CommonMark
                    # mistakes that definition for a URL. Remove only these broken,
                    # redundant links when this very paragraph has real evidence IDs.
                    children = previous.children or []
                    clean = []
                    j = 0
                    while j < len(children):
                        if (j + 2 < len(children) and children[j].type == 'link_open'
                                and children[j + 1].type == 'text' and FOOTNOTE.fullmatch(children[j + 1].content)
                                and children[j + 2].type == 'link_close'
                                and not source_href({'url': children[j].attrGet('href')})):
                            j += 3
                            continue
                        clean.append(children[j])
                        j += 1
                    existing = {token.meta.get('citation_id') for token in clean}
                    clean.extend(badge(cid) for cid in dict.fromkeys(ids) if cid not in existing)
                    previous.children = clean
                elif show_citations:
                    inline.children = [badge(cid) for cid in dict.fromkeys(ids)]
                    output.extend(tokens[i:i + 3])
                i += 3
                continue
        output.append(tokens[i])
        i += 1
    return md.renderer.render(output, md.options, {})
