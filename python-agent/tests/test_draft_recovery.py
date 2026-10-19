"""Production writing graph, frozen evidence and scripted models; no paid calls."""
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import test_grounding
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.graph import action_runtime, builder, draft_recovery, main_agent, staged_runtime
from app.graph.nodes import writing_worker
from app.graph.state_factory import create_initial_state
from app.models.draft import DraftOutput
from app.models.evidence_assessment import EvidenceAssessment
from app.services import grounding
from app.services.delivery_patch import GroundingPatch
from app.security.capabilities import effective_capabilities
from test_delivery_recovery import gap
from test_grounding import CID, CITATION, source_result
from fakes import RUN_ID, repository


class DraftRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def execute(self, *, lookup=True, retrieval_error=False, remaining=False,
                      missing='supporting_source', max_rounds=8, max_tasks=10,
                      repeat=False, deny_web=False, checkpoint=False, cancel=False, hard_error=False,
                      store=None, graph_config=None, restart_store=None):
        state = create_initial_state(7, '写一篇说明此版本默认值的文章', [])
        state.update(run_id=RUN_ID, execution_token='executor', main_round=1,
            task_results={'retrieve_1': {**source_result(), 'kind': 'search', 'actor': 'main',
                'retrieval_target': 'knowledge', 'instruction': '原查询', 'result': '没有默认值资料'}})
        if deny_web:
            state['active_constraints'] = [{'id': 'no_web', 'key': 'web_search', 'content': 'deny'}]
        request = main_agent.RetrievalRequest(instruction='原查询' if repeat else '补查此版本官方默认值',
            search_query=None if repeat else '版本 默认值 官方', filters={}, allow_web=not repeat)
        if repeat:
            old = main_agent.compile_action_plan(main_agent.MainDecision(action='retrieve', retrieval=request), 1).tasks[0]
            state['action_history'] = [{'action': 'retrieve', 'task_ids': ['retrieve_1'], 'tasks': [old.model_dump()]}]
        task_id = 'draft_test'
        decision = main_agent.MainDecision(action='write_draft',
            evidence_assessment=EvidenceAssessment(selected_ids=[CID], adequacy='sufficient', reason='候选资料'),
            draft_request={'task_id': task_id, 'instruction': '根据资料写文章',
                'requires_evidence': True, 'depends_on': ['retrieve_1']})
        main_control = SimpleNamespace(ainvoke=AsyncMock(side_effect=[decision,
            draft_recovery.DeliveryLookup(retrieval=request if lookup else None),
            main_agent.MainDecision(action='answer', reply='草稿已保存到草稿箱。')]))
        main_model = SimpleNamespace(with_structured_output=Mock(return_value=main_control))
        candidate = DraftOutput(title='版本说明', summary='概述',
            content=f'  开头🙂  \r\n\r\n该版本默认值为10。[{CID}]\r\n\r\n因此建议启用。\r\n\r\n结尾。')
        lookup_id = 'draft_lookup_' + hashlib.sha256(task_id.encode()).hexdigest()[:12]
        new_cid = lookup_id + ':1'
        will_lookup = lookup and not repeat and not hard_error and max_rounds > 2 and max_tasks >= 3 and missing in (
            'supporting_source', 'source_fulltext', 'version_details')
        fixed = f'该版本默认值为20。[{new_cid}]' if will_lookup and not retrieval_error else '缺少该版本官方说明，暂时不能确认具体默认值。'
        edits = GroundingPatch(replacements=[{'block_index': index, 'issue_block_index': 3, 'text': value}
            for index, value in [(3, fixed), (4, '需先确认版本和配置，再决定是否启用。')]])
        patch_control = SimpleNamespace(ainvoke=AsyncMock(return_value=edits))
        patch_model = SimpleNamespace(with_structured_output=Mock(return_value=patch_control))
        issue = gap(index=3, missing=missing)
        if hard_error:
            issue.update(verdict='contradicted', hard_error=True, issue_code='contradiction', missing_information=None)
        reviewer = AsyncMock(side_effect=[HTTPException(409, 'cancelled') if cancel else [issue],
                                          [issue] if remaining else []])
        async def retrieve(context):
            self.assertNotIn('draft_generate', effective_capabilities(context))
            if deny_web:
                self.assertNotIn('web_search', effective_capabilities(context))
            if retrieval_error:
                raise TimeoutError()
            return {'status': 'succeeded', 'rag_context': f'[{new_cid}] 官方默认值为20。',
                'citations': [{**CITATION, 'id': new_cid, 'excerpt': '官方默认值为20。'}],
                'citation_contents': {new_cid: '官方默认值为20。'}, 'article_cards': [],
                'retrieval_report': {'assessment_owner': 'main', 'platform': {'status': 'found'},
                                     'web': {'status': 'not_requested'}}}
        retriever = AsyncMock(side_effect=retrieve)
        generate = AsyncMock(return_value=candidate)
        save = AsyncMock(return_value=99)
        repo = repository()
        repo.record_delivery_failure = AsyncMock()
        repo.record_progress = AsyncMock()
        graph = builder._build_graph().compile(checkpointer=store or InMemorySaver())
        config = graph_config or {'configurable': {'thread_id': self.id()}}
        config['configurable']['execution_token'] = 'executor'
        config['recursion_limit'] = 80
        with patch.object(main_agent, 'get_llm', return_value=main_model), \
             patch.object(grounding, 'get_llm', return_value=patch_model), \
             patch.object(grounding, 'review_text', reviewer), \
             patch.object(writing_worker, 'generate_draft', generate), \
             patch.object(writing_worker, 'save_approved_draft', save), \
             patch.object(action_runtime, 'retrieve_evidence', retriever), \
             patch.object(staged_runtime, 'run_repository', repo), \
             patch('app.services.evidence_verifier.verify_public_evidence', AsyncMock()), \
             patch.object(staged_runtime, 'verify_public_evidence', AsyncMock()), \
             patch.object(main_agent.settings, 'MAIN_MAX_ROUNDS', max_rounds), \
             patch.object(main_agent.settings, 'MAIN_MAX_TASKS', max_tasks):
            if remaining or cancel:
                with self.assertRaises(HTTPException if cancel else grounding.DraftVerificationError) as raised:
                    await graph.ainvoke(state, config)
                save.assert_not_awaited()
                snapshot = await graph.aget_state(config, subgraphs=True)
                self.assertFalse(snapshot.tasks[0].interrupts)
                if cancel:
                    retriever.assert_not_awaited()
                    patch_control.ainvoke.assert_not_awaited()
                    repo.record_delivery_failure.assert_not_awaited()
                else:
                    self.assertIn('未进入审批或保存', str(raised.exception))
                    self.assertNotIn('已移除', str(raised.exception))
                    audit = repo.record_delivery_failure.await_args.args[2]
                    self.assertEqual(audit['failure_phase'], 'review_after_repair')
                    self.assertTrue(audit['remaining_findings'])
                    self.assertNotIn('statement', audit['remaining_findings'][0])
                return generate, reviewer, retriever, patch_control, None
            if checkpoint:
                # Pause after generation to prove recovery does not regenerate.
                child_graph = graph.get_subgraphs().__next__()[1]
                child_graph.interrupt_after_nodes = ['verify_draft' if checkpoint == 'review' else 'generate_draft']
                await graph.ainvoke(state, config)
                self.assertEqual(reviewer.await_count, 1 if checkpoint == 'review' else 0)
                if restart_store:
                    graph = builder._build_graph().compile(checkpointer=await restart_store())
                else:
                    child_graph.interrupt_after_nodes = []
                await graph.ainvoke(None, config)
            else:
                await graph.ainvoke(state, config)
            snapshot = await graph.aget_state(config, subgraphs=True)
            payload = snapshot.tasks[0].interrupts[0].value
            child = snapshot.tasks[0].state.values
            self.assertEqual(child['draft_candidate'], '')
            self.assertEqual(child['grounding_audit']['review_calls'], 2)
            self.assertEqual(child['grounding_audit']['repair_calls'], 1)
            self.assertTrue(payload['draft'].startswith('  开头🙂  \r\n\r\n'))
            self.assertTrue(payload['draft'].endswith('\r\n\r\n结尾。'))
            self.assertNotIn('citation-ref', child['draft_html'])
            self.assertNotRegex(child['draft_html'], r'\[[a-z][a-z0-9_]*:(?:web)?\d+\]')
            save.assert_not_awaited()
            # Do not ask Main for lookup in runs which skipped that branch.
            main_control.ainvoke.side_effect = [main_agent.MainDecision(action='answer', reply='草稿已保存到草稿箱。')]
            result = await graph.ainvoke(Command(resume={'action': 'approve', 'runId': RUN_ID,
                'draftHash': payload['draftHash']}), config)
            self.assertEqual(result['draft_article_id'], 99)
            self.assertEqual(save.await_count, 1)
            planned_lookup = not hard_error and max_rounds > 2 and max_tasks >= 3 and missing in (
                'supporting_source', 'source_fulltext', 'version_details')
            self.assertEqual(result['main_round'], 3 if planned_lookup else 2)
            if will_lookup:
                self.assertIn(lookup_id, result['task_results'])
                self.assertEqual(result['task_results'][lookup_id]['status'], 'tool_error' if retrieval_error else 'succeeded')
            if will_lookup and not retrieval_error:
                self.assertIn(new_cid, payload['draft'])
                self.assertIn(new_cid, {c['id'] for c in payload['citations']})
                sources = json.loads(patch_control.ainvoke.await_args.args[0][1].content)['sources']
                self.assertIn('官方默认值为20。', [source['content'] for source in sources])
        return generate, reviewer, retriever, patch_control, child

    async def test_gap_supplemented_once_then_patch_review_approval_and_save(self):
        generate, review, retrieval, repair, child = await self.execute()
        self.assertEqual((generate.await_count, review.await_count, retrieval.await_count, repair.ainvoke.await_count), (1, 2, 1, 1))
        self.assertEqual(child['grounding_audit']['lookup_status'], 'succeeded')

    async def test_failed_lookup_or_main_decline_uses_existing_sources(self):
        for kwargs in ({'retrieval_error': True}, {'lookup': False}):
            with self.subTest(kwargs=kwargs):
                generate, review, retrieval, repair, child = await self.execute(**kwargs)
                self.assertEqual((generate.await_count, review.await_count, repair.ainvoke.await_count), (1, 2, 1))
                self.assertEqual(retrieval.await_count, int(bool(kwargs.get('retrieval_error'))))

    async def test_nonretrievable_gaps_and_exhausted_task_or_round_budget_skip_lookup(self):
        for kwargs in ({'missing': 'measurement_data'}, {'missing': 'user_context'}, {'max_rounds': 2}, {'max_tasks': 2}):
            with self.subTest(kwargs=kwargs):
                _, _, retrieval, _, _ = await self.execute(**kwargs)
                retrieval.assert_not_awaited()

    async def test_repeated_strategy_does_not_rerun_and_permissions_remain_narrow(self):
        _, _, retrieval, _, child = await self.execute(repeat=True)
        retrieval.assert_not_awaited()
        self.assertEqual(child['grounding_audit']['lookup_status'], 'budget_or_repeat_limit')
        await self.execute(deny_web=True)

    async def test_failed_second_review_persists_safe_diagnostics_and_never_approves(self):
        generate, review, retrieval, repair, _ = await self.execute(remaining=True)
        self.assertEqual((generate.await_count, review.await_count, retrieval.await_count, repair.ainvoke.await_count), (1, 2, 1, 1))

    async def test_cancel_during_review_never_looks_up_repairs_or_saves(self):
        await self.execute(cancel=True)

    async def test_checkpoint_between_generation_and_audit_does_not_repeat_generation(self):
        for stage in ('generation', 'review'):
            with self.subTest(stage=stage):
                generate, review, _, _, _ = await self.execute(checkpoint=stage)
                generate.assert_awaited_once()
                self.assertEqual(review.await_count, 2)

    async def test_known_contradiction_is_repaired_without_searching_for_justification(self):
        _, _, retrieval, _, _ = await self.execute(remaining=True, hard_error=True)
        retrieval.assert_not_awaited()

    async def test_unavailable_auditor_stays_distinct_from_content_rejection(self):
        for failure in (TimeoutError(), ValueError('sensitive provider payload')):
            with self.subTest(error=type(failure).__name__), \
                 patch.object(grounding, 'review_text', AsyncMock(side_effect=failure)), \
                 patch.object(grounding, 'repair_text', AsyncMock()) as repair, \
                 patch.object(staged_runtime, 'assert_run', AsyncMock()):
                with self.assertRaises(grounding.DraftVerificationError) as raised:
                    await grounding.verify_delivery({}, '正文', [CITATION], draft=True)
                self.assertEqual(raised.exception.audit['status'], 'verification_unavailable')
                self.assertIn('未完成核验', str(raised.exception))
                self.assertNotIn('sensitive', str(raised.exception))
                self.assertNotIn('sensitive', json.dumps(raised.exception.audit))
                repair.assert_not_awaited()
