"""Mixed factual/reasoning answers, local salvage and honest audit failures."""
import json
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import test_grounding as fixtures
from test_grounding import CID, CONTENT, CITATION, review
from app.graph.state_factory import create_initial_state
from app.models.evidence_assessment import EvidenceAssessment
from app.services import grounding
from app.services.execution_facts import execution_facts


def claim(statement, *, kind='source_fact', verdict='supported', unit=0, quote=CONTENT, rationale=''):
    return grounding.ClaimReview(unit_index=unit, statement=statement, kind=kind, verdict=verdict,
        reason='固定测试判断', rationale=rationale,
        quotes=[grounding.Quote(citation_id=CID, text=quote)] if quote else [])


def blocks(*claims):
    return grounding.GroundingReview(blocks=[grounding.BlockReview(block_index=i, claims=[value])
        for i, value in enumerate(claims)])


class PolicyContractTests(unittest.TestCase):
    def test_recommendation_general_knowledge_and_derived_conclusion_need_no_direct_quote(self):
        for kind, rationale, quote in [
            ('recommendation', '在读多写少且可接受短暂不一致的前提下，先采用简单补偿方案，降低维护成本。', ''),
            ('general_knowledge', '', ''),
            ('inference', '来源说明重试不能保证强一致，因此不能据此承诺所有读取都立刻最新。', CONTENT),
        ]:
            with self.subTest(kind=kind):
                response = blocks(claim('这是一条条件性分析', kind=kind, rationale=rationale, quote=quote))
                result = grounding.validate_review(response, ['这是一条条件性分析'], [{**CITATION, 'content': CONTENT}])
                self.assertEqual(result, [])

    def test_source_facts_still_need_evidence_and_explicit_citations_cannot_switch_sources(self):
        response = blocks(claim('本资料规定12GB', quote=''))
        with self.assertRaisesRegex(ValueError, '缺少支持引文'):
            grounding.validate_review(response, ['本资料规定12GB'], [{**CITATION, 'content': CONTENT}])
        response = review(statement='建议采用该方案', kind='recommendation', rationale='符合条件', citation_id='retrieve_1:2')
        result = grounding.validate_review(response, [f'建议采用该方案[{CID}]'],
            [{**CITATION, 'content': CONTENT}, {'id': 'retrieve_1:2', 'content': CONTENT}])
        self.assertIn('正文引用不一致', result[0]['reason'])

    def test_reasoning_requires_rationale_and_execution_assertions_use_server_facts(self):
        for kind in ('inference', 'recommendation'):
            response = blocks(claim('建议先测试', kind=kind, quote=''))
            self.assertTrue(grounding.validate_review(response, ['建议先测试'], []))
        response = blocks(claim('草稿已保存到草稿箱', kind='execution_fact', quote=''))
        result = grounding.validate_review(response, ['草稿已保存到草稿箱'], [], facts=execution_facts({}))
        self.assertIn('真实执行状态', result[0]['reason'])

    def test_cited_fact_and_advice_can_share_unit_without_forcing_advice_into_source(self):
        text = f'可以异步重试，建议先做小规模验证[{CID}]'
        response = grounding.GroundingReview(blocks=[grounding.BlockReview(block_index=0, claims=[
            claim('可以异步重试，'), claim('建议先做小规模验证', kind='recommendation', quote='', rationale='先验证业务可接受性')])])
        self.assertEqual(grounding.validate_review(response, [text], [{**CITATION, 'content': CONTENT}]), [])

    def test_failure_detail_never_persists_arbitrary_provider_exception_text(self):
        self.assertEqual(grounding.audit_failure_detail(ValueError('核验返回未知依据编号')), 'unknown_evidence')
        detail = grounding.audit_failure_detail(ValueError('request contains private text and secret'))
        self.assertEqual(detail, 'response_schema')


class MixedAnswerTests(unittest.IsolatedAsyncioTestCase):
    run_graph = fixtures.GroundingGraphTests.run_graph

    async def test_fact_plus_unquoted_advice_survives_without_repair(self):
        advice = '若能接受短暂不一致，我建议先采用简单重试方案'
        candidate = f'可用异步重试补偿[{CID}]\n\n{advice}'
        response = blocks(claim('可用异步重试补偿'), claim(advice, kind='recommendation', quote='',
            rationale='在可接受短暂不一致的条件下，简单方案便于维护'))
        result, _, _, repair = await self.run_graph(candidate, [response])
        self.assertEqual(result['final_reply'], candidate)
        self.assertEqual(result['grounding_audit']['status'], 'verified')
        repair.ainvoke.assert_not_awaited()

    async def test_repair_still_bad_preserves_good_fact_and_conditional_advice(self):
        candidate = f'可以异步重试[{CID}]\n\n保证绝对强一致[{CID}]\n\n建议先验证业务容忍度'
        response = blocks(claim('可以异步重试'), claim('保证绝对强一致', verdict='contradicted'),
            claim('建议先验证业务容忍度', kind='recommendation', quote='', rationale='确定业务允许的延迟范围'))
        result, _, audit, repair = await self.run_graph(candidate, [response, response], [candidate])
        self.assertEqual(result['grounding_audit']['status'], 'partial')
        self.assertIn('可以异步重试', result['final_reply'])
        self.assertIn('建议先验证业务容忍度', result['final_reply'])
        self.assertNotIn('保证绝对强一致', result['final_reply'])
        self.assertEqual((audit.ainvoke.await_count, repair.ainvoke.await_count), (2, 1))

    async def test_repair_timeout_or_reaudit_timeout_keeps_original_reviewed_part(self):
        candidate = f'可以异步重试[{CID}]\n\n保证绝对强一致[{CID}]'
        response = blocks(claim('可以异步重试'), claim('保证绝对强一致', verdict='contradicted'))
        for audits, repairs in [([response], [TimeoutError('repair timeout')]),
                                 ([response, TimeoutError('reaudit timeout')], [candidate])]:
            with self.subTest(audits=audits):
                result, _, _, _ = await self.run_graph(candidate, audits, repairs)
                self.assertEqual(result['grounding_audit']['status'], 'partial')
                self.assertEqual(result['grounding_audit']['reason_code'], 'timeout')
                self.assertIn('可以异步重试', result['final_reply'])
                self.assertNotIn('保证绝对强一致', result['final_reply'])
                self.assertIn('不代表已判定原回答错误', result['final_reply'])

    async def test_no_evidence_allows_qualified_general_advice_without_fake_sources(self):
        advice = '没有检索到相关资料；若你能接受短暂延迟，建议先验证简单方案'
        assessment = EvidenceAssessment(selected_ids=[], adequacy='none', reason='没有匹配来源')
        response = review(quote='', kind='recommendation', rationale='以用户可接受短暂延迟为显式假设，建议先验证')
        result, _, audit, repair = await self.run_graph(advice, [response], assessment=assessment)
        self.assertIn(advice, result['final_reply'])
        self.assertIn('不代表已通过本次检索验证', result['final_reply'])
        self.assertEqual(audit.ainvoke.await_count, 1)
        repair.ainvoke.assert_not_awaited()

    async def test_sourced_draft_timeout_still_blocks_approval_with_correct_reason(self):
        state = create_initial_state(7, '根据资料写文章', [])
        state['evidence_contents'] = {CID: CONTENT}
        text = json.dumps({'title': '缓存', 'summary': '分析', 'content': f'可异步重试[{CID}]'})
        with patch.object(grounding, 'review_text', AsyncMock(side_effect=TimeoutError('offline'))):
            with self.assertRaisesRegex(ValueError, '核验超时.*未进入审批或保存'):
                await grounding.verify_delivery(state, text, [CITATION], draft=True)

    async def test_repair_cannot_convert_ordinary_answer_to_draft_json(self):
        converted = json.dumps({'title': '标题', 'summary': '摘要', 'content': '正文'})
        control = SimpleNamespace(ainvoke=AsyncMock(return_value=grounding.GroundingPatch(replacements=[
            {'block_index': 0, 'issue_block_index': 0, 'text': converted}])))
        model = SimpleNamespace(with_structured_output=lambda *args, **kwargs: control)
        with patch.object(grounding, 'get_llm', return_value=model):
            with self.assertRaisesRegex(ValueError, '输出格式'):
                await grounding.repair_text('普通回答', [], execution_facts({}), ['修正'])
        prompt = control.ainvoke.await_args.args[0][0].content
        self.assertIn('当前输入是普通回答', prompt)


if __name__ == '__main__':
    unittest.main()
