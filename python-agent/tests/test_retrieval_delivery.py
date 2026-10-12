"""Retrieval fetches candidates; Main assesses and acts in one model call."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["AGENT_SERVICE_KEY"] = "offline-service-key-32-bytes-long!!"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.config import settings
from app.graph.nodes import search_worker as search
from app.graph import action_runtime as actions, main_agent as agent, staged_runtime as runtime
from app.graph.staged_plan import ExecutionTask
from app.graph.state_factory import create_initial_state
from app.models.evidence_assessment import EvidenceAssessment
from app.services.query_rewrite import QueryFilters, ResolvedFilters
from app.services.filter_resolver import FilterResolutionError


class RetrievalDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def state(self, allow_web=True):
        task = ExecutionTask(task_id="source", actor="main", kind="search", instruction="整理几篇 Spring Boot 入门文章", allow_web=allow_web, filters={})
        return runtime.task_context(create_initial_state(7, task.instruction, []), task)

    async def retrieve(self, state, web=None, degraded=False, resolver=None, docs=None):
        if docs is None:
            docs = [{"article_id": "42", "title": "Excel 导出", "content": "Spring @Async 导出 Excel 并上传 MinIO"}]
        if degraded:
            docs = [{**doc, 'rerank_status': 'degraded'} for doc in docs]
        rewrite = {"semantic_queries": ["Spring Boot 入门教程"], "keywords": ["Spring Boot 入门"], "filters": QueryFilters(),
                   "search_mode": "platform", "need_web_search": False, "status": "degraded"}
        web_tool = AsyncMock(return_value=web or [])
        with patch.object(search.query_rewrite_service, "rewrite", AsyncMock(return_value=rewrite)), \
             patch.object(search.filter_resolver_instance, "resolve", resolver or AsyncMock(return_value=ResolvedFilters())), \
             patch.object(search.retrieval_service_instance, "hybrid_search", AsyncMock(return_value=docs)), \
             patch.object(search, "_verify_candidates_from_mysql", AsyncMock(return_value=docs)), \
             patch.object(search.reranker_service, "rerank", AsyncMock(return_value=docs)), \
             patch.object(search, "do_search", web_tool), \
             patch('app.config.get_llm', side_effect=AssertionError('unexpected relevance model call')):
            result = await search.retrieve_evidence(state)
        return result, web_tool

    async def test_failed_rewrite_without_authoritative_scope_does_not_search(self):
        state = self.state()
        state['current_task']['filters'] = None
        with patch.object(search.query_rewrite_service, 'rewrite', AsyncMock(return_value={'status': 'degraded'})), \
             patch.object(search.retrieval_service_instance, 'hybrid_search', AsyncMock()) as coarse, \
             patch.object(search, 'do_search', AsyncMock()) as web:
            result = await search.retrieve_evidence(state)
            coarse.assert_not_awaited()
        self.assertEqual(result['status'], 'tool_error')
        self.assertEqual(result['citations'], [])
        self.assertNotIn('quality', result['retrieval_report'])
        web.assert_not_awaited()

    async def test_degraded_rewrite_retains_explicit_filters_and_blocks_web(self):
        state = self.state()
        requested = QueryFilters(author_name='指定作者', category_names=['教程'], required_tags=['Redis'], time_range='month')
        state['current_task']['filters'] = requested.model_dump()
        resolver = AsyncMock(return_value=ResolvedFilters())
        with patch.object(settings, 'AGENT_WEB_SEARCH_ENABLED', True):
            result, web = await self.retrieve(state, resolver=resolver)
        resolver.assert_awaited_once_with(requested)
        self.assertEqual(result['retrieval_report']['query_rewrite']['status'], 'degraded')
        self.assertEqual(result['retrieval_report']['web']['reason'], 'required_platform_filters')
        web.assert_not_awaited()

    async def test_unresolved_scope_returns_no_sources(self):
        state = self.state()
        state['current_task']['filters'] = QueryFilters(author_name='不存在的作者').model_dump()
        result, web = await self.retrieve(state, resolver=AsyncMock(side_effect=FilterResolutionError('指定作者不存在')))
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['retrieval_report']['failure_reason'], 'required_filter_unresolved')
        self.assertEqual(result['citations'], [])
        web.assert_not_awaited()

    async def test_platform_and_web_candidates_reach_main_without_relevance_call(self):
        with patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", True):
            result, web = await self.retrieve(self.state(), [{"url": "https://spring.io/guides/gs/rest-service/",
                "title": "REST 入门", "content": "从 Spring Initializr 创建项目，编写 REST 控制器"}])
        web.assert_awaited_once_with("Spring Boot 入门", size=5)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(len(result['citations']), 2)
        self.assertEqual(result['retrieval_report']['assessment_owner'], 'main')
        self.assertNotIn('quality', result['retrieval_report'])
        self.assertEqual(result['retrieval_report']['platform']['status'], 'found')
        self.assertEqual(result['retrieval_report']['web']['status'], 'found')
        self.assertIn('Excel', result['rag_context'])

    async def test_empty_candidates_are_not_reported_as_success(self):
        result, web = await self.retrieve(self.state(False), docs=[])
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['citations'], [])
        self.assertEqual(result['article_cards'], [])
        self.assertEqual(result['retrieval_report']['platform']['status'], 'empty')
        web.assert_not_awaited()

    async def test_constraint_blocks_web_and_is_observed_as_blocked(self):
        with patch.object(settings, 'AGENT_WEB_SEARCH_ENABLED', True):
            state = self.state()
            state['active_constraints'] = [{'id': 'deny', 'key': 'web_search', 'content': 'deny'}]
            result, web = await self.retrieve(state)
        self.assertEqual(result['retrieval_report']['web']['status'], 'blocked')
        web.assert_not_awaited()

    async def test_degraded_rerank_returns_candidates_without_claiming_semantic_quality(self):
        result, _ = await self.retrieve(self.state(False), degraded=True)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['retrieval_report']['platform']['rerank']['status'], 'degraded')
        self.assertNotIn('quality', result['retrieval_report'])
        self.assertTrue(result['citations'])

    async def test_failed_report_is_persisted_and_visible_to_main(self):
        state = create_initial_state(7, 'find', [])
        state.update(main_round=1, main_action='retrieve')
        state.update(agent.validate_action(state, agent.MainDecision(action='retrieve',
            retrieval=agent.RetrievalRequest(instruction='find')), 1))
        report = {'assessment_owner': 'main', 'platform': {'status': 'empty'}, 'web': {'status': 'not_requested'}}
        evidence = {'status': 'insufficient_evidence', 'result': '未返回候选', 'citations': [], 'article_cards': [], 'retrieval_report': report}
        with patch.object(actions, 'retrieve_evidence', AsyncMock(return_value=evidence)):
            outcome = await actions.main_retrieve_node(state)
        self.assertEqual(outcome['task_results']['retrieve_1']['retrieval_report'], report)
        self.assertEqual(outcome['observations'][0]['retrieval_reports']['retrieve_1'], report)
        state.update(outcome)
        self.assertIn('not_requested', agent.decision_context(state))


class IntegratedAssessmentTests(unittest.IsolatedAsyncioTestCase):
    def state(self):
        state = create_initial_state(7, '整理 Spring Boot 入门文章', [])
        state['task_results'] = {'source': {'status': 'succeeded', 'kind': 'search', 'actor': 'main',
            'instruction': 'find', 'result': 'Excel 项目笔记 [source:1]\nREST 入门 [source:web2]',
            'retrieval_target': 'knowledge', 'retrieval_report': {'assessment_owner': 'main',
                'platform': {'status': 'found'}, 'web': {'status': 'found'}},
            'citations': [{'id': 'source:1', 'articleId': '42', 'title': 'Excel', 'excerpt': '无关项目笔记'},
                          {'id': 'source:web2', 'articleId': '', 'title': 'REST 入门', 'excerpt': '教程', 'url': 'https://spring.io/guide'}],
            'article_cards': [{'articleId': '42'}],
            'citation_contents': {'source:1': 'Excel 无关项目笔记', 'source:web2': '完整教程' * 400 + '保留末尾正文'}}}
        return state

    def assessment(self, **overrides):
        return EvidenceAssessment(**{'selected_ids': ['source:web2'], 'adequacy': 'partial',
            'reason': '仅有一篇相关教程', 'missing_aspects': ['其他入门文章'], **overrides})

    async def decide(self, state, decisions):
        control = SimpleNamespace(ainvoke=AsyncMock(side_effect=decisions))
        model = SimpleNamespace(with_structured_output=Mock(return_value=control))
        with patch.object(agent, 'get_llm', return_value=model):
            result = await agent.decide_main_action(state)
        return result, control

    async def test_partial_answer_and_selection_share_one_model_call(self):
        decision = agent.MainDecision(action='answer', reply='找到一篇 REST 入门教程 [source:web2]，其余尚缺。',
            evidence_assessment=self.assessment())
        result, control = await self.decide(self.state(), [decision])
        self.assertEqual(control.ainvoke.await_count, 1)
        self.assertEqual([c['id'] for c in result['citations']], ['source:web2'])
        self.assertIsNone(result['article_cards'])
        self.assertEqual(result['main_decision']['evidence_assessment']['adequacy'], 'partial')

    async def test_none_answer_never_forces_irrelevant_citations_or_cards(self):
        decision = agent.MainDecision(action='answer', reply='当前候选没有相关教程，请提供来源。',
            evidence_assessment=self.assessment(selected_ids=[], adequacy='none'))
        result, control = await self.decide(self.state(), [decision])
        self.assertEqual(control.ainvoke.await_count, 1)
        self.assertIsNone(result['citations'])
        self.assertIsNone(result['article_cards'])

    async def test_partial_assessment_and_new_query_are_emitted_together(self):
        state = self.state()
        decision = agent.MainDecision(action='retrieve', evidence_assessment=self.assessment(),
            retrieval=agent.RetrievalRequest(instruction='补充 Spring Boot 配置与自动装配入门文章',
                search_query='Spring Boot 配置 自动装配 入门教程', filters={}, allow_web=True))
        result, control = await self.decide(state, [decision])
        self.assertEqual(control.ainvoke.await_count, 1)
        self.assertEqual(result['main_action'], 'retrieve')
        self.assertEqual(result['plan']['tasks'][0]['search_query'], decision.retrieval.search_query)
        self.assertEqual(set(state['task_results']), {'source'})
        context = json.loads(agent.decision_context({**state, **result}))
        self.assertEqual(context['previous_evidence_assessment']['missing_aspects'], ['其他入门文章'])

    async def test_missing_assessment_enters_existing_bounded_format_repair(self):
        bad = agent.MainDecision(action='answer', reply='没有资料')
        good = agent.MainDecision(action='answer', reply='当前候选不足。',
            evidence_assessment=self.assessment(selected_ids=[], adequacy='none'))
        result, control = await self.decide(self.state(), [bad, good])
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertEqual(result['final_reply'], good.reply)

    def test_assessment_cannot_invent_ids_or_select_failed_or_undeclared_dependencies(self):
        for changes in ({'selected_ids': ['fake:1']}, {'selected_ids': ['failed:1']}):
            state = self.state()
            state['task_results']['failed'] = {'status': 'tool_error', 'citations': [{'id': 'failed:1'}]}
            decision = agent.MainDecision(action='answer', reply='answer', evidence_assessment=self.assessment(**changes))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                agent.validate_evidence_assessment(state, decision)
        state = self.state()
        state['task_results']['other'] = {'status': 'succeeded', 'citations': []}
        with self.assertRaises(ValueError):
            agent.validate_evidence_assessment(state, agent.MainDecision(action='answer', reply='answer',
                answer_dependencies=['other'], evidence_assessment=self.assessment()))

    def test_inconsistent_assessments_are_rejected(self):
        for changes in ({'selected_ids': ['source:1', 'source:1']}, {'selected_ids': []},
                        {'adequacy': 'none'}, {'adequacy': 'sufficient'}, {'missing_aspects': ['']}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.assessment(**changes)

    def test_bounded_stop_uses_only_main_selected_sources(self):
        state = self.state()
        state['task_results']['source']['retrieval_report']['quality'] = {'adequacy': 'sufficient'}
        state['main_decision'] = {'evidence_assessment': self.assessment().model_dump()}
        result = agent.bounded_evidence_reply(state, 'limit')
        self.assertEqual([c['id'] for c in result['citations']], ['source:web2'])
        self.assertNotIn('Excel', result['final_reply'])
        self.assertTrue(result['final_reply'].startswith('limit'))
        self.assertIsNone(result['article_cards'])
        self.assertEqual(result['delivery_evidence']['citations'], result['citations'])
        state['main_decision'] = {'evidence_assessment': self.assessment(selected_ids=[], adequacy='none').model_dump()}
        self.assertIsNone(agent.bounded_evidence_reply(state, 'limit')['citations'])
        self.assertTrue(agent.bounded_evidence_reply(state, 'limit')['final_reply'].startswith('limit'))

    def test_unassessed_candidates_are_not_promoted_by_bounded_stop(self):
        result = agent.bounded_evidence_reply(self.state(), 'limit')
        self.assertTrue(result['final_reply'].startswith('limit'))
        self.assertIsNone(result['citations'])

    def test_draft_dependencies_and_main_artifacts_only_receive_selected_sources(self):
        state = self.state()
        state['main_decision'] = {'evidence_assessment': self.assessment().model_dump()}
        task = ExecutionTask(task_id='draft', kind='writing', actor='main', instruction='write',
            depends_on=['source'], requires_evidence=True)
        context = runtime.task_context(state, task)
        self.assertEqual([c['id'] for c in context['citations']], ['source:web2'])
        self.assertEqual(context['dependency_cards'], [])
        self.assertNotIn('Excel', context['dependency_context'])
        self.assertIn('保留末尾正文', context['dependency_context'])
        self.assertNotIn('citation_contents', context['dependency_context'])
        bad = agent.MainArtifact(task_id='notes', instruction='analyze', result='bad [source:1]', depends_on=['source'])
        with self.assertRaises(agent.ArtifactCitationError):
            agent.prepare_artifacts(state, [bad])
        self.assertEqual(len(state['task_results']['source']['citations']), 2)

    async def test_no_selected_evidence_cannot_start_evidence_required_draft(self):
        decision = agent.MainDecision(action='write_draft',
            evidence_assessment=self.assessment(selected_ids=[], adequacy='none'),
            draft_request=agent.DraftRequest(task_id='draft', instruction='write', depends_on=['source'], requires_evidence=True))
        result, control = await self.decide(self.state(), [decision])
        self.assertEqual(control.ainvoke.await_count, 1)
        self.assertEqual(result['main_action'], 'answer')
        self.assertIn('未启动生成', result['final_reply'])

    async def test_main_artifact_with_missing_selected_evidence_stops_without_server_error(self):
        decision = agent.MainDecision(action='retrieve',
            evidence_assessment=self.assessment(selected_ids=[], adequacy='none'),
            retrieval=agent.RetrievalRequest(instruction='new search'), artifacts=[agent.MainArtifact(
                task_id='notes', instruction='analyze', result='unsupported', depends_on=['source'], requires_evidence=True)])
        result, control = await self.decide(self.state(), [decision])
        self.assertEqual(control.ainvoke.await_count, 1)
        self.assertIn('未通过校验', result['stop_reason'])

    async def test_repeated_query_stop_uses_current_selection_without_another_call(self):
        state = self.state()
        decision = agent.MainDecision(action='retrieve', evidence_assessment=self.assessment(),
            retrieval=agent.RetrievalRequest(instruction='same query', filters={}))
        previous = agent.validate_action(state, decision, 1)
        state['action_history'] = previous['action_history']
        state['main_round'] = 1
        state['task_results'][previous['action_task_ids'][0]] = {'status': 'insufficient_evidence'}
        result, control = await self.decide(state, [decision])
        self.assertEqual(control.ainvoke.await_count, 1)
        self.assertIn('停止重复执行', result['stop_reason'])
        self.assertEqual([c['id'] for c in result['citations']], ['source:web2'])


class FinalEvidenceTests(unittest.TestCase):
    def test_original_document_footnotes_are_data_but_generated_references_are_validated(self):
        task = ExecutionTask(task_id='source', kind='search', actor='main', instruction='find', requires_evidence=True)
        state = runtime.task_context(create_initial_state(7, 'find', []), task)
        update = {'worker_results': [{'worker_name': 'search', 'result': '[source:1] 原始文档自带旧编号[old_task:web6]及脚注[7]'}],
                  'citations': [{'id': 'source:1', 'articleId': '42'}]}
        self.assertEqual(runtime.task_result(state, update, raw_retrieval=True)['status'], 'succeeded')
        self.assertEqual(runtime.task_result(state, update)['status'], 'invalid_citation')
        analysis = ExecutionTask(task_id='analysis', kind='analysis', actor='main', instruction='analyze')
        with self.assertRaises(PermissionError):
            runtime.task_result(runtime.task_context(create_initial_state(7, 'analyze', []), analysis), update, raw_retrieval=True)

    def test_recovery_limit_describes_actual_search_scope(self):
        for status, expected in (('not_requested', '本轮未执行联网检索'), ('blocked', '权限或约束限制'),
                                 ('empty', '已检索平台和公开网页'), ('error', '联网搜索未完成')):
            state = {'observations': [{'retrieval_reports': {'source': {'assessment_owner': 'main',
                'platform': {'status': 'empty'}, 'web': {'status': status}}}}]}
            with self.subTest(status=status):
                stopped = agent.recovery_limit_reply(state)
                self.assertIn(expected, stopped['final_reply'])
                self.assertIn('停止自动重试', stopped['stop_reason'])

    def test_only_sources_used_outside_code_and_their_cards_are_delivered(self):
        citations = [{'id': 'source:1', 'articleId': '42'}, {'id': 'source:2', 'articleId': '43'},
                     {'id': 'source:web3', 'articleId': '', 'url': 'https://example.org'}]
        cards = [{'articleId': '42'}, {'articleId': '43'}]
        selected, displayed = runtime.used_evidence('正文[source:web3]，代码 `[source:1]`，正文[source:2]', citations, cards)
        self.assertEqual([c['id'] for c in selected], ['source:2', 'source:web3'])
        self.assertEqual(displayed, [{'articleId': '43'}])
