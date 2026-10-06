"""Regression for missing web execution, irrelevant hits and final source display."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["AGENT_SERVICE_KEY"] = "offline-service-key-32-bytes-long!!"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.config import settings
from app.graph.nodes import search_worker as search
from app.graph import action_runtime as actions, main_agent as agent, staged_runtime as runtime
from app.graph.staged_plan import ExecutionTask
from app.graph.state_factory import create_initial_state
from app.services import evidence_selection as selection
from app.services.query_rewrite import QueryFilters, ResolvedFilters
from app.services.filter_resolver import FilterResolutionError


class RetrievalDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def state(self, allow_web=True):
        task = ExecutionTask(task_id="source", actor="main", kind="search", instruction="整理几篇 Spring Boot 入门文章", allow_web=allow_web, filters={})
        return runtime.task_context(create_initial_state(7, task.instruction, []), task)

    async def retrieve(self, state, chosen, web=None, degraded=False, resolver=None):
        docs = [{"article_id": "42", "title": "Excel 导出", "content": "Spring @Async 导出 Excel 并上传 MinIO"}]
        if degraded:
            docs[0]['rerank_status'] = 'degraded'
        rewrite = {"semantic_queries": ["Spring Boot 入门教程"], "keywords": ["Spring Boot 入门"], "filters": QueryFilters(),
                   "search_mode": "platform", "need_web_search": False, "status": "degraded"}
        web_tool = AsyncMock(return_value=web or [])
        with patch.object(search.query_rewrite_service, "rewrite", AsyncMock(return_value=rewrite)), \
             patch.object(search.filter_resolver_instance, "resolve", resolver or AsyncMock(return_value=ResolvedFilters())), \
             patch.object(search.retrieval_service_instance, "hybrid_search", AsyncMock(return_value=docs)), \
             patch.object(search, "_verify_candidates_from_mysql", AsyncMock(return_value=docs)), \
             patch.object(search.reranker_service, "rerank", AsyncMock(return_value=docs)), \
             patch.object(search, "do_search", web_tool), \
             patch.object(search.evidence_selector, "select", AsyncMock(side_effect=chosen if isinstance(chosen, Exception) else None, return_value=chosen)):
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
        web.assert_not_awaited()

    async def test_degraded_rewrite_retains_all_explicit_filters_and_blocks_unverifiable_web(self):
        state = self.state()
        requested = QueryFilters(author_name='指定作者', category_names=['教程'], required_tags=['Redis'], time_range='month')
        state['current_task']['filters'] = requested.model_dump()
        resolver = AsyncMock(return_value=ResolvedFilters())
        with patch.object(settings, 'AGENT_WEB_SEARCH_ENABLED', True):
            result, web = await self.retrieve(state, selection.EvidenceSelection(adequacy='none', reason='no evidence'), resolver=resolver)
        resolver.assert_awaited_once_with(requested)
        self.assertEqual(result['retrieval_report']['query_rewrite']['status'], 'degraded')
        self.assertEqual(result['retrieval_report']['web']['reason'], 'required_platform_filters')
        web.assert_not_awaited()

    async def test_unresolved_authoritative_scope_returns_no_sources(self):
        state = self.state()
        state['current_task']['filters'] = QueryFilters(author_name='不存在的作者').model_dump()
        resolver = AsyncMock(side_effect=FilterResolutionError('指定作者不存在'))
        result, web = await self.retrieve(state, selection.EvidenceSelection(adequacy='none', reason='no evidence'), resolver=resolver)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['retrieval_report']['quality']['reason'], 'required_filter_unresolved')
        self.assertEqual(result['citations'], [])
        web.assert_not_awaited()

    async def test_main_web_request_survives_rewrite_denial_or_degradation(self):
        with patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", True):
            state = self.state()
            chosen = selection.EvidenceSelection(selected_ids=["web_0"], adequacy="partial", reason="仅一篇入门教程，平台笔记无关")
            result, web = await self.retrieve(state, chosen, [{"url": "https://spring.io/guides/gs/rest-service/", "title": "REST 入门", "content": "从 Spring Initializr 创建项目，编写 REST 控制器"}])
        web.assert_awaited_once_with("Spring Boot 入门", size=5)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["article_cards"], [])
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0]["source"], "web")
        self.assertEqual(result["retrieval_report"]["platform"]["status"], "irrelevant")
        self.assertEqual(result["retrieval_report"]["web"]["status"], "found")
        self.assertEqual(result["retrieval_report"]["quality"]["adequacy"], "partial")

    async def test_irrelevant_platform_hits_are_not_successful_evidence(self):
        result, web = await self.retrieve(self.state(False), selection.EvidenceSelection(adequacy="none", reason="项目经历不属于入门教程"))
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["article_cards"], [])
        self.assertEqual(result["retrieval_report"]["platform"]["status"], "irrelevant")
        self.assertEqual(result["retrieval_report"]["web"]["status"], "not_requested")
        web.assert_not_awaited()

    async def test_constraint_blocks_web_and_is_observed_as_blocked_not_empty(self):
        with patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", True):
            state = self.state()
            state["active_constraints"] = [{"id": "deny", "key": "web_search", "content": "deny"}]
            result, web = await self.retrieve(state, selection.EvidenceSelection(adequacy="none", reason="无关"))
        self.assertEqual(result["retrieval_report"]["web"]["status"], "blocked")
        web.assert_not_awaited()

    async def test_relevance_failure_never_promotes_unchecked_candidates(self):
        result, _ = await self.retrieve(self.state(False), TimeoutError())
        self.assertEqual(result["status"], "tool_error")
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["article_cards"], [])
        self.assertEqual(result["retrieval_report"]["quality"]["adequacy"], "unknown")

    async def test_degraded_rerank_is_reported_and_still_requires_relevance_verification(self):
        result, _ = await self.retrieve(self.state(False),
            selection.EvidenceSelection(adequacy='none', reason='只是框架同名，与目标无关'), degraded=True)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['retrieval_report']['platform']['rerank']['status'], 'degraded')
        self.assertEqual(result['retrieval_report']['quality']['verification'], 'completed')
        self.assertEqual(result['citations'], [])
        result, _ = await self.retrieve(self.state(False), TimeoutError(), degraded=True)
        self.assertEqual(result['status'], 'tool_error')
        self.assertEqual(result['citations'], [])

    async def test_verified_degraded_source_retains_its_degradation_report(self):
        result, _ = await self.retrieve(self.state(False),
            selection.EvidenceSelection(selected_ids=['platform_0'], adequacy='partial', reason='支持部分目标'), degraded=True)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['retrieval_report']['platform']['rerank']['status'], 'degraded')
        self.assertEqual(result['retrieval_report']['quality']['adequacy'], 'partial')

    async def test_report_is_persisted_and_visible_even_for_failed_retrieval(self):
        state = create_initial_state(7, "find", [])
        state.update(main_round=1, main_action="retrieve")
        update = agent.validate_action(state, agent.MainDecision(action="retrieve", retrieval=agent.RetrievalRequest(instruction="find")), 1)
        state.update(update)
        report = {"platform": {"status": "irrelevant"}, "web": {"status": "not_requested"}, "quality": {"adequacy": "none"}}
        evidence = {"status": "insufficient_evidence", "result": "未找到相关教程", "citations": [], "article_cards": [], "retrieval_report": report}
        with patch.object(actions, "retrieve_evidence", AsyncMock(return_value=evidence)):
            outcome = await actions.main_retrieve_node(state)
        self.assertEqual(outcome["task_results"]["retrieve_1"]["retrieval_report"], report)
        self.assertEqual(outcome["observations"][0]["retrieval_reports"]["retrieve_1"], report)
        state.update(outcome)
        self.assertIn('not_requested', agent.decision_context(state))

    async def test_selector_rejects_invented_source_duplicate_ids_and_inconsistent_adequacy(self):
        for output in ({"selected_ids": ["invented"], "adequacy": "sufficient", "reason": "fake"},
                       {"selected_ids": ["web_0", "web_0"], "adequacy": "partial", "reason": "duplicate"},
                       {"selected_ids": [], "adequacy": "sufficient", "reason": "empty"}):
            control = SimpleNamespace(ainvoke=AsyncMock(return_value=output))
            model = SimpleNamespace(with_structured_output=Mock(return_value=control))
            with self.subTest(output=output), patch.object(selection, "get_llm", return_value=model), self.assertRaises(ValueError):
                await selection.EvidenceSelector().select("find", [{"id": "web_0", "content": "data"}])


class FinalEvidenceTests(unittest.TestCase):
    def test_original_document_footnotes_are_data_but_generated_references_are_validated(self):
        task = ExecutionTask(task_id="source", kind="search", actor="main", instruction="find", requires_evidence=True)
        state = runtime.task_context(create_initial_state(7, "find", []), task)
        update = {"worker_results": [{"worker_name": "search", "result": "[source:1] 原始文档自带旧编号[old_task:web6]及脚注[7]"}],
                  "citations": [{"id": "source:1", "articleId": "42"}]}
        self.assertEqual(runtime.task_result(state, update, raw_retrieval=True)["status"], "succeeded")
        self.assertEqual(runtime.task_result(state, update)["status"], "invalid_citation")
        analysis = ExecutionTask(task_id="analysis", kind="analysis", actor="main", instruction="analyze")
        state = runtime.task_context(create_initial_state(7, "analyze", []), analysis)
        with self.assertRaises(PermissionError):
            runtime.task_result(state, update, raw_retrieval=True)

    def test_recovery_limit_describes_actual_search_scope_without_claiming_web_was_used(self):
        for status, expected in (("not_requested", "本轮未执行联网检索"), ("blocked", "权限或约束限制"),
                                 ("irrelevant", "已检索平台和公开网页"), ("error", "联网搜索未完成")):
            state = {"observations": [{"retrieval_reports": {"source": {"web": {"status": status}, "quality": {"adequacy": "none"}}}}]}
            with self.subTest(status=status):
                stopped = agent.recovery_limit_reply(state)
                self.assertIn(expected, stopped["final_reply"])
                self.assertIn("停止自动重试", stopped["stop_reason"])

    def test_only_sources_used_outside_code_and_their_cards_are_delivered(self):
        citations = [{"id": "source:1", "articleId": "42"}, {"id": "source:2", "articleId": "43"},
                     {"id": "source:web3", "articleId": "", "url": "https://example.org"}]
        cards = [{"articleId": "42"}, {"articleId": "43"}]
        selected, displayed = runtime.used_evidence("正文[source:web3]，代码 `[source:1]`，正文[source:2]", citations, cards)
        self.assertEqual([c["id"] for c in selected], ["source:2", "source:web3"])
        self.assertEqual(displayed, [{"articleId": "43"}])
