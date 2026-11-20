import unittest
from types import SimpleNamespace

from app.services.draft_gateway import render_draft, draft_hash
from app.services.draft_citations import source_href, render_cited_markdown

SOURCES = [
    {'id': 'research:web7', 'url': 'https://www.example.org/intro?a=1&b=2', 'title': '学校简介'},
    {'id': 'research:2', 'articleId': '42', 'title': '平台文章'},
]


class DraftCitationTests(unittest.TestCase):
    def draft(self, content):
        return SimpleNamespace(title='标题', summary='摘要', content=content)

    def test_known_ids_become_clickable_superscripts_without_mutating_audited_markdown(self):
        draft = self.draft('学校介绍[research:web7]，平台资料[research:2]。')
        html = render_cited_markdown(draft.content, SOURCES)
        self.assertIn('<sup class="citation-ref">', html)
        self.assertIn('href="https://www.example.org/intro?a=1&amp;b=2"', html)
        self.assertIn('title="学校简介"', html)
        self.assertIn('href="/article/42"', html)
        self.assertIn('>[1]</a>', html)
        self.assertIn('>[2]</a>', html)
        self.assertIn('[research:web7]', draft.content)
        self.assertNotIn('research:', html)
        self.assertEqual(draft_hash(draft, html), draft_hash(draft, render_cited_markdown(draft.content, SOURCES)))

    def test_grounding_source_paragraph_folds_into_prose_and_discards_only_broken_redundant_footnote(self):
        draft = self.draft('介绍学校[^1]。\n\n来源：[research:web7][research:2]\n\n[^1]: 这是一段摘要，不是网址。')
        html = render_cited_markdown(draft.content, SOURCES)
        self.assertEqual(html.count('<p>'), 1)
        self.assertNotIn('^1', html)
        self.assertNotIn('来源：', html)
        self.assertEqual(html.count('class="inline-citation"'), 2)
        self.assertIn('介绍学校。', html)

    def test_code_and_explicit_links_and_inherited_valid_footnotes_remain(self):
        content = '`[research:web7]`\n\n~~~text\n[research:web7]\n~~~\n\n[research:web7](https://other.example.org)\n\n普通脚注[^1]。\n\n[^1]: https://example.org/note'
        html = render_draft(self.draft(content), SOURCES)
        self.assertIn('<code>[research:web7]</code>', html)
        self.assertIn('href="https://other.example.org"', html)
        self.assertIn('href="https://example.org/note"', html)
        self.assertNotIn('class="inline-citation"', html)

    def test_source_paragraph_cannot_jump_back_across_code_or_heading(self):
        html = render_cited_markdown('第一段。\n\n```java\nint n = 1;\n```\n\n来源：[research:web7]', SOURCES)
        self.assertIn('<p>第一段。</p>', html)
        self.assertIn('</pre>\n<p><sup', html)

    def test_unsafe_or_missing_source_is_never_given_an_invented_link(self):
        for url in ('javascript:alert(1)', '//example.org', 'https://user:password@example.org', 'https://example.org/\nwrong'):
            self.assertIsNone(source_href({'url': url}))
        html = render_cited_markdown('正文[unknown:web1]。', SOURCES)
        self.assertIn('[unknown:web1]', html)
        self.assertNotIn('<a ', html)

    def test_titles_and_urls_are_escaped_and_manual_html_is_preserved(self):
        html = render_cited_markdown('正文[x:web1]', [{'id': 'x:web1', 'url': 'https://example.org/?q="x"', 'title': '"><img src=x onerror=1>'}])
        self.assertNotIn('<img', html)
        self.assertIn('&lt;img', html)
        manual = SimpleNamespace(content='<p>用户正文<sup>2</sup></p>', content_format='html')
        self.assertEqual(render_draft(manual, SOURCES), manual.content)

    def test_saved_article_has_no_system_markers_but_audited_draft_and_hash_keep_them(self):
        draft = self.draft('[research:web7]学校介绍[research:2]。\n\n来源：[research:web7][research:2]')
        original = draft.content
        rendered = render_draft(draft, SOURCES)
        self.assertEqual(rendered, '<p>学校介绍。</p>\n')
        self.assertEqual(draft.content, original)
        self.assertEqual(draft_hash(draft, rendered), draft_hash(draft, render_draft(draft, SOURCES)))
        self.assertNotEqual(draft_hash(draft, rendered), draft_hash(self.draft('学校介绍。'), rendered))

    def test_hidden_evidence_does_not_leave_source_paragraphs_or_broken_footnotes(self):
        draft = self.draft('介绍[^1]。\n\n来源：[research:web7]\n\n[^1]: 一段摘要\n\n## 标题\n\n来源：[research:2]')
        self.assertEqual(render_draft(draft, SOURCES), '<p>介绍。</p>\n<h2>标题</h2>\n')

    def test_draft_keeps_code_author_links_and_unrelated_numeric_text(self):
        draft = self.draft('正文[research:web7]。\n\n`[research:web7]` 与数组[1]。\n\n```text\n[research:2]\n```\n\n[research:web7](https://other.example.org)\n\n[1](https://example.org/note)')
        rendered = render_draft(draft, SOURCES)
        self.assertIn('<p>正文。</p>', rendered)
        self.assertIn('<code>[research:web7]</code> 与数组[1]', rendered)
        self.assertIn('<pre><code class="language-text">[research:2]', rendered)
        self.assertIn('href="https://other.example.org"', rendered)
        self.assertIn('href="https://example.org/note">1</a>', rendered)

    def test_known_numeric_and_scoped_ids_hide_without_inventing_source_links(self):
        self.assertEqual(render_draft(self.draft('正文[1][missing:web2]。'), [{'id': '1', 'url': 'javascript:bad'}]), '<p>正文。</p>\n')
