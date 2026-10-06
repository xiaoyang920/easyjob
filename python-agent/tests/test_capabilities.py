"""Execution capabilities come from current server policy, never model labels."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
os.environ["AGENT_SERVICE_KEY"] = "offline-service-key-32-bytes-long!!"

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.graph import main_agent as agent, staged_runtime as runtime
from app.graph.main_agent import MainDecision, RetrievalRequest
from app.graph.nodes import search_worker, writing_worker
from app.graph.staged_plan import (DependencyPlan, DelegatedTask, DraftRequest,
                                   ExecutionTask, load_execution_task)
from app.graph.state_factory import create_initial_state
from app.models.draft import DraftOutput
from app.security.capabilities import (effective_capabilities, require_capability,
                                       require_draft_approval, task_capabilities)
from app.services.query_rewrite import QueryFilters, ResolvedFilters
from fakes import RUN_ID, repository, select_fixture_evidence


def execution_state(kind="search", actor="main", allow_web=False):
    task = ExecutionTask(task_id="work", kind=kind, actor=actor,
                         instruction="find current sources", allow_web=allow_web)
    state = create_initial_state(7, task.instruction, [])
    state.update(current_task=task.model_dump(), task_id=task.task_id,
                 task_descriptions={kind: task.instruction}, allow_web=allow_web,
                 execution_mode="delegate" if actor == "subagent" else "direct",
                 capabilities=list(task_capabilities(task)))
    return state


class CapabilityPolicyTests(unittest.TestCase):
    def test_main_and_delegated_retrieval_have_the_same_policy(self):
        for enabled in (False, True):
            for requested in (False, True):
                with self.subTest(enabled=enabled, requested=requested), \
                     patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", enabled):
                    main = execution_state(allow_web=requested)
                    delegated = execution_state(actor="subagent", allow_web=requested)
                    expected = {"platform_read"}
                    if enabled and requested:
                        expected.add("web_search")
                    self.assertEqual(effective_capabilities(main), frozenset(expected))
                    self.assertEqual(effective_capabilities(delegated), frozenset(expected))

    def test_forged_grants_cannot_expand_analysis_or_writing(self):
        for kind, actor, expected in (("analysis", "main", set()),
                                       ("analysis", "subagent", set()),
                                       ("writing", "main", {"draft_generate"})):
            with self.subTest(kind=kind, actor=actor):
                state = execution_state(kind, actor)
                state["capabilities"] = ["platform_read", "web_search", "draft_generate", "admin"]
                state["allow_web"] = True
                self.assertEqual(effective_capabilities(state), frozenset(expected))
                for capability in {"platform_read", "web_search", "draft_generate", "admin"} - expected:
                    with self.subTest(capability=capability), self.assertRaises(PermissionError):
                        require_capability(state, capability)

    def test_persisted_grants_can_only_narrow_current_policy(self):
        with patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", True):
            state = execution_state(allow_web=True)
            state["capabilities"] = ["platform_read"]
            self.assertEqual(effective_capabilities(state), frozenset({"platform_read"}))
            with self.assertRaises(PermissionError):
                require_capability(state, "web_search")
            state["capabilities"] = []
            self.assertEqual(effective_capabilities(state), frozenset())
            with self.assertRaises(PermissionError):
                require_capability(state, "platform_read")

    def test_missing_task_context_and_mismatched_executor_fail_closed(self):
        state = create_initial_state(7, "find", [])
        state["capabilities"] = ["platform_read", "web_search", "draft_generate"]
        with self.assertRaises(PermissionError):
            effective_capabilities(state)
        with self.assertRaises(PermissionError):
            require_capability(state, "platform_read")
        state = execution_state(actor="subagent")
        state["execution_mode"] = "direct"
        with self.assertRaises(ValueError):
            effective_capabilities(state)

    def test_current_policy_restricts_old_checkpoints_without_grants(self):
        for actor in ("main", "subagent"):
            with self.subTest(actor=actor), patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", True):
                state = execution_state(actor=actor, allow_web=True)
                state.pop("capabilities")
                # Persisted tasks from the old contract are accepted only by the
                # internal checkpoint loader, then checked against today's policy.
                state["current_task"].pop("kind")
                state["current_task"].pop("actor")
                state["current_task"]["subagent"] = "search"
                self.assertIn("web_search", effective_capabilities(state))
                with patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", False):
                    self.assertEqual(effective_capabilities(state), frozenset({"platform_read"}))
                    with self.assertRaises(PermissionError):
                        require_capability(state, "web_search")

    def test_checkpoint_migration_does_not_accept_legacy_model_requests(self):
        legacy = {"task_id": "draft", "instruction": "write", "subagent": "writing"}
        task = load_execution_task(legacy, actor="main")
        self.assertEqual((task.kind, task.actor), ("writing", "main"))
        self.assertNotIn("subagent", task.model_dump())
        for stored_actor in ("main", "subagent"):
            checkpoint = {"task_id": "source", "instruction": "find", "subagent": "search", "actor": stored_actor}
            with self.subTest(actor=stored_actor):
                self.assertEqual(load_execution_task(checkpoint, actor=stored_actor).actor, stored_actor)
                conflicting_actor = "subagent" if stored_actor == "main" else "main"
                with self.assertRaisesRegex(ValueError, "执行者"):
                    load_execution_task(checkpoint, actor=conflicting_actor)
        with self.assertRaises(ValueError):
            DraftRequest.model_validate(legacy)
        with self.assertRaises(ValueError):
            MainDecision.model_validate({"action": "write_draft", "task": legacy})
        with self.assertRaises(ValueError):
            MainDecision.model_validate({"action": "write_draft", "draft_request": legacy})

    def test_changing_actor_cannot_repeat_the_same_retrieval_strategy(self):
        direct = MainDecision(action="retrieve", retrieval=RetrievalRequest(task_id="direct", instruction="find"))
        delegated = MainDecision(action="delegate", delegation_reason="independent research",
            plan=DependencyPlan(tasks=[DelegatedTask(task_id="delegated", subagent="search", instruction="find")]))
        for first, second in ((direct, delegated), (delegated, direct)):
            with self.subTest(first=first.action):
                state = create_initial_state(7, "find", [])
                update = agent.validate_action(state, first, 1)
                state.update(action_history=update["action_history"],
                    task_results={update["action_task_ids"][0]: {"status": "succeeded"}})
                result = agent.validate_action(state, second, 2)
                self.assertEqual(result["main_action"], "answer")
                self.assertIn("停止重复执行", result["stop_reason"])

    def test_draft_capability_does_not_replace_current_version_approval(self):
        state = execution_state(kind="writing")
        for decision in (None, "", "reject", "revise"):
            with self.subTest(decision=decision), self.assertRaises(PermissionError):
                require_draft_approval({**state, "decision": decision})
        require_draft_approval({**state, "decision": "approve"})


class CapabilityBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        selector = patch.object(search_worker.evidence_selector, "select", AsyncMock(side_effect=select_fixture_evidence))
        selector.start()
        self.addCleanup(selector.stop)

    async def test_web_failure_keeps_verified_platform_evidence(self):
        with patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", True):
            state = execution_state(allow_web=True)
            rewrite = {"semantic_queries": ["q"], "keywords": ["q"], "filters": QueryFilters(),
                       "search_mode": "hybrid", "need_web_search": True}
            documents = [{"article_id": "42", "title": "Platform doc", "content": "verified platform content"}]
            citation = {"id": "work:1", "articleId": "42", "source": "platform", "excerpt": "verified platform content"}
            with patch.object(search_worker.query_rewrite_service, "rewrite", AsyncMock(return_value=rewrite)), \
                 patch.object(search_worker.filter_resolver_instance, "resolve", AsyncMock(return_value=ResolvedFilters())), \
                 patch.object(search_worker.retrieval_service_instance, "hybrid_search", AsyncMock(return_value=documents)), \
                 patch.object(search_worker, "_verify_candidates_from_mysql", AsyncMock(return_value=documents)), \
                 patch.object(search_worker.reranker_service, "rerank", AsyncMock(return_value=documents)), \
                 patch.object(search_worker.citation_builder_instance, "build", return_value=([SimpleNamespace(to_dict=lambda: citation)], "[work:1] verified platform content")), \
                 patch.object(search_worker, "activity", AsyncMock()), \
                 patch.object(search_worker, "do_search", AsyncMock(side_effect=search_worker.WebSearchError("博查 API Key 无效或已过期"))):
                result = await search_worker.retrieve_evidence(state)
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["citations"], [citation])
            self.assertEqual(result["article_cards"][0]["articleId"], "42")
            self.assertIn("verified platform content", result["rag_context"])
            self.assertIn("不得声称已核实实时网页信息", result["rag_context"])

    async def test_invalid_web_key_is_a_tool_failure_not_an_empty_result(self):
        with patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", True):
            state = execution_state(allow_web=True)
            rewrite = {"semantic_queries": ["q"], "keywords": ["q"], "filters": QueryFilters(),
                       "search_mode": "web", "need_web_search": True}
            with patch.object(search_worker.query_rewrite_service, "rewrite", AsyncMock(return_value=rewrite)), \
                 patch.object(search_worker.filter_resolver_instance, "resolve", AsyncMock(return_value=ResolvedFilters())), \
                 patch.object(search_worker.retrieval_service_instance, "hybrid_search", AsyncMock(return_value=[])), \
                 patch.object(search_worker, "activity", AsyncMock()) as events, \
                 patch.object(search_worker, "do_search", AsyncMock(side_effect=search_worker.WebSearchError("博查 API Key 无效或已过期"))):
                result = await search_worker.retrieve_evidence(state)
            self.assertEqual(result["status"], "tool_error")
            self.assertIn("Key", result["result"])
            self.assertEqual(result["citations"], [])
            self.assertTrue(any(call.args[1] == "web" and call.args[3] == "error" for call in events.await_args_list if len(call.args) > 3))

    async def test_enabled_web_request_calls_tool_and_returns_its_evidence(self):
        with patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", True):
            state = execution_state(allow_web=True)
            rewrite = {"semantic_queries": ["q"], "keywords": ["q"],
                       "filters": QueryFilters(), "search_mode": "web", "need_web_search": True}
            with patch.object(search_worker.query_rewrite_service, "rewrite", AsyncMock(return_value=rewrite)), \
                 patch.object(search_worker.filter_resolver_instance, "resolve", AsyncMock(return_value=ResolvedFilters())), \
                 patch.object(search_worker.retrieval_service_instance, "hybrid_search", AsyncMock(return_value=[])), \
                 patch.object(search_worker, "activity", AsyncMock()), \
                 patch.object(search_worker, "do_search", AsyncMock(return_value=[
                     {"url": "https://example.org/current", "title": "Current source", "content": "verified web content"}])) as web:
                result = await search_worker.retrieve_evidence(state)
            web.assert_awaited_once_with("q", size=5)
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["citations"][0]["source"], "web")
            self.assertEqual(result["citations"][0]["url"], "https://example.org/current")
            self.assertIn("verified web content", result["rag_context"])

    async def test_server_disable_blocks_web_even_when_model_and_rewriter_request_it(self):
        for actor in ("main", "subagent"):
            with self.subTest(actor=actor), patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", True):
                state = execution_state(actor=actor, allow_web=True)
                # Grants were persisted while enabled. Turning policy off must
                # affect the actual tool call rather than just the next plan.
                self.assertIn("web_search", state["capabilities"])
                rewrite = {"semantic_queries": ["q"], "keywords": ["q"],
                           "filters": QueryFilters(), "search_mode": "web", "need_web_search": True}
                db = SimpleNamespace(fetch_all=AsyncMock(return_value=[]))
                with patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", False), \
                     patch.object(search_worker.query_rewrite_service, "rewrite", AsyncMock(return_value=rewrite)), \
                     patch.object(search_worker.filter_resolver_instance, "resolve", AsyncMock(return_value=ResolvedFilters())), \
                     patch.object(search_worker.retrieval_service_instance, "hybrid_search", AsyncMock(return_value=[])) as retrieve, \
                     patch.object(search_worker, "db", db), patch.object(search_worker, "activity", AsyncMock()), \
                     patch.object(search_worker, "do_search", AsyncMock()) as web:
                    result = await search_worker.retrieve_evidence(state)
                self.assertEqual(result["status"], "insufficient_evidence")
                self.assertEqual(retrieve.await_args.kwargs["search_mode"], "platform")
                web.assert_not_awaited()

    async def test_top_level_web_flag_cannot_grant_permission_to_platform_only_task(self):
        with patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", True):
            state = execution_state(allow_web=False)
            state["allow_web"] = True
            state["capabilities"] = ["platform_read", "web_search"]
            rewrite = {"semantic_queries": ["q"], "keywords": ["q"],
                       "filters": QueryFilters(), "search_mode": "web", "need_web_search": True}
            with patch.object(search_worker.query_rewrite_service, "rewrite", AsyncMock(return_value=rewrite)), \
                 patch.object(search_worker.filter_resolver_instance, "resolve", AsyncMock(return_value=ResolvedFilters())), \
                 patch.object(search_worker.retrieval_service_instance, "hybrid_search", AsyncMock(return_value=[])), \
                 patch.object(search_worker, "activity", AsyncMock()), \
                 patch.object(search_worker, "do_search", AsyncMock()) as web:
                result = await search_worker.retrieve_evidence(state)
            self.assertEqual(result["status"], "insufficient_evidence")
            web.assert_not_awaited()

    async def test_unauthorized_context_never_calls_rewriter_or_tools(self):
        states = [create_initial_state(7, "find", []), execution_state(kind="analysis"),
                  execution_state(kind="analysis", actor="subagent"), execution_state(kind="writing")]
        for state in states:
            state["capabilities"] = ["platform_read", "web_search"]
            with self.subTest(task=state.get("current_task")), \
                 patch.object(search_worker.query_rewrite_service, "rewrite", AsyncMock()) as rewrite, \
                 patch.object(search_worker, "do_search", AsyncMock()) as web:
                with self.assertRaises(PermissionError):
                    await search_worker.retrieve_evidence(state)
            rewrite.assert_not_awaited()
            web.assert_not_awaited()

    async def test_unapproved_draft_never_reaches_gateway(self):
        state = execution_state(kind="writing")
        state.update(run_id=RUN_ID, execution_token="executor",
                     draft=DraftOutput(title="Title", summary="Summary", content="# Draft").model_dump())
        with patch.object(runtime, "assert_run", AsyncMock()), \
             patch.object(writing_worker, "save_approved_draft", AsyncMock()) as save:
            for decision in (None, "", "reject", "revise"):
                with self.subTest(decision=decision), self.assertRaises(PermissionError):
                    await writing_worker.draft_save_node({**state, "decision": decision})
        save.assert_not_awaited()

    async def test_approved_legacy_writing_checkpoint_can_reach_gateway_under_current_policy(self):
        state = execution_state(kind="writing")
        state.pop("capabilities")
        state["current_task"].pop("kind")
        state["current_task"].pop("actor")
        state["current_task"]["subagent"] = "writing"
        state.update(run_id=RUN_ID, execution_token="executor", decision="approve", citations=[],
                     draft=DraftOutput(title="Title", summary="Summary", content="# Draft").model_dump())
        repo = repository()
        with patch.object(settings, "AGENT_WEB_SEARCH_ENABLED", False), \
             patch.object(runtime, "run_repository", repo), \
             patch.object(writing_worker, "save_approved_draft", AsyncMock(return_value=99)) as save:
            self.assertEqual(effective_capabilities(state), frozenset({"draft_generate"}))
            result = await writing_worker.draft_save_node(state)
        repo.assert_executor.assert_awaited_once_with(RUN_ID, "executor")
        save.assert_awaited_once()
        self.assertEqual(save.await_args.args[0]["user_id"], 7)
        self.assertEqual(save.await_args.args[0]["execution_token"], "executor")
        self.assertEqual(result["draft_article_id"], 99)


if __name__ == "__main__":
    unittest.main()
