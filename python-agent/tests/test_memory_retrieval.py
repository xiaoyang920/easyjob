"""Exercise the production retrieve loop and private memory service boundary offline."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
os.environ["AGENT_SERVICE_KEY"] = "offline-service-key-32-bytes-long!!"

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.memory import InMemorySaver

from app import main
from app.graph import builder, main_agent as agent, action_runtime as actions, staged_runtime as runtime
from app.graph.main_agent import MainDecision, RetrievalRequest
from app.graph.nodes import memory_retrieval, search_worker
from app.graph.staged_plan import DelegatedTask, ExecutionTask, compile_delegate_task, load_execution_task
from app.graph.state_factory import create_initial_state
from app.security.capabilities import effective_capabilities, require_capability
from app.services.memory import MemoryService
from fakes import RUN_ID, repository
from test_main_agent import llm, evidence, run_updates
from test_streaming import parse_frames, result as stream_result


def decision(target="memory", tid="history", instruction="阶段屏障的调整原因"):
    return MainDecision(action="retrieve", retrieval=RetrievalRequest(target=target, task_id=tid, instruction=instruction))


def context(target="memory"):
    task = ExecutionTask(task_id="history", kind="search", actor="main", retrieval_target=target, instruction="history")
    return runtime.task_context(create_initial_state(7, "question", []), task)


def memories(profile="默认使用 Java", content="private history [old:1]"):
    return {"profile_summary": profile, "memories": [{"memory_id": 42, "content": content,
            "importance": 0.5, "source_conversation_id": 11}]}


def row(**values):
    return SimpleNamespace(_mapping=values)


class RetrievalContractTests(unittest.TestCase):
    def test_target_survives_compilation_and_legacy_defaults_to_knowledge(self):
        self.assertEqual(RetrievalRequest(instruction="find").target, "knowledge")
        for target in ("memory", "knowledge"):
            update = agent.validate_action(create_initial_state(7, "q", []), decision(target), 1)
            task = load_execution_task(update["plan"]["tasks"][0], "main")
            self.assertEqual(task.retrieval_target, target)
            self.assertEqual(task.requires_evidence, target == "knowledge")
        legacy = {"task_id": "old", "subagent": "search", "instruction": "find"}
        self.assertEqual(load_execution_task(legacy, "main").retrieval_target, "knowledge")
        self.assertEqual(compile_delegate_task(DelegatedTask(task_id="child", subagent="search", instruction="find")).retrieval_target, "knowledge")

    def test_model_cannot_select_identity_grants_or_invalid_targets(self):
        for extra in ({"target": "sql"}, {"target": "memory", "allow_web": True},
                      {"user_id": 99}, {"retrieval_target": "memory"}, {"capabilities": ["memory_read"]},
                      {"scope": "all_users"}, {"top_k": 100}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                RetrievalRequest(instruction="find", **extra)
        for extra in ({"kind": "analysis", "actor": "main", "retrieval_target": "memory"},
                      {"kind": "search", "actor": "subagent", "retrieval_target": "memory"},
                      {"kind": "search", "actor": "main", "retrieval_target": "memory", "allow_web": True},
                      {"kind": "search", "actor": "main", "retrieval_target": "memory", "requires_evidence": True}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                ExecutionTask(task_id="bad", instruction="find", **extra)

    def test_targets_have_disjoint_grants_even_if_state_forces_all_capabilities(self):
        for target, expected in (("memory", {"memory_read"}), ("knowledge", {"platform_read"})):
            state = context(target)
            state.update(capabilities=["platform_read", "memory_read", "web_search", "draft_generate"], target="memory")
            self.assertEqual(effective_capabilities(state), frozenset(expected))
            for cap in {"platform_read", "memory_read", "web_search", "draft_generate"} - expected:
                with self.subTest(target=target, cap=cap), self.assertRaises(PermissionError):
                    require_capability(state, cap)

    def test_memory_cannot_satisfy_public_evidence_or_carry_article_metadata(self):
        state = context()
        update = {"worker_results": [{"result": "old [old:1]"}], "citations": [], "article_cards": [],
                  "memory_sources": [{"id": "memory:42", "type": "event"}], "memory_found": True, "memory_match_count": 1}
        result = runtime.task_result(state, update)
        self.assertEqual(result["status"], "succeeded")
        parent = create_initial_state(7, "q", [])
        parent["task_results"] = {"history": result}
        self.assertEqual(agent.answer_evidence(parent, ["history"]), ([], []))
        with self.assertRaises(ValueError):
            runtime.task_context(parent, ExecutionTask(task_id="draft", kind="writing", actor="main", instruction="write",
                depends_on=["history"], requires_evidence=True))
        for extra in ({"citations": evidence()["citations"]}, {"article_cards": evidence()["article_cards"]}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                runtime.task_result(state, {**update, **extra})


class MemoryServiceBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        pending = patch("app.services.memory_policy.memory_policy_service.flush_pending_index", AsyncMock())
        pending.start()
        self.addCleanup(pending.stop)

    async def test_real_search_filters_user_and_mysql_removes_foreign_or_deleted_candidates_in_es_order(self):
        service = MemoryService.__new__(MemoryService)
        service._embedding = SimpleNamespace(aembed=AsyncMock(return_value=[0.1]))
        search = AsyncMock(return_value={"hits": {"hits": [{"_source": {"memory_id": mid}, "_score": 1.0}
                                                         for mid in (2, 99, 1, 2)]}})
        service._es = SimpleNamespace(client=SimpleNamespace(search=search))
        service._get_profile = AsyncMock(return_value=None)
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[
            row(memory_id=1, content="first", source_conversation_id=11),
            row(memory_id=2, content="second", source_conversation_id=12)]), execute=AsyncMock())
        with patch("app.services.memory.db", database):
            recalled = await service.recall_details(7, "query", top_k=3, strict=True)
        self.assertEqual(search.await_args.kwargs["knn"]["filter"], {'bool': {'filter': [
            {'term': {'user_id': 7}}, {'term': {'memory_type': 'decision'}}, {'term': {'scope': 'user'}}]}})
        self.assertIn("memory_type='decision'", database.fetch_all.await_args.args[0])
        self.assertEqual([m["memory_id"] for m in recalled["memories"]], [2, 1])
        self.assertIn("user_id = :uid", database.fetch_all.await_args.args[0])
        self.assertEqual(database.fetch_all.await_args.args[1]["uid"], 7)
        self.assertIn("user_id = :uid", database.execute.await_args.args[0])
        self.assertEqual(set(database.execute.await_args.args[1].values()), {1, 2, 7})
        service._get_profile.assert_awaited_once_with(7)

    async def test_explicit_index_failure_propagates_but_automatic_recall_keeps_fallback(self):
        service = MemoryService.__new__(MemoryService)
        service._embedding = SimpleNamespace(aembed=AsyncMock(side_effect=TimeoutError("private endpoint")))
        service._get_profile = AsyncMock(return_value={"summary": "Java preference"})
        with self.assertRaises(TimeoutError):
            await service.recall_details(7, "q", strict=True)
        self.assertIn("Java preference", await service.recall(7, "q"))

    async def test_capability_denial_happens_before_either_retriever_calls_dependencies(self):
        with patch.object(memory_retrieval.memory_service, "recall_details", AsyncMock()) as recall, \
             patch.object(search_worker.query_rewrite_service, "rewrite", AsyncMock()) as rewrite:
            with self.assertRaises(PermissionError):
                await memory_retrieval.retrieve_memory(context("knowledge"))
            with self.assertRaises(PermissionError):
                await search_worker.retrieve_evidence(context("memory"))
            state = context()
            state["user_id"] = 0
            with self.assertRaises(PermissionError):
                await memory_retrieval.retrieve_memory(state)
        recall.assert_not_awaited()
        rewrite.assert_not_awaited()

    async def test_profile_only_is_not_reported_as_a_historical_event(self):
        with patch.object(memory_retrieval.memory_service, "recall_details", AsyncMock(return_value={
                "profile_summary": "Java", "memories": []})):
            result = await memory_retrieval.retrieve_memory(context())
        self.assertFalse(result["memory_found"])
        self.assertEqual(result["memory_match_count"], 0)
        self.assertEqual(result["memory_sources"], [])
        self.assertIn("未找到相关已确认决策", result["result"])


class MemoryActionLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_memory_branch_returns_results_to_main_without_an_extra_worker_llm(self):
        model, control = llm([decision(), MainDecision(action="answer", reply="根据历史候选给出解释", answer_dependencies=["history"])])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(memory_retrieval.memory_service, "recall_details", AsyncMock(return_value=memories())) as recall, \
             patch.object(actions, "retrieve_evidence", AsyncMock()) as knowledge:
            result, nodes = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "why", []))
        self.assertEqual(nodes, ["main_agent", "main_retrieve", "main_agent", "final_gate"])
        self.assertEqual(control.ainvoke.await_count, 2)
        model.ainvoke.assert_not_awaited()
        recall.assert_awaited_once_with(7, "阶段屏障的调整原因", top_k=3, strict=True, conversation_id=None, include_profile=False)
        knowledge.assert_not_awaited()
        previous = json.loads(control.ainvoke.await_args_list[1].args[0][1].content)["successful_tasks"]["history"]
        self.assertEqual(previous["retrieval_target"], "memory")
        self.assertIn("private history [old:1]", previous["result"])
        self.assertEqual(previous["memory_sources"][0]["id"], "memory:42")
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["correction_count"], 0)

    async def test_completed_empty_lookup_is_visible_to_main_and_uses_no_recovery(self):
        model, control = llm([decision(), MainDecision(action="answer", reply="没有找到这次决策的历史")])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(memory_retrieval.memory_service, "recall_details", AsyncMock(return_value={"profile_summary": "", "memories": []})):
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "q", []))
        self.assertEqual(result["task_results"]["history"]["status"], "succeeded")
        self.assertFalse(result["task_results"]["history"]["memory_found"])
        self.assertEqual(result["correction_count"], 0)
        context_data = json.loads(control.ainvoke.await_args_list[1].args[0][1].content)
        self.assertFalse(context_data["successful_tasks"]["history"]["memory_found"])

    async def test_same_query_can_search_different_targets_and_only_knowledge_yields_citations(self):
        model, _ = llm([decision(), decision("knowledge", tid="source"),
                       MainDecision(action="answer", reply="事实来自文章 [source:1]", answer_dependencies=["history", "source"])])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(memory_retrieval.memory_service, "recall_details", AsyncMock(return_value=memories())) as recall, \
             patch.object(actions, "retrieve_evidence", AsyncMock(return_value=evidence("source"))) as knowledge:
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "q", []))
        self.assertEqual(recall.await_count, 1)
        self.assertEqual(knowledge.await_count, 1)
        self.assertEqual(result["citations"], evidence("source")["citations"])
        self.assertNotIn("stop_reason", {k: v for k, v in result.items() if v})

    async def test_same_memory_query_with_a_new_task_id_is_not_reexecuted(self):
        model, _ = llm([decision(), decision(tid="repeat")])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(memory_retrieval.memory_service, "recall_details", AsyncMock(return_value=memories())) as recall:
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "q", []))
        self.assertEqual(recall.await_count, 1)
        self.assertIn("停止重复执行", result["stop_reason"])

    async def test_timeout_can_retry_once_and_never_leaks_endpoint_or_changes_target(self):
        model, control = llm([decision(), decision(tid="retry"), MainDecision(action="answer", reply="已恢复")])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(memory_retrieval.memory_service, "recall_details", AsyncMock(side_effect=[TimeoutError("private endpoint"), memories()])) as recall, \
             patch.object(actions, "retrieve_evidence", AsyncMock()) as knowledge:
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "q", []))
        self.assertEqual(recall.await_count, 2)
        knowledge.assert_not_awaited()
        self.assertEqual(result["task_results"]["history"]["status"], "tool_error")
        self.assertEqual(result["task_results"]["retry"]["retrieval_target"], "memory")
        self.assertEqual(result["correction_count"], 1)
        self.assertNotIn("private endpoint", json.dumps(result))
        self.assertNotIn("private endpoint", control.ainvoke.await_args_list[1].args[0][1].content)

    async def test_bad_memory_request_gets_one_schema_repair_without_execution(self):
        model, control = llm([{"action": "retrieve", "retrieval": {"target": "memory", "instruction": "find", "allow_web": True}},
                              MainDecision(action="answer", reply="修正后回答")])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(memory_retrieval.memory_service, "recall_details", AsyncMock()) as recall:
            _, nodes = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "q", []))
        self.assertEqual(nodes, ["main_agent", "final_gate"])
        self.assertEqual(control.ainvoke.await_count, 2)
        recall.assert_not_awaited()

    async def test_stream_labels_memory_and_keeps_recalled_body_out_of_activity_events(self):
        model, _ = llm([decision(), MainDecision(action="answer", reply="历史说明")])
        service = SimpleNamespace(repository=repository(), finish=AsyncMock(return_value=stream_result("历史说明")))
        config = {"configurable": {"thread_id": "memory-stream", "run_id": RUN_ID, "execution_token": "t"}}
        with patch.object(agent, "get_llm", return_value=model), patch.object(main, "run_service", service), \
             patch.object(memory_retrieval.memory_service, "recall_details", AsyncMock(return_value=memories())):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            frames = [frame async for frame in __import__("test_streaming").source_response(graph, create_initial_state(7, "q", []), 11, 7, config).body_iterator]
        events = parse_frames(frames, "__AGENT_EVENT__:")
        plan = next(event for event in events if event["kind"] == "plan")
        self.assertEqual(plan["tasks"][0]["role"], "memory")
        self.assertTrue(any(event.get("label") == "召回相关记忆" and event.get("status") == "done" for event in events))
        self.assertNotIn("private history", json.dumps(events))
        self.assertNotIn("memory:42", json.dumps(events))
        self.assertEqual(events[-1]["status"], "complete")


if __name__ == "__main__":
    unittest.main()
