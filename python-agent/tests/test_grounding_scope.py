"""Markdown citation scope and coherent local omission, without external calls."""
import unittest

from app.services import grounding
from app.services.execution_facts import execution_facts

A, B = 'retrieve_1:1', 'retrieve_1:2'
TABLE = '| Option | Mode |\n| --- | --- |\n| DemoGraph | Explicit graph |\n| DemoFlow | Sequential flow |'
SOURCES = [{'id': A, 'content': TABLE}, {'id': B, 'content': 'Start small. Add a tool. Add memory.'}]


def annotate(text, bad=None):
    blocks = grounding.text_blocks(text)
    units = grounding.review_units(blocks)
    catalog = grounding.evidence_catalog(SOURCES)
    reviews = []
    for i, group in enumerate(units):
        claims = []
        for unit in group:
            structural = (unit.get('citation_role') == 'label'
                          or unit['text'].startswith(('| Option', '| ---')))
            claims.append(grounding.ClaimReview(unit_index=unit['unit_index'],
                kind='non_factual' if structural else 'source_fact' if unit['citation_ids'] else 'general_knowledge',
                verdict='non_factual' if structural else 'contradicted' if bad and bad in unit['text'] else 'supported',
                evidence_ids=[] if structural else [key for key, quote in catalog.items()
                    if quote.citation_id in unit['citation_ids']]))
        reviews.append(grounding.BlockReview(block_index=i, claims=claims))
    return grounding.validate_review(grounding.GroundingReview(blocks=reviews), blocks, SOURCES, catalog=catalog)


class CitationScopeTests(unittest.TestCase):
    def test_reference_before_colon_applies_to_all_following_steps(self):
        units = grounding.claim_units(f'- **Steps**[{B}]: first; second; third.')
        self.assertEqual(units[0]['citation_role'], 'label')
        self.assertGreater(len(units), 3)
        self.assertTrue(all(unit['citation_ids'] == [B] for unit in units))
        self.assertTrue(all(unit['citation_role'] == 'inherited' for unit in units[1:]))

    def test_trailing_list_label_binds_table_without_absorbing_previous_fact(self):
        blocks = [f'- A fact[{B}].\n- **Options**[{A}]:', TABLE, 'Unrelated prose.', '## New section', 'Other prose.']
        units = grounding.review_units(blocks)
        self.assertEqual(units[0][0]['citation_ids'], [B])
        self.assertEqual(units[0][-1]['citation_role'], 'label')
        self.assertTrue(all(unit['citation_ids'] == [A] for unit in units[1]))
        self.assertTrue(all(not unit['citation_ids'] for group in units[2:] for unit in group))

    def test_scope_stops_at_new_heading_and_does_not_cross_draft_metadata(self):
        self.assertTrue(all(not unit['citation_ids'] for unit in grounding.review_units(
            [f'**Options**[{A}]:', '## Other section', TABLE])[2]))
        units = grounding.review_units([f'title: Example[{A}]:', 'summary: Unrelated', TABLE], metadata_indices=(0, 1))
        self.assertTrue(all(not unit['citation_ids'] for group in units[1:] for unit in group))

    def test_explicit_row_reference_overrides_inherited_table_source(self):
        table = TABLE + f'\n| Other | Other mode[{B}] |'
        units = grounding.review_units([f'**Options**[{A}]:', table])[1]
        self.assertEqual(units[-1]['citation_ids'], [B])
        self.assertEqual(units[-1]['citation_role'], 'inline')

    def test_comparison_cells_keep_their_own_sources_without_neighbor_binding(self):
        table = (f'| 名称 | A | B |\n|---|---|---|\n'
                 f'| 路径 | 路径直观[{A}] | 需要重试[{B}] |\n'
                 f'| 维护 | 我建议先验证小方案 | 需要监控[{B}] |')
        units = grounding.review_units([table])[0]
        by_text = {unit['text']: unit for unit in units}
        self.assertEqual(by_text['路径直观']['citation_ids'], [A])
        self.assertEqual(by_text['需要重试']['citation_ids'], [B])
        self.assertEqual(by_text['我建议先验证小方案']['citation_ids'], [])
        self.assertEqual(by_text['需要监控']['citation_ids'], [B])
        self.assertEqual(by_text['路径直观']['citation_role'], 'inline')
        self.assertEqual([unit['unit_index'] for unit in units], list(range(len(units))))

    def test_list_item_reference_cannot_reach_back_to_previous_item(self):
        text = f'1. A的说明。\n2. B的说明[{B}]。本项分析。\n3. A的事实[{A}]'
        units = grounding.review_units([text])[0]
        self.assertEqual([unit['citation_ids'] for unit in units], [[], [B], [], [A]])

    def test_table_inline_code_and_escaped_pipe_do_not_split_cells(self):
        table = f'| 名称 | 示例 |\n|---|---|\n| A | `a|b`与a\\|b[{A}] |'
        units = grounding.review_units([table])[0]
        self.assertEqual(units[-1]['text'], '`a|b`与a\\|b')
        self.assertEqual(units[-1]['citation_ids'], [A])

    def test_row_suffix_and_list_intro_sources_remain_scoped(self):
        table = f'| 名称 | 数值 |\n|---|---|\n| A | 1 |[{A}]'
        units = grounding.review_units([table])[0]
        self.assertEqual(units[-1]['citation_ids'], [A])
        groups = grounding.review_units([f'**步骤**[{A}]:', f'- 第一步\n- 第二步[{B}]'])
        self.assertEqual([unit['citation_ids'] for unit in groups[1]], [[A], [B]])

    def test_neighbor_cells_do_not_require_wrong_source_and_wrong_cell_still_rejected(self):
        text = f'| A | B |\n|---|---|\n| 路径直观[{A}] | 需要重试[{B}] |'
        sources = [{'id': A, 'content': '路径直观'}, {'id': B, 'content': '需要重试'}]
        units = grounding.review_units([text])[0]
        claims = [grounding.ClaimReview(unit_index=unit['unit_index'],
            kind='source_fact' if unit['citation_ids'] else 'non_factual',
            verdict='supported' if unit['citation_ids'] else 'non_factual',
            quotes=[grounding.Quote(citation_id=cid, text=sources[0 if cid == A else 1]['content'])
                    for cid in unit['citation_ids']]) for unit in units]
        response = grounding.GroundingReview(blocks=[grounding.BlockReview(block_index=0, claims=claims)])
        self.assertEqual(grounding.validate_review(response, [text], sources), [])
        claims[-1].quotes = [grounding.Quote(citation_id=A, text='路径直观')]
        issues = grounding.validate_review(response, [text], sources)
        self.assertIn('正文引用不一致', issues[0]['reason'])
        self.assertEqual(issues[0]['citation_ids'], [B])
        self.assertEqual(issues[0]['evidence_citation_ids'], [A])

    def test_table_footer_applies_to_the_table_but_not_unrelated_prose(self):
        blocks = [TABLE, f'来源：[{A}]', 'Unrelated prose.']
        units = grounding.review_units(blocks)
        self.assertTrue(all(unit['citation_ids'] == [A] for unit in units[0]))
        self.assertTrue(all(unit['citation_role'] == 'label' for unit in units[1]))
        self.assertTrue(all(not unit['citation_ids'] for unit in units[2]))
        self.assertEqual(annotate('\n\n'.join(blocks)), [])

    def test_intro_code_source_keeps_array_literal_as_data(self):
        units = grounding.review_units([f'**Example**[{A}]:', '```python\nvalues = [9]\n```'])[1]
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]['citation_ids'], [A])

    def test_cited_table_and_learning_steps_pass_without_repeating_inline_refs(self):
        text = f'**Options**[{A}]:\n\n{TABLE}\n\n**Steps**[{B}]: first; second; third.'
        result = annotate(text)
        self.assertEqual(result, [])
        self.assertEqual(result.omitted_blocks, [])

    def test_partial_delivery_preserves_complete_table_without_placeholder_paragraphs(self):
        text = f'**Options**[{A}]:\n\n{TABLE}\n\n(Source includes wrong statement.)'
        result = annotate(text, bad='wrong statement')
        retained = grounding.retained_answer(result, execution_facts({}))
        self.assertIn(TABLE, retained)
        self.assertNotIn('此处内容未通过依据核验', retained)
        self.assertNotIn('Source includes', retained)
        self.assertEqual(len(result.omitted_blocks), 1)

    def test_one_failed_claim_does_not_leave_half_parentheses_or_empty_label(self):
        text = 'Reliable fact.\n\n**Options**: (wrong statement.)'
        result = annotate(text, bad='wrong statement')
        retained = grounding.retained_answer(result, execution_facts({}))
        self.assertIn('Reliable fact.', retained)
        self.assertNotIn('**Options**', retained)
        self.assertNotIn('(', retained)


if __name__ == '__main__':
    unittest.main()
