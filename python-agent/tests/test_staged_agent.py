"""Exercise the production graph with real checkpoints and offline services."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
os.environ["AGENT_SERVICE_KEY"] = "offline-service-key-32-bytes-long!!"

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from fastapi import HTTPException

from app import main
from app.graph import builder, staged_runtime as runtime, main_agent as agent
from app.graph.main_agent import MainDecision
from test_main_agent import llm
from app.graph.staged_plan import (DependencyPlan, DelegatedTask, DraftRequest, ExecutionTask,
                                   build_execution_stages, compile_delegate_task, merge_task_results)
from app.graph.state_factory import create_initial_state
from app.graph.nodes import writing_worker
from app.models.draft import DraftOutput
from app.services.run_service import RunService
from app.services.run_repository import RunRepository
from app.security.principal import Principal
from fakes import repository, RUN_ID, HASH, SERVICE_KEY


def citation(tid):
    return {"id": tid + ":1", "articleId": "42", "title": "source", "excerpt": "evidence", "chunkIndex": 0}


class PlanValidationTests(unittest.TestCase):
    def test_two_searches_parallel_then_analysis_with_separate_draft_request(self):
        plan = DependencyPlan(tasks=[DelegatedTask(task_id="a", subagent="search", instruction="A"),
            DelegatedTask(task_id="b", subagent="search", instruction="B"),
            DelegatedTask(task_id="compare", subagent="analysis", instruction="compare", depends_on=["a", "b"])])
        draft = DraftRequest(task_id="draft", instruction="write", depends_on=["compare"])
        self.assertEqual(build_execution_stages(plan), [["a", "b"], ["compare"]])
        self.assertEqual(draft.depends_on, ["compare"])
        self.assertNotIn("subagent", draft.model_dump())

    def test_cycles_missing_and_duplicates_rejected(self):
        cases = [
            [DelegatedTask(task_id="a", subagent="search", instruction="A", depends_on=["b"]),
             DelegatedTask(task_id="b", subagent="analysis", instruction="B", depends_on=["a"])],
            [DelegatedTask(task_id="a", subagent="search", instruction="A", depends_on=["unknown"])],
            [DelegatedTask(task_id="a", subagent="search", instruction="A")] * 2,
        ]
        for tasks in cases:
            with self.subTest(tasks=tasks), self.assertRaises(ValueError):
                build_execution_stages(DependencyPlan(tasks=tasks))

    def test_delegation_rejects_business_workflows_and_privilege_expansion(self):
        for role in ("writing", "chat"):
            with self.subTest(role=role), self.assertRaises(ValueError):
                DelegatedTask(task_id="a", subagent=role, instruction="A")
        with self.assertRaises(ValueError):
            compile_delegate_task(DelegatedTask(task_id="a", subagent="analysis", instruction="A", allow_web=True))

    def test_execution_identity_is_compiled_and_internal_tasks_reject_privilege_expansion(self):
        task = compile_delegate_task(DelegatedTask(task_id="a", subagent="search", instruction="find"))
        self.assertEqual(task.actor, "subagent")
        self.assertEqual(task.kind, "search")
        self.assertNotIn("subagent", task.model_dump())
        for fields in (dict(kind="writing", actor="subagent"),
                       dict(kind="analysis", actor="main", allow_web=True),
                       dict(kind="analysis", actor="subagent", allow_web=True)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                ExecutionTask(task_id="a", instruction="A", **fields)

    def test_conflicting_results_and_failed_external_dependency_rejected(self):
        with self.assertRaises(ValueError):
            merge_task_results({"a": {"result": "old"}}, {"a": {"result": "new"}})
        with self.assertRaises(ValueError):
            build_execution_stages(DependencyPlan(tasks=[DelegatedTask(task_id="b", subagent="analysis",
                instruction="B", depends_on=["a"])]), {"a": {"status": "failed"}})

    def test_context_exposes_only_declared_dependencies(self):
        state = create_initial_state(7, "q", [])
        state["task_results"] = {"a": {"status": "succeeded", "result": "allowed", "citations": [citation("a")]},
                                 "b": {"status": "succeeded", "result": "secret unrelated", "citations": []}}
        task = ExecutionTask(task_id="analyze", kind="analysis", actor="subagent", instruction="inspect", depends_on=["a"], requires_evidence=True)
        context = runtime.task_context(state, task)
        self.assertIn("allowed", context["dependency_context"])
        self.assertNotIn("secret unrelated", context["dependency_context"])
        self.assertNotIn("task_results", context)

    def test_dependency_citation_collision_fails_closed(self):
        state = create_initial_state(7, "q", [])
        state["task_results"] = {"a": {"status": "succeeded", "citations": [citation("a")]},
                                 "b": {"status": "succeeded", "citations": [{**citation("a"), "excerpt": "changed"}]}}
        with self.assertRaises(ValueError):
            runtime.task_context(state, ExecutionTask(task_id="c", kind="analysis", actor="subagent", instruction="compare", depends_on=["a", "b"]))


class GraphExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_graph_parallel_dependencies_and_approval(self):
        plan = DependencyPlan(tasks=[DelegatedTask(task_id="a", subagent="search", instruction="search A"),
            DelegatedTask(task_id="b", subagent="search", instruction="search B"),
            DelegatedTask(task_id="analyze", subagent="analysis", instruction="compare", depends_on=["a", "b"], requires_evidence=True)])
        draft_request = DraftRequest(task_id="draft", instruction="write", depends_on=["analyze"], requires_evidence=True)
        started, finished = set(), set()
        both_started = asyncio.Event()
        async def search(state):
            tid = state["task_id"]
            started.add(tid)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 2)
            finished.add(tid)
            return {"worker_results": [{"worker_name": "search", "result": f"source [{tid}:1]"}],
                    "citations": [citation(tid)], "article_cards": [{"articleId": "42"}]}
        async def analysis(state):
            self.assertEqual(finished, {"a", "b"})
            self.assertEqual(set(json.loads(state["dependency_context"])), {"a", "b"})
            return {"worker_results": [{"worker_name": "analysis", "result": "comparison [a:1] [b:1]"}]}
        async def draft(task_input, system_prompt):
            self.assertIn("comparison [a:1] [b:1]", task_input)
            return DraftOutput(title="Review", summary="summary", content="# Review\nBased on [a:1] [b:1]")
        repo = repository()
        model, control = llm([MainDecision(action="delegate", plan=plan, delegation_reason="parallel research"),
                              MainDecision(action="write_draft", draft_request=draft_request)])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(runtime, "search_worker_node", search), patch.object(runtime, "analysis_worker_node", analysis), \
             patch.object(runtime, "run_repository", repo), patch.object(writing_worker, "generate_draft", AsyncMock(side_effect=draft)) as generate, \
             patch.object(writing_worker, "save_approved_draft", AsyncMock(return_value=99)) as save:
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            state = create_initial_state(7, "collect compare write", [])
            state.update(run_id=RUN_ID, execution_token="first")
            config = {"configurable": {"thread_id": "staged", "execution_token": "first"}}
            await graph.ainvoke(state, config)
            snap = await graph.aget_state(config)
            preview = snap.tasks[0].interrupts[0].value
            self.assertEqual(generate.await_count, 1)
            save.assert_not_awaited()
            config["configurable"]["execution_token"] = "resumed"
            await graph.ainvoke(Command(resume={"action": "approve", "runId": RUN_ID, "draftHash": preview["draftHash"]}), config)
            snap = await graph.aget_state(config)
            self.assertEqual(snap.values["draft_article_id"], 99)
            self.assertEqual(generate.await_count, 1)
            self.assertEqual(save.await_count, 1)
            self.assertEqual(save.call_args.args[0]["execution_token"], "resumed")
            self.assertEqual(len(snap.values["task_results"]), 4)
            self.assertEqual(snap.values["task_results"]["a"]["actor"], "subagent")
            self.assertEqual(snap.values["task_results"]["draft"]["actor"], "main")
            self.assertEqual(snap.values["task_results"]["draft"]["kind"], "writing")
            self.assertTrue(all("subagent" not in r for r in snap.values["task_results"].values()))
            self.assertEqual(snap.values["final_reply"], "草稿已保存到草稿箱。")
            self.assertEqual(control.ainvoke.await_count, 2)

    async def test_insufficient_search_does_not_start_downstream_and_replans_once(self):
        first = DependencyPlan(tasks=[DelegatedTask(task_id="a", subagent="search", instruction="A"),
            DelegatedTask(task_id="b", subagent="analysis", instruction="B", depends_on=["a"], requires_evidence=True)])
        second = DependencyPlan(tasks=[DelegatedTask(task_id="c", subagent="search", instruction="different query")])
        search = AsyncMock(return_value={"worker_results": [{"worker_name": "search", "result": "no evidence", "status": "insufficient_evidence"}], "citations": []})
        model, control = llm([MainDecision(action="delegate", plan=first, delegation_reason="isolated analysis"),
                              MainDecision(action="delegate", plan=second, delegation_reason="isolated research")])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(runtime, "search_worker_node", search), patch.object(runtime, "analysis_worker_node", AsyncMock()) as analysis:
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            output = await graph.ainvoke(create_initial_state(7, "q", []), {"configurable": {"thread_id": "failure"}})
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertEqual(output["task_results"]["b"]["status"], "blocked")
        self.assertEqual(search.await_count, 2)
        analysis.assert_not_awaited()
        self.assertIn("停止自动重试", output["final_reply"])

    async def test_generation_correction_reuses_evidence_and_does_not_rerun_search(self):
        plan = DependencyPlan(tasks=[DelegatedTask(task_id="a", subagent="search", instruction="A"),
            DelegatedTask(task_id="b", subagent="analysis", instruction="B", depends_on=["a"], requires_evidence=True)])
        search = AsyncMock(return_value={"worker_results": [{"worker_name": "search", "result": "source [a:1]"}], "citations": [citation("a")]})
        analysis = AsyncMock(side_effect=[{"worker_results": [{"worker_name": "analysis", "result": "invalid [fake:1]"}]},
                                         {"worker_results": [{"worker_name": "analysis", "result": "valid [a:1]"}]}])
        model, control = llm([MainDecision(action="delegate", plan=plan, delegation_reason="isolated analysis"),
                              MainDecision(action="answer", reply="valid [a:1]", answer_dependencies=["b"])])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(runtime, "search_worker_node", search), patch.object(runtime, "analysis_worker_node", analysis):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            result = await graph.ainvoke(create_initial_state(7, "q", []), {"configurable": {"thread_id": "correct"}})
        self.assertEqual(search.await_count, 1)
        self.assertEqual(analysis.await_count, 2)
        self.assertEqual(result["final_reply"], "valid [a:1]")

    async def test_stale_approval_does_not_save(self):
        request = DraftRequest(task_id="draft", instruction="write")
        model, _ = llm([MainDecision(action="write_draft", draft_request=request)])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(writing_worker, "generate_draft", AsyncMock(return_value=DraftOutput(title="A", summary="S", content="text"))), \
             patch.object(writing_worker, "save_approved_draft", AsyncMock()) as save:
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            config = {"configurable": {"thread_id": "stale"}}
            await graph.ainvoke(create_initial_state(7, "write", []), config)
            with self.assertRaises(ValueError):
                await graph.ainvoke(Command(resume={"action": "approve", "runId": "", "draftHash": HASH}), config)
            save.assert_not_awaited()

    async def test_next_action_keeps_successful_results(self):
        plan = DependencyPlan(tasks=[DelegatedTask(task_id="extra", subagent="search", instruction="new query"),
            DelegatedTask(task_id="answer", subagent="analysis", instruction="combine", depends_on=["known", "extra"], requires_evidence=True)])
        state = create_initial_state(7, "q", [])
        state.update(task_results={"known": {"status": "succeeded", "result": "keep", "citations": [citation("known")]}})
        result = agent.validate_action(state, MainDecision(action="delegate", plan=plan, delegation_reason="independent research"), 2)
        self.assertEqual(result["stages"], [["extra"], ["answer"]])
        self.assertNotIn("task_results", result)

    async def test_unchanged_replan_stops_without_repeating_subagents(self):
        plan = DependencyPlan(tasks=[DelegatedTask(task_id="a", subagent="search", instruction="same query")])
        retry_plan = DependencyPlan(tasks=[DelegatedTask(task_id="b", subagent="search", instruction="same query")])
        state = create_initial_state(7, "q", [])
        first = agent.validate_action(state, MainDecision(action="delegate", plan=plan, delegation_reason="isolated research"), 1)
        state.update(action_history=first["action_history"], task_results={"a": {"status": "insufficient_evidence"}})
        result = agent.validate_action(state, MainDecision(action="delegate", plan=retry_plan, delegation_reason="isolated research"), 2)
        self.assertEqual(result["main_action"], "answer")
        self.assertIn("停止重复执行", result["stop_reason"])


class AuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_python_refuses_missing_identity_and_forged_user(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            missing = await client.post("/chat", json={"user_id": 7, "message": "q"})
            forged = await client.post("/chat", json={"user_id": 8, "message": "q"},
                headers={"X-Agent-Key": SERVICE_KEY, "X-Agent-User": "7"})
            reload = await client.post("/mcp/reload", json={"servers": {}})
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(forged.status_code, 403)
        self.assertEqual(reload.status_code, 404)

    async def test_completed_request_replay_does_not_append_user_message_or_invoke_graph(self):
        from test_phase0 import services
        conversations, memory = services()
        repo = repository()
        repo.find_request.return_value = {"run_id": RUN_ID, "conversation_id": 11, "user_id": 7,
            "execution_token": "t", "input_hash": agent.digest({"message": "q", "images": []}),
            "status": "succeeded", "draft_article_id": None}
        cid, config, state = await RunService(conversations, memory, repo).prepare_chat(
            main.ChatRequest(user_id=7, message="q", request_id=RUN_ID), SimpleNamespace())
        self.assertEqual(cid, 11)
        self.assertTrue(config["configurable"]["replay"])
        self.assertIsNone(state)
        conversations.add_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
