"""Regression tests for dynamic decisions, dependency scheduling and correction limits."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
os.environ["AGENT_SERVICE_KEY"] = "offline-service-key-32-bytes-long!!"

import asyncio
import json
import unittest
from grounding_fakes import setUpModule, tearDownModule
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import NodeCancelledError
from langgraph.types import Command

from app.graph import builder, main_agent as agent, action_runtime as actions, staged_runtime as runtime
from app.graph.main_agent import MainArtifact, MainDecision, RetrievalRequest
from app.graph.staged_plan import DependencyPlan, DelegatedTask, DraftRequest
from app.graph.state_factory import create_initial_state
from app.graph.nodes import writing_worker
from app.models.draft import DraftOutput
from fakes import repository, RUN_ID
from test_main_agent import llm, evidence, run_updates


def retrieve(instruction="find", tid="source"):
    return MainDecision(action="retrieve", retrieval=RetrievalRequest(task_id=tid, instruction=instruction))


def delegate(tasks):
    return MainDecision(action="delegate", plan=DependencyPlan(tasks=tasks), delegation_reason="independent research and isolated analysis")


def search_result(tid, status="succeeded"):
    return {"worker_results": [{"worker_name": "search", "result": f"source [{tid}:1]" if status == "succeeded" else "no evidence",
                                "status": status}], "citations": evidence(tid)["citations"] if status == "succeeded" else []}


class ActionLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_observes_tool_error_and_changes_strategy_without_exposing_error_details(self):
        model, control = llm([retrieve("first"), retrieve("narrower", "new_source"),
                              MainDecision(action="answer", reply="found [new_source:1]")])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(actions, "retrieve_evidence", AsyncMock(side_effect=[TimeoutError("secret endpoint"), evidence("new_source")])) as rag:
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
        self.assertEqual(rag.await_count, 2)
        self.assertEqual(result["correction_count"], 1)
        context = json.loads(control.ainvoke.await_args_list[1].args[0][1].content)
        self.assertEqual(context["observations"][0]["failures"], {"source": "tool_error"})
        self.assertNotIn("secret endpoint", json.dumps(result))

    async def test_same_strategy_with_new_id_or_executor_is_not_executed_again(self):
        tasks = [DelegatedTask(task_id="new_source", subagent="search", instruction="find")]
        for second in (retrieve(tid="new_source"), delegate(tasks)):
            model, control = llm([retrieve(), second])
            with self.subTest(action=second.action), patch.object(agent, "get_llm", return_value=model), \
                 patch.object(actions, "retrieve_evidence", AsyncMock(return_value=evidence("source"))) as rag, \
                 patch.object(runtime, "search_worker_node", AsyncMock()) as child:
                result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
            self.assertIn("停止重复执行", result["final_reply"])
            self.assertEqual(rag.await_count, 1)
            child.assert_not_awaited()
            self.assertEqual(result["citations"], [])

    async def test_partial_success_is_reused_and_failed_dependents_never_execute(self):
        first = [DelegatedTask(task_id="a", subagent="search", instruction="A"),
                 DelegatedTask(task_id="b", subagent="search", instruction="B"),
                 DelegatedTask(task_id="blocked", subagent="analysis", instruction="needs A", depends_on=["a"], requires_evidence=True)]
        recovery = DelegatedTask(task_id="recover", subagent="analysis", instruction="use B instead", depends_on=["b"], requires_evidence=True)
        model, control = llm([delegate(first), delegate([recovery]),
                              MainDecision(action="answer", reply="recovered [b:1]", answer_dependencies=["recover"])])
        async def search(state):
            return search_result(state["task_id"], "insufficient_evidence" if state["task_id"] == "a" else "succeeded")
        async def analysis(state):
            self.assertEqual(state["task_id"], "recover")
            self.assertEqual(set(json.loads(state["dependency_context"])), {"b"})
            return {"worker_results": [{"worker_name": "analysis", "result": "recovered [b:1]"}]}
        with patch.object(agent, "get_llm", return_value=model), patch.object(runtime, "search_worker_node", AsyncMock(side_effect=search)) as searches, \
             patch.object(runtime, "analysis_worker_node", AsyncMock(side_effect=analysis)) as analyses:
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "compare", []))
        self.assertEqual(searches.await_count, 2)
        self.assertEqual(analyses.await_count, 1)
        self.assertEqual(result["task_results"]["blocked"]["status"], "blocked")
        self.assertEqual(result["correction_count"], 1)
        next_context = json.loads(control.ainvoke.await_args_list[1].args[0][1].content)
        self.assertEqual(set(next_context["successful_tasks"]), {"b"})

    async def test_ready_dependency_runs_before_unrelated_slow_task(self):
        c_started = asyncio.Event()
        plan = [DelegatedTask(task_id="a", subagent="search", instruction="A"),
                DelegatedTask(task_id="b", subagent="search", instruction="slow B"),
                DelegatedTask(task_id="c", subagent="analysis", instruction="C", depends_on=["a"], requires_evidence=True)]
        async def search(state):
            if state["task_id"] == "b":
                await asyncio.wait_for(c_started.wait(), 2)
            return search_result(state["task_id"])
        async def analysis(state):
            c_started.set()
            return {"worker_results": [{"worker_name": "analysis", "result": "C [a:1]"}]}
        model, _ = llm([delegate(plan), MainDecision(action="answer", reply="C [a:1]", answer_dependencies=["c"])])
        with patch.object(agent, "get_llm", return_value=model), patch.object(runtime, "search_worker_node", search), \
             patch.object(runtime, "analysis_worker_node", analysis), patch.object(agent.settings, "SUBAGENT_CONCURRENCY", 2):
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "compare", []))
        self.assertTrue(c_started.is_set())
        self.assertTrue(all(r["status"] == "succeeded" for r in result["task_results"].values()))

    async def test_concurrency_is_limited_by_code(self):
        running, maximum = 0, 0
        async def search(state):
            nonlocal running, maximum
            running += 1
            maximum = max(maximum, running)
            await asyncio.sleep(0.01)
            running -= 1
            return search_result(state["task_id"])
        tasks = [DelegatedTask(task_id=f"t{i}", subagent="search", instruction=f"topic {i}") for i in range(5)]
        model, _ = llm([delegate(tasks), MainDecision(action="answer", reply="done")])
        with patch.object(agent, "get_llm", return_value=model), patch.object(runtime, "search_worker_node", search), \
             patch.object(agent.settings, "SUBAGENT_CONCURRENCY", 2):
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "research", []))
        self.assertEqual(maximum, 2)
        self.assertEqual(len(result["task_results"]), 5)

    async def test_round_task_and_context_budgets_stop_before_more_execution(self):
        cases = [("MAIN_MAX_ROUNDS", 1, "轮数上限"), ("MAIN_MAX_TASKS", 1, "任务数量上限"),
                 ("MAIN_CONTEXT_MAX_CHARS", 1, "处理预算")]
        for setting, limit, message in cases:
            model, _ = llm([retrieve("first"), retrieve("changed", "second")])
            with self.subTest(setting=setting), patch.object(agent, "get_llm", return_value=model), \
                 patch.object(agent.settings, setting, limit), patch.object(actions, "retrieve_evidence", AsyncMock(return_value=evidence("source"))) as rag:
                result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
            self.assertIn(message, result["final_reply"])
            self.assertEqual(rag.await_count, 0 if setting == "MAIN_CONTEXT_MAX_CHARS" else 1)

    async def test_malformed_decision_is_repaired_once_without_executing_invalid_action(self):
        invalid_decisions = [{"action": "answer", "reply": "bad", "user_id": 99},
            {"action": "delegate", "delegation_reason": "isolated analysis", "plan": {"tasks": [
                {"task_id": "analysis", "subagent": "analysis", "instruction": "analyze", "allow_web": True}]}}]
        for invalid in invalid_decisions:
            model, control = llm([invalid, MainDecision(action="answer", reply="fixed")])
            with self.subTest(invalid=invalid), patch.object(agent, "get_llm", return_value=model), \
                 patch.object(runtime, "search_worker_node", AsyncMock()) as search, \
                 patch.object(runtime, "analysis_worker_node", AsyncMock()) as analysis:
                result, nodes = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "hello", []))
            self.assertEqual(control.ainvoke.await_count, 2)
            self.assertEqual(result["main_round"], 1)
            self.assertEqual(result["user_id"], 7)
            self.assertEqual(result["final_reply"], "fixed")
            self.assertEqual(nodes, ["main_agent", "final_gate"])
            search.assert_not_awaited()
            analysis.assert_not_awaited()

    async def test_source_or_permission_failures_do_not_enter_recovery(self):
        model, control = llm([retrieve(), MainDecision(action="answer", reply="unsafe")])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(actions, "retrieve_evidence", AsyncMock(side_effect=ValueError("source or permission changed"))):
            with self.assertRaisesRegex(ValueError, "source or permission changed"):
                await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
        self.assertEqual(control.ainvoke.await_count, 1)

    async def test_cancellation_cancels_other_running_subagents(self):
        sibling_started, sibling_cancelled = asyncio.Event(), asyncio.Event()
        async def search(state):
            if state["task_id"] == "a":
                await sibling_started.wait()
                raise asyncio.CancelledError()
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                sibling_cancelled.set()
                raise
        tasks = [DelegatedTask(task_id="a", subagent="search", instruction="A"), DelegatedTask(task_id="b", subagent="search", instruction="B")]
        model, control = llm([delegate(tasks)])
        with patch.object(agent, "get_llm", return_value=model), patch.object(runtime, "search_worker_node", search):
            with self.assertRaises(NodeCancelledError):
                await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
        self.assertTrue(sibling_cancelled.is_set())
        self.assertEqual(control.ainvoke.await_count, 1)

    async def test_main_artifact_repairs_in_decision_without_spending_strategy_recovery(self):
        task = DelegatedTask(task_id="consumer", subagent="analysis", instruction="use comparison", depends_on=["comparison"], requires_evidence=True)
        def decision(body):
            return MainDecision(action="delegate", plan=DependencyPlan(tasks=[task]), delegation_reason="isolated specialist context",
                artifacts=[MainArtifact(task_id="comparison", instruction="compare", result=body,
                                        depends_on=["source"], requires_evidence=True)])
        model, control = llm([retrieve(), decision("bad [fake:1]"), agent.CitationRepair(artifacts=[
            agent.ArtifactCitationRepair(task_id="comparison", result="fixed [source:1]")]),
                              MainDecision(action="answer", reply="final [source:1]", answer_dependencies=["consumer"])])
        async def consume(state):
            self.assertEqual(set(json.loads(state["dependency_context"])), {"comparison"})
            self.assertIn("fixed [source:1]", state["dependency_context"])
            return {"worker_results": [{"worker_name": "analysis", "result": "final [source:1]"}]}
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(actions, "retrieve_evidence", AsyncMock(return_value=evidence("source"))) as rag, \
             patch.object(runtime, "analysis_worker_node", AsyncMock(side_effect=consume)) as child:
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "analyze", []))
        self.assertEqual(rag.await_count, 1)
        self.assertEqual(control.ainvoke.await_count, 4)  # retrieve, decision + citation repair, final answer
        model.ainvoke.assert_not_awaited()
        self.assertEqual(child.await_count, 1)
        self.assertEqual(result["task_results"]["comparison"]["actor"], "main")
        self.assertEqual(result["correction_count"], 0)

    async def test_transport_error_allows_one_same_parameter_retry_then_stops(self):
        for retry_result, succeeds in [(evidence("retry"), True), (TimeoutError("private"), False)]:
            model, control = llm([retrieve(), retrieve(tid="retry"), MainDecision(action="answer", reply="found [retry:1]")])
            with self.subTest(succeeds=succeeds), patch.object(agent, "get_llm", return_value=model), \
                 patch.object(actions, "retrieve_evidence", AsyncMock(side_effect=[TimeoutError("private"), retry_result])) as rag:
                result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
            self.assertEqual(rag.await_count, 2)
            self.assertEqual(control.ainvoke.await_count, 3 if succeeds else 2)
            self.assertEqual(result["correction_count"], 1 if succeeds else 2)
            self.assertEqual(result["action_history"][1]["tasks"][0]["instruction"], "find")
            self.assertEqual(result["action_history"][0]["fingerprints"], result["action_history"][1]["fingerprints"])
            if not succeeds:
                self.assertIn("停止自动重试", result["final_reply"])

    async def test_main_receives_complete_results_and_citation_excerpts(self):
        source = evidence("source")
        source["rag_context"] = "x" * 3500 + "重要尾部资料 [source:1]"
        source["citations"][0]["excerpt"] = "y" * 800 + "原始证据尾部"
        model, control = llm([retrieve(), MainDecision(action="answer", reply="解释 [source:1]")])
        with patch.object(agent, "get_llm", return_value=model), patch.object(actions, "retrieve_evidence", AsyncMock(return_value=source)):
            await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
        context = json.loads(control.ainvoke.await_args_list[1].args[0][1].content)
        self.assertEqual(context["successful_tasks"]["source"]["result"], source["rag_context"])
        self.assertEqual(context["successful_tasks"]["source"]["citations"], source["citations"])

    async def test_context_overflow_preserves_complete_outputs_without_another_model_call(self):
        source = evidence("source")
        source["rag_context"] = "x" * 15000 + "尾部 [source:1]"
        model, control = llm([retrieve()])
        # Keep the initial request inside the guard as the decision schema grows;
        # the retrieved document must overflow it without being truncated.
        from app.utils.context_budget import json_text
        from langchain_core.utils.function_calling import convert_to_openai_tool
        initial = create_initial_state(7, "find", [])
        baseline = sum(len(json_text(m.content)) for m in agent.main_message_renderer(initial)([]))
        baseline += len(json_text(convert_to_openai_tool(MainDecision)))
        with patch.object(agent, "get_llm", return_value=model), patch.object(agent.settings, "MAIN_CONTEXT_MAX_CHARS", baseline + 4000), \
             patch.object(actions, "retrieve_evidence", AsyncMock(return_value=source)):
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
        self.assertIn("处理预算", result["final_reply"])
        self.assertEqual(result["task_results"]["source"]["result"], source["rag_context"])
        self.assertEqual(control.ainvoke.await_count, 1)

    async def test_successful_transport_retry_cannot_be_repeated_a_third_time(self):
        model, control = llm([retrieve(), retrieve(tid="retry"), retrieve(tid="third")])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(actions, "retrieve_evidence", AsyncMock(side_effect=[TimeoutError(), evidence("retry")])) as rag:
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
        self.assertIn("停止重复执行", result["final_reply"])
        self.assertEqual(rag.await_count, 2)
        self.assertEqual(control.ainvoke.await_count, 3)

    async def test_artifacts_and_pending_tasks_share_budget_and_commit_atomically(self):
        decision = retrieve("next")
        decision.artifacts = [MainArtifact(task_id="notes", instruction="整理需求", result="已经整理的需求")]
        model, _ = llm([decision])
        with patch.object(agent, "get_llm", return_value=model), patch.object(agent.settings, "MAIN_MAX_TASKS", 1), \
             patch.object(actions, "retrieve_evidence", AsyncMock()) as rag:
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
        self.assertIn("任务数量上限", result["final_reply"])
        self.assertEqual(result["task_results"], {})
        rag.assert_not_awaited()

    async def test_artifact_citation_repair_cannot_change_external_request(self):
        artifact = MainArtifact(task_id="notes", instruction="整理", result="bad [fake:1]")
        first = MainDecision(action="retrieve", retrieval=RetrievalRequest(instruction="original"), artifacts=[artifact])
        second = {"action": "retrieve", "retrieval": {"instruction": "changed"},
                  "artifacts": [{"task_id": "notes", "result": "fixed"}]}
        model, _ = llm([first, second])
        with patch.object(agent, "get_llm", return_value=model), patch.object(actions, "retrieve_evidence", AsyncMock()) as rag:
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
        self.assertIn("回答引用未通过校验", result["final_reply"])
        self.assertEqual(result["task_results"], {})
        rag.assert_not_awaited()

    async def test_reject_is_terminal_and_does_not_call_model_or_save_again(self):
        task = DraftRequest(task_id="draft", instruction="write")
        model, control = llm([MainDecision(action="write_draft", draft_request=task)])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(writing_worker, "generate_draft", AsyncMock(return_value=DraftOutput(title="A", summary="S", content="text"))) as generate, \
             patch.object(writing_worker, "save_approved_draft", AsyncMock()) as save:
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            config = {"configurable": {"thread_id": "reject-loop"}}
            await graph.ainvoke(create_initial_state(7, "write", []), config)
            preview = (await graph.aget_state(config)).tasks[0].interrupts[0].value
            await graph.ainvoke(Command(resume={"action": "reject", "runId": "", "draftHash": preview["draftHash"]}), config)
            result = (await graph.aget_state(config)).values
        self.assertEqual(result["final_reply"], "用户取消了草稿保存。")
        self.assertTrue(result["business_complete"])
        self.assertEqual(control.ainvoke.await_count, 1)
        self.assertEqual(generate.await_count, 1)
        save.assert_not_awaited()
