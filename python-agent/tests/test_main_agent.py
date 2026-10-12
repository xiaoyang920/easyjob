"""Verify adaptive routing on the production graph without network calls."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
os.environ["AGENT_SERVICE_KEY"] = "offline-service-key-32-bytes-long!!"

import hashlib
import json
import unittest
from grounding_fakes import setUpModule, tearDownModule
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.graph import builder, main_agent as agent, staged_runtime as runtime, action_runtime as actions
from app.graph.nodes import search_worker, writing_worker
from app.graph.main_agent import MainArtifact, MainDecision, RetrievalRequest, CitationRepair, ArtifactCitationRepair
from app.graph.staged_plan import DependencyPlan, DelegatedTask, DraftRequest, ExecutionTask
from app.graph.state_factory import create_initial_state
from app.models.draft import DraftOutput
from app.services import evidence_verifier
from app.services.query_rewrite import QueryFilters, ResolvedFilters
from fakes import repository, RUN_ID, article_chunk
from app.models.evidence_assessment import EvidenceAssessment


def llm(decisions, replies=()):
    control = SimpleNamespace(ainvoke=AsyncMock(side_effect=decisions))
    model = SimpleNamespace(with_structured_output=Mock(return_value=control),
                            ainvoke=AsyncMock(side_effect=[SimpleNamespace(content=r) for r in replies]))
    return model, control


def evidence(tid="main"):
    return {"status": "succeeded", "rag_context": f"[{tid}:1] verified source",
            "citations": [{"id": f"{tid}:1", "articleId": "42", "title": "source", "excerpt": "verified source"}],
            "article_cards": [{"articleId": "42", "title": "source"}]}


async def run_updates(graph, state, thread="adaptive"):
    config = {"configurable": {"thread_id": thread}, "recursion_limit": 80}
    nodes = []
    async for update in graph.astream(state, config, stream_mode="updates"):
        nodes.extend(update)
    return (await graph.aget_state(config)).values, nodes


class DecisionTests(unittest.TestCase):
    def test_mixed_actions_missing_reason_and_model_identity_are_rejected(self):
        plan = DependencyPlan(tasks=[DelegatedTask(task_id="a", subagent="search", instruction="research")])
        cases = [dict(action="answer", reply=""),
                 dict(action="answer", reply="hello", plan=plan),
                 dict(action="retrieve"),
                 dict(action="analyze", plan=plan),
                 dict(action="delegate", plan=plan),
                 dict(action="answer", reply="hello", user_id=99),
                 dict(action="delegate", delegation_reason="isolated analysis", plan={"tasks": [
                     {"task_id": "analysis", "subagent": "analysis", "instruction": "analyze", "allow_web": True}]}),
                 dict(action="delegate", delegation_reason="chat", plan={"tasks": [
                     {"task_id": "chat", "subagent": "chat", "instruction": "hello"}]})]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                MainDecision.model_validate(case)

    def test_only_delegate_accepts_subagent_and_draft_request_has_no_execution_identity(self):
        request = DraftRequest(task_id="draft", instruction="write")
        decision = MainDecision(action="write_draft", draft_request=request)
        self.assertEqual(decision.draft_request, request)
        self.assertNotIn("task", decision.model_dump())
        self.assertNotIn("subagent", decision.draft_request.model_dump())
        for extra in ({"subagent": "writing"}, {"kind": "writing"}, {"actor": "main"},
                      {"allow_web": True}, {"capabilities": {"tools": ["save_draft"]}}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                DraftRequest(task_id="draft", instruction="write", **extra)
        for extra in ({"actor": "main"}, {"kind": "writing"},
                      {"capabilities": {"tools": ["save_draft"]}}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                DelegatedTask(task_id="search", subagent="search", instruction="find", **extra)
        with self.assertRaises(ValueError):
            MainDecision(action="write_draft", task={"task_id": "draft", "instruction": "write", "subagent": "writing"})


class MainArtifactTests(unittest.TestCase):
    def state(self):
        state = create_initial_state(7, "compare", [])
        state["task_results"] = {"source": {"task_id": "source", "kind": "search", "actor": "main", "instruction": "find",
            "status": "succeeded", "result": "source [source:1]", "citations": evidence("source")["citations"],
            "article_cards": evidence("source")["article_cards"]}}
        return state

    def test_artifact_chain_accumulates_without_mutating_existing_state(self):
        state = self.state()
        artifacts = [MainArtifact(task_id="comparison", instruction="compare", result="comparison [source:1]",
                                 depends_on=["source"], requires_evidence=True),
                     MainArtifact(task_id="outline", instruction="outline", result="outline [source:1]",
                                 depends_on=["comparison"], requires_evidence=True)]
        outputs = agent.prepare_artifacts(state, artifacts)
        self.assertEqual(set(outputs), {"comparison", "outline"})
        self.assertEqual(set(state["task_results"]), {"source"})
        self.assertEqual(outputs["outline"]["citations"], evidence("source")["citations"])
        self.assertEqual(outputs["outline"]["actor"], "main")
        self.assertEqual(outputs["outline"]["kind"], "analysis")
        self.assertTrue(all("subagent" not in output for output in outputs.values()))

    def test_artifact_cannot_overwrite_or_consume_failed_future_or_undeclared_evidence(self):
        state = self.state()
        state["task_results"]["failed"] = {**state["task_results"]["source"], "status": "tool_error"}
        cases = [dict(task_id="source", result="overwrite"),
                 dict(task_id="new", result="new", depends_on=["future"]),
                 dict(task_id="new", result="new", depends_on=["failed"]),
                 dict(task_id="new", result="new", depends_on=["source", "source"]),
                 dict(task_id="new", result="new", requires_evidence=True),
                 dict(task_id="new", result="undeclared [source:1]"),
                 dict(task_id="new", result="   ")]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                agent.prepare_artifacts(state, [MainArtifact(instruction="compare", **case)])
        self.assertEqual(set(state["task_results"]), {"source", "failed"})

    def test_removed_action_and_model_supplied_artifact_identity_or_citations_are_rejected(self):
        with self.assertRaises(ValueError):
            MainDecision(action="analyze", task=DelegatedTask(task_id="a", subagent="analysis", instruction="analyze"))
        for extra in ({"user_id": 99}, {"citations": evidence()["citations"]},
                      {"subagent": "analysis"}, {"actor": "subagent"}, {"kind": "search"},
                      {"capabilities": {"tools": ["save_draft"]}}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                MainArtifact(task_id="notes", instruction="整理", result="正文", **extra)


class MainAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_writing_evidence_dependency_is_repaired_before_draft_generation(self):
        bad = MainDecision(action="write_draft", draft_request=DraftRequest(
            task_id="draft", instruction="写一篇 Agent 开发文章", requires_evidence=True))
        good = MainDecision(action="write_draft", draft_request=DraftRequest(
            task_id="draft", instruction="写一篇通用知识原创文章", requires_evidence=False))
        for decisions, calls in [([good], 1), ([bad, good], 2)]:
            with self.subTest(calls=calls):
                model, control = llm(decisions)
                state = create_initial_state(7, "帮我写一篇，agent开发的文章", [])
                with patch.object(agent, "get_llm", return_value=model), \
                     patch.object(writing_worker, "generate_draft", AsyncMock(return_value=DraftOutput(
                         title="Agent 开发入门", summary="原创概念介绍", content="从决策、工具与状态开始。"))) as generate, \
                     patch.object(writing_worker, "save_approved_draft", AsyncMock()) as save:
                    graph = builder._build_graph().compile(checkpointer=InMemorySaver())
                    config = {"configurable": {"thread_id": f"draft-contract-{calls}"}, "recursion_limit": 80}
                    await graph.ainvoke(state, config)
                    snap = await graph.aget_state(config)
                self.assertTrue(snap.tasks[0].interrupts)
                self.assertEqual(snap.tasks[0].interrupts[0].value["title"], "Agent 开发入门")
                self.assertEqual(snap.values["main_round"], 1)
                self.assertEqual(len(snap.values["action_history"]), 1)
                self.assertEqual(control.ainvoke.await_count, calls)
                generate.assert_awaited_once()
                save.assert_not_awaited()
                if calls == 2:
                    self.assertIn("有据分析或写作必须声明证据依赖", control.ainvoke.call_args.args[0][-1].content)

    async def test_invalid_task_contracts_stop_after_one_repair_without_side_effects(self):
        cases = [
            MainDecision(action="write_draft", draft_request=DraftRequest(
                task_id="draft", instruction="write", requires_evidence=True)),
            MainDecision(action="write_draft", draft_request=DraftRequest(
                task_id="draft", instruction="write", depends_on=["missing"])),
            MainDecision(action="write_draft", draft_request=DraftRequest(
                task_id="draft", instruction="write", required_skills=["unregistered-test-skill"])),
            MainDecision(action="delegate", delegation_reason="independent work", plan=DependencyPlan(tasks=[
                DelegatedTask(task_id="a", subagent="analysis", instruction="a", depends_on=["b"]),
                DelegatedTask(task_id="b", subagent="analysis", instruction="b", depends_on=["a"])])),
            MainDecision(action="delegate", delegation_reason="independent work", plan=DependencyPlan(tasks=[
                DelegatedTask(task_id="a", subagent="search", instruction="a"),
                DelegatedTask(task_id="a", subagent="search", instruction="b")]))]
        for bad in cases:
            with self.subTest(decision=bad.model_dump()):
                model, control = llm([bad, bad])
                state = create_initial_state(7, "write", [])
                with patch.object(agent, "get_llm", return_value=model), \
                     patch.object(actions, "run_subagent", AsyncMock()) as worker, \
                     patch.object(writing_worker, "generate_draft", AsyncMock()) as generate, \
                     patch.object(agent.memory_policy_service, "enqueue_changes", AsyncMock()) as memory:
                    result, nodes = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), state)
                self.assertIn("本轮动作格式未通过校验", result["final_reply"])
                self.assertEqual(control.ainvoke.await_count, 2)
                self.assertEqual(nodes, ["main_agent", "final_gate"])
                self.assertFalse(result["action_history"])
                worker.assert_not_awaited()
                generate.assert_not_awaited()
                memory.assert_not_awaited()

    async def test_evidence_writing_can_repair_to_retrieve_without_dropping_evidence_requirement(self):
        model, control = llm([
            MainDecision(action="write_draft", draft_request=DraftRequest(
                task_id="draft", instruction="基于站内文章写作", requires_evidence=True)),
            MainDecision(action="retrieve", retrieval=RetrievalRequest(
                task_id="sources", instruction="查找 Agent 开发资料"))])
        state = create_initial_state(7, "基于站内文章写一篇 Agent 开发文章", [])
        with patch.object(agent, "get_llm", return_value=model):
            result = await agent.decide_main_action(state)
        self.assertEqual(result["main_action"], "retrieve")
        self.assertTrue(result["plan"]["tasks"][0]["requires_evidence"])
        self.assertEqual(result["main_round"], 1)
        self.assertEqual(len(result["action_history"]), 1)
        self.assertEqual(control.ainvoke.await_count, 2)

    async def test_failed_local_citation_repair_preserves_independent_work_and_blocks_dependents(self):
        state = create_initial_state(7, 'compare', [])
        state.update(main_round=1, main_action='delegate', plan={'tasks': [
            {'task_id': 'bad', 'kind': 'analysis', 'actor': 'subagent', 'instruction': 'a'},
            {'task_id': 'good', 'kind': 'analysis', 'actor': 'subagent', 'instruction': 'b'},
            {'task_id': 'dependent', 'kind': 'analysis', 'actor': 'subagent', 'instruction': 'c', 'depends_on': ['bad']}]})
        async def run(context, task):
            result = actions.failed_result(task, 'invalid_citation' if task.task_id == 'bad' else 'succeeded',
                                           'unsafe [fake:1]' if task.task_id == 'bad' else 'usable analysis')
            result['citations'] = [{'id': 'fake:1'}] if task.task_id == 'bad' else []
            return {task.task_id: result}
        with patch.object(actions, 'run_subagent', AsyncMock(side_effect=run)) as runner:
            result = await actions.main_delegate_node(state)
        outputs = result['task_results']
        self.assertEqual(outputs['good']['result'], 'usable analysis')
        self.assertEqual(outputs['bad']['status'], 'invalid_citation')
        self.assertEqual(outputs['bad']['citations'], [])
        self.assertNotIn('unsafe', outputs['bad']['result'])
        self.assertEqual(outputs['dependent']['status'], 'blocked')
        self.assertEqual(runner.await_count, 2)
        self.assertEqual(result['correction_count'], 1)

    async def test_invalid_answer_dependency_is_repaired_before_execution(self):
        bad = MainDecision(action='answer', reply='unavailable', answer_dependencies=['failed'])
        for second, expected in [(MainDecision(action='answer', reply='没有可用资料'), '没有可用资料'),
                                 (bad, '本轮动作格式未通过校验')]:
            model, control = llm([bad, second])
            state = create_initial_state(7, 'find', [])
            state['task_results'] = {'failed': {'status': 'insufficient_evidence'}}
            with patch.object(agent, 'get_llm', return_value=model):
                result = await agent.decide_main_action(state)
            self.assertIn(expected, result['final_reply'])
            self.assertEqual(control.ainvoke.await_count, 2)

    async def test_retrieved_source_without_reference_defers_classification_to_final_gate(self):
        for reply in ('source https://example.org', '缓存用于减少重复访问'):
            model, control = llm([MainDecision(action='answer', reply=reply)])
            state = create_initial_state(7, 'search the web', [])
            state['task_results'] = {'web': {**evidence('web'), 'retrieval_target': 'knowledge',
                'retrieval_report': {'quality': {'adequacy': 'partial'}}}}
            with patch.object(agent, 'get_llm', return_value=model):
                result = await agent.decide_main_action(state)
            self.assertEqual(result['final_reply'], reply)
            self.assertEqual(control.ainvoke.await_count, 1)
            self.assertIsNone(result['citations'])
            self.assertEqual(result['delivery_evidence']['citations'], evidence('web')['citations'])

    async def test_irrelevant_retrieval_does_not_force_citation_on_no_results_answer(self):
        model, control = llm([MainDecision(action='answer', reply='没有找到相关资料')])
        state = create_initial_state(7, 'find', [])
        state['task_results'] = {'web': {**evidence('web'),
            'retrieval_report': {'quality': {'adequacy': 'none'}}}}
        with patch.object(agent, 'get_llm', return_value=model):
            result = await agent.decide_main_action(state)
        self.assertIsNone(result['citations'])
        self.assertEqual(control.ainvoke.await_count, 1)

    async def test_simple_answer_is_one_model_call_without_planner_or_subagent(self):
        model, control = llm([MainDecision(action="answer", reply="你好，有什么可以帮你？")])
        state = create_initial_state(7, "你好", [{"role": "user", "content": "previous"}])
        state["memory_context"] = "untrusted memory"
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(runtime, "search_worker_node", AsyncMock()) as search:
            result, nodes = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), state)
        self.assertEqual(nodes, ["main_agent", "final_gate"])
        self.assertEqual(control.ainvoke.await_count, 1)
        model.ainvoke.assert_not_awaited()
        self.assertEqual(model.with_structured_output.call_args.args[0], MainDecision)
        self.assertEqual(result["final_reply"], "你好，有什么可以帮你？")
        context = json.loads(control.ainvoke.call_args.args[0][1].content)
        self.assertEqual(context["memory"], "untrusted memory")
        self.assertEqual(context["history"], state["history_messages"])
        search.assert_not_awaited()

    async def test_direct_retrieval_uses_shared_rag_and_final_source_recheck(self):
        decision = MainDecision(action="retrieve", retrieval=RetrievalRequest(instruction="find RAG articles"))
        decision.retrieval.task_id = "main"
        model, control = llm([decision, MainDecision(action="answer", reply="回答 [main:1]",
            evidence_assessment=EvidenceAssessment(selected_ids=['main:1'], adequacy='sufficient', reason='正文覆盖目标'))])
        source = "<p>current public evidence</p>"
        source_row = SimpleNamespace(_mapping={"article_id": 42, "title": "RAG", "content": source})
        db = SimpleNamespace(fetch_all=AsyncMock(return_value=[source_row]))
        rewrite = SimpleNamespace(rewrite_request=AsyncMock(return_value={"semantic_queries": ["RAG"], "keywords": ["RAG"],
            "filters": QueryFilters(), "search_mode": "hybrid", "need_web_search": True}))
        resolver = SimpleNamespace(resolve=AsyncMock(return_value=ResolvedFilters()))
        retrieval = SimpleNamespace(hybrid_search=AsyncMock(return_value=[article_chunk()]))
        reranker = SimpleNamespace(rerank=AsyncMock(side_effect=lambda query, docs: docs))
        state = create_initial_state(7, "找几篇相关的", [{"role": "user", "content": "RAG"}])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(search_worker, "db", db), patch.object(evidence_verifier, "db", db), \
             patch.object(search_worker, "query_rewrite_service", rewrite), \
             patch.object(search_worker, "filter_resolver_instance", resolver), \
             patch.object(search_worker, "retrieval_service_instance", retrieval), \
             patch.object(search_worker, "reranker_service", reranker), \
             patch.object(search_worker, "do_search", AsyncMock()) as web, \
             patch.object(runtime, "subagent_node", AsyncMock()) as subagent:
            result, nodes = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), state)
        self.assertEqual(nodes, ["main_agent", "main_retrieve", "main_agent", "final_gate"])
        self.assertEqual(control.ainvoke.await_count, 2)
        model.ainvoke.assert_not_awaited()
        context = json.loads(control.ainvoke.call_args.args[0][1].content)
        self.assertIn("current public evidence", context["successful_tasks"]["main"]["result"])
        self.assertEqual(context["observations"][0]["tasks"], {"main": "succeeded"})
        self.assertEqual(retrieval.hybrid_search.await_count, 1)
        # Retrieval + final gate before and after the potentially awaited audit.
        self.assertEqual(db.fetch_all.await_count, 3)
        self.assertEqual(rewrite.rewrite_request.call_args.args[2], state["history_messages"])
        self.assertEqual(result["citations"][0]["sourceHash"], hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(result["citations"][0]["excerpt"], "current public evidence")
        self.assertEqual(result["article_cards"][0]["articleId"], "42")
        web.assert_not_awaited()
        subagent.assert_not_awaited()

    async def test_empty_retrieval_returns_observation_and_main_can_explain_insufficiency(self):
        model, control = llm([MainDecision(action="retrieve", retrieval=RetrievalRequest(instruction="find")),
                              MainDecision(action="answer", reply="没有可用资料")])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(actions, "retrieve_evidence", AsyncMock(return_value={"status": "insufficient_evidence",
                 "result": "没有可用资料", "citations": [], "article_cards": [], "rag_context": ""})) as retrieve:
            result, nodes = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
        self.assertEqual(result["final_reply"], "没有可用资料")
        self.assertEqual(nodes, ["main_agent", "main_retrieve", "main_agent", "final_gate"])
        self.assertEqual(retrieve.await_count, 1)
        model.ainvoke.assert_not_awaited()

    async def test_gap_driven_second_retrieval_reuses_sources_in_three_main_calls(self):
        def assess(ids, adequacy, gaps=()):
            return EvidenceAssessment(selected_ids=ids, adequacy=adequacy, reason='按用户目标核对正文', missing_aspects=list(gaps))
        decisions = [MainDecision(action='retrieve', retrieval=RetrievalRequest(task_id='principle',
                         instruction='缓存一致性原理', search_query='Cache Aside 原理', filters={})),
                     MainDecision(action='retrieve', evidence_assessment=assess(['principle:1'], 'partial', ['删除失败补偿']),
                         retrieval=RetrievalRequest(task_id='recovery', instruction='补充删除失败补偿',
                             search_query='缓存删除失败 重试补偿', filters={})),
                     MainDecision(action='answer', reply='原理 [principle:1]；补偿 [recovery:1]',
                         evidence_assessment=assess(['principle:1', 'recovery:1'], 'sufficient'))]
        model, control = llm(decisions)
        def retrieved(tid):
            return {**evidence(tid), 'retrieval_report': {'assessment_owner': 'main',
                    'platform': {'status': 'found'}, 'web': {'status': 'not_requested'}}}
        with patch.object(agent, 'get_llm', return_value=model), \
             patch.object(actions, 'retrieve_evidence', AsyncMock(side_effect=[retrieved('principle'), retrieved('recovery')])) as retrieve:
            result, nodes = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()),
                create_initial_state(7, '解释缓存一致性并说明删除失败补偿', []))
        self.assertEqual(control.ainvoke.await_count, 3)
        self.assertEqual(retrieve.await_count, 2)
        self.assertEqual(nodes.count('main_retrieve'), 2)
        self.assertEqual(set(result['task_results']), {'principle', 'recovery'})
        self.assertEqual([c['id'] for c in result['citations']], ['principle:1', 'recovery:1'])
        final_context = json.loads(control.ainvoke.await_args_list[-1].args[0][1].content)
        self.assertEqual(final_context['previous_evidence_assessment']['missing_aspects'], ['删除失败补偿'])
        self.assertEqual(result['action_history'][1]['evidence_assessment']['adequacy'], 'partial')
        self.assertEqual(result['correction_count'], 0)

    async def test_empty_source_body_never_reaches_search_generation(self):
        rewrite = {"semantic_queries": ["q"], "keywords": ["q"], "filters": QueryFilters()}
        state = runtime.task_context(create_initial_state(7, "find", []),
            ExecutionTask(task_id="find", kind="search", actor="main", instruction="find"))
        with patch.object(search_worker.query_rewrite_service, "rewrite", AsyncMock(return_value=rewrite)), \
             patch.object(search_worker.filter_resolver_instance, "resolve", AsyncMock(return_value=ResolvedFilters())), \
             patch.object(search_worker.retrieval_service_instance, "hybrid_search", AsyncMock(return_value=[{"article_id": "42"}])), \
             patch.object(search_worker, "_verify_candidates_from_mysql", AsyncMock(return_value=[{"article_id": "42", "content": ""}])), \
             patch.object(search_worker.reranker_service, "rerank", AsyncMock(side_effect=lambda q, docs: docs)), \
             patch.object(search_worker, "run_tool_agent", AsyncMock()) as generate:
            result = await search_worker.search_worker_node(state)
        self.assertEqual(result["worker_results"][0]["status"], "insufficient_evidence")
        self.assertEqual(result["citations"], [])
        generate.assert_not_awaited()

    async def test_citation_correction_reuses_retrieval_and_invalid_final_is_rejected(self):
        for replies, fails in [(["bad [unknown:1]", "fixed [main:1]"], False),
                               (["bad [unknown:1]"] * 2, True)]:
            model, control = llm([MainDecision(action="retrieve", retrieval=RetrievalRequest(task_id="main", instruction="find")),
                                  MainDecision(action="answer", reply=replies[0], answer_dependencies=["main"]),
                                  CitationRepair(reply=replies[1])])
            with self.subTest(fails=fails), patch.object(agent, "get_llm", return_value=model), \
                 patch.object(actions, "retrieve_evidence", AsyncMock(return_value=evidence())) as retrieve:
                graph = builder._build_graph().compile(checkpointer=InMemorySaver())
                result, _ = await run_updates(graph, create_initial_state(7, "find", []))
                if fails:
                    self.assertIn("回答引用未通过校验", result["final_reply"])
                    self.assertTrue(result["stop_reason"])
                    self.assertEqual(result["citations"], [])
                    self.assertNotIn("unknown:1", result["final_reply"])
                else:
                    self.assertEqual(result["final_reply"], "fixed [main:1]")
                    self.assertEqual(result["main_decision"]["answer_dependencies"], ["main"])
            self.assertEqual(model.with_structured_output.call_args.args[0], CitationRepair)
            self.assertEqual(retrieve.await_count, 1)
            self.assertEqual(control.ainvoke.await_count, 3)
            model.ainvoke.assert_not_awaited()

    async def test_mixed_reply_retry_explains_validation_and_stops_after_two_calls(self):
        invalid = {"action": "retrieve", "retrieval": {"instruction": "find"}, "reply": "progress"}
        for second, fails in [(invalid, True), (MainDecision(action="answer", reply="fixed"), False)]:
            model, control = llm([invalid, second])
            with self.subTest(fails=fails), patch.object(agent, "get_llm", return_value=model), \
                 patch.object(actions, "retrieve_evidence", AsyncMock()) as retrieve:
                result, nodes = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
            self.assertEqual(control.ainvoke.await_count, 2)
            self.assertEqual(nodes, ["main_agent", "final_gate"])
            retrieve.assert_not_awaited()
            self.assertEqual(result["final_reply"], "本轮动作格式未通过校验，已停止执行。请重新描述目标后再试。\n\n当前未完成全部要求。" if fails else "fixed")
            self.assertIn("执行动作不能包含最终回复", control.ainvoke.await_args_list[1].args[0][-1].content)

    async def test_text_repair_preserves_request_constraints_and_artifact_dependencies(self):
        state = MainArtifactTests().state()
        decision = MainDecision(action="retrieve", retrieval=RetrievalRequest(instruction="original", allow_web=True),
            constraint_overrides=["constraint-1"], artifacts=[
                MainArtifact(task_id="notes", instruction="compare", result="bad [fake:1]", depends_on=["source"], requires_evidence=True),
                MainArtifact(task_id="outline", instruction="outline", result="bad [fake:2]", depends_on=["notes"], requires_evidence=True)])
        patch_result = CitationRepair(artifacts=[ArtifactCitationRepair(task_id=tid, result="fixed [source:1]") for tid in ("notes", "outline")])
        model, control = llm([patch_result])
        fixed = await agent.repair_citation_text(state, decision, model, [])
        before, after = decision.model_dump(), fixed.model_dump()
        for artifact in after["artifacts"]:
            artifact["result"] = next(a["result"] for a in before["artifacts"] if a["task_id"] == artifact["task_id"])
        self.assertEqual(before, after)
        self.assertEqual(fixed.artifacts[0].result, "fixed [source:1]")
        self.assertEqual(decision.artifacts[0].result, "bad [fake:1]")
        context = json.loads(control.ainvoke.await_args.args[0][1].content)
        self.assertEqual(context["artifacts"][1]["allowed_citations"], evidence("source")["citations"])
        self.assertEqual(set(agent.prepare_artifacts(state, fixed.artifacts)), {"notes", "outline"})

    async def test_text_repair_rejects_missing_duplicate_extra_ids_and_changed_action(self):
        decision = MainDecision(action="retrieve", retrieval=RetrievalRequest(instruction="original"),
            artifacts=[MainArtifact(task_id="notes", instruction="compare", result="bad [fake:1]")])
        good = ArtifactCitationRepair(task_id="notes", result="fixed")
        for output in (CitationRepair(), CitationRepair(artifacts=[good, good]),
                       CitationRepair(artifacts=[ArtifactCitationRepair(task_id="other", result="fixed")]),
                       CitationRepair(reply="unexpected", artifacts=[good]),
                       {"action": "answer", "reply": "unsafe", "artifacts": []}):
            model, _ = llm([output])
            with self.subTest(output=output), self.assertRaises(ValueError):
                await agent.repair_citation_text(create_initial_state(7, "find", []), decision, model, [])

    async def test_text_repair_timeout_stops_without_repeating_search(self):
        model, control = llm([MainDecision(action="retrieve", retrieval=RetrievalRequest(task_id="main", instruction="find")),
            MainDecision(action="answer", reply="bad [unknown:1]"), TimeoutError()])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(actions, "retrieve_evidence", AsyncMock(return_value=evidence())) as retrieve:
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "find", []))
        self.assertIn("回答引用未通过校验", result["final_reply"])
        self.assertEqual(control.ainvoke.await_count, 3)
        self.assertEqual(retrieve.await_count, 1)

    async def test_sequential_main_workflow_preserves_approval_and_resume_fencing(self):
        draft_request = DraftRequest(task_id="draft", instruction="write", depends_on=["analysis"], requires_evidence=True)
        artifact = MainArtifact(task_id="analysis", instruction="compare research", result="analysis [research:1]",
                                depends_on=["research"], requires_evidence=True)
        model, control = llm([MainDecision(action="retrieve", retrieval=RetrievalRequest(task_id="research", instruction="find")),
                              MainDecision(action="write_draft", draft_request=draft_request, artifacts=[artifact])])
        repo = repository()
        state = create_initial_state(7, "find analyze draft", [])
        state.update(run_id=RUN_ID, execution_token="first")
        config = {"configurable": {"thread_id": "workflow", "execution_token": "first"}, "recursion_limit": 80}
        with patch.object(agent, "get_llm", return_value=model), patch.object(runtime, "run_repository", repo), \
             patch.object(actions, "retrieve_evidence", AsyncMock(return_value=evidence("research"))) as retrieve, \
             patch.object(runtime, "search_worker_node", AsyncMock()) as search, \
             patch.object(runtime, "analysis_worker_node", AsyncMock()) as analysis, \
             patch.object(writing_worker, "generate_draft", AsyncMock(return_value=DraftOutput(title="A", summary="S", content="draft [research:1]"))) as draft, \
             patch.object(writing_worker, "save_approved_draft", AsyncMock(return_value=99)) as save:
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            await graph.ainvoke(state, config)
            snap = await graph.aget_state(config)
            self.assertEqual(snap.values["main_round"], 2)
            self.assertEqual(set(snap.values["task_results"]), {"research", "analysis"})
            self.assertEqual(snap.values["task_results"]["analysis"]["actor"], "main")
            self.assertEqual(snap.values["task_results"]["analysis"]["result"], artifact.result)
            preview = snap.tasks[0].interrupts[0].value
            save.assert_not_awaited()
            config["configurable"]["execution_token"] = "resumed"
            await graph.ainvoke(Command(resume={"action": "approve", "runId": RUN_ID, "draftHash": preview["draftHash"]}), config)
            snap = await graph.aget_state(config)
        self.assertEqual(snap.values["execution_mode"], "direct")
        self.assertEqual(snap.values["draft_article_id"], 99)
        self.assertEqual(control.ainvoke.await_count, 2)
        model.ainvoke.assert_not_awaited()
        self.assertEqual(retrieve.await_count, 1)
        self.assertEqual(draft.await_count, 1)
        self.assertEqual(save.await_count, 1)
        self.assertEqual(save.call_args.args[0]["execution_token"], "resumed")
        search.assert_not_awaited()
        analysis.assert_not_awaited()
        labels = [call.args[1] for call in repo.event.await_args_list]
        self.assertNotIn("research", labels)  # Subagent executor uses bare task IDs.

    async def test_delegate_decision_enters_parallel_subagents_without_second_planning_call(self):
        import asyncio
        plan = DependencyPlan(tasks=[DelegatedTask(task_id="a", subagent="search", instruction="A"),
                                    DelegatedTask(task_id="b", subagent="search", instruction="B")])
        model, control = llm([MainDecision(action="delegate", plan=plan, delegation_reason="independent sources in parallel"),
                              MainDecision(action="answer", reply="combined [a:1] [b:1]")])
        started = set()
        ready = asyncio.Event()
        async def search(state):
            tid = state["task_id"]
            started.add(tid)
            if len(started) == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 2)
            return {"worker_results": [{"worker_name": "search", "result": f"source [{tid}:1]"}],
                    "citations": evidence(tid)["citations"]}
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(runtime, "search_worker_node", search):
            result, nodes = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "compare", []))
        self.assertEqual(started, {"a", "b"})
        self.assertIn("main_delegate", nodes)
        self.assertNotIn("main_task", nodes)
        self.assertEqual(result["action_history"][0]["action"], "delegate")
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertNotIn("planner", nodes)

    async def test_new_turn_resets_retrieval_and_route_on_existing_checkpoint(self):
        model, control = llm([MainDecision(action="retrieve", retrieval=RetrievalRequest(task_id="main", instruction="find")),
                              MainDecision(action="answer", reply="source [main:1]"), MainDecision(action="answer", reply="hello")])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(actions, "retrieve_evidence", AsyncMock(return_value=evidence())) as retrieve:
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            await run_updates(graph, create_initial_state(7, "find", []), "same")
            result, nodes = await run_updates(graph, create_initial_state(7, "hello", []), "same")
        self.assertEqual(nodes, ["main_agent", "final_gate"])
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["article_cards"], [])
        self.assertIsNone(result["main_decision"]["retrieval"])
        self.assertEqual(result["main_round"], 1)
        self.assertEqual(result["action_history"], [])
        self.assertEqual(result["observations"], [])
        self.assertEqual(result["task_results"], {})
        self.assertFalse(result["business_complete"])
        self.assertEqual(result["correction_count"], 0)
        self.assertEqual(result["final_reply"], "hello")
        self.assertEqual(retrieve.await_count, 1)

    async def test_cancelled_executor_cannot_finish_direct_answer(self):
        model, _ = llm([MainDecision(action="answer", reply="hello")])
        repo = repository()
        repo.assert_executor.side_effect = [None, ValueError("cancelled")]
        state = create_initial_state(7, "hello", [])
        state.update(run_id=RUN_ID, execution_token="first")
        with patch.object(agent, "get_llm", return_value=model), patch.object(runtime, "run_repository", repo):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            with self.assertRaisesRegex(ValueError, "cancelled"):
                await run_updates(graph, state)

    async def test_direct_answer_correction_cannot_switch_to_tools_or_delegate(self):
        for second, fails in [(CitationRepair(reply="corrected"), False),
                              ({"action": "retrieve", "retrieval": {"instruction": "new search"}}, True)]:
            model, control = llm([MainDecision(action="answer", reply="bad [fake:1]"), second])
            with self.subTest(fails=fails), patch.object(agent, "get_llm", return_value=model), \
                 patch.object(actions, "retrieve_evidence", AsyncMock()) as retrieve:
                graph = builder._build_graph().compile(checkpointer=InMemorySaver())
                result, nodes = await run_updates(graph, create_initial_state(7, "hello", []))
                if fails:
                    self.assertIn("回答引用未通过校验", result["final_reply"])
                else:
                    self.assertEqual(result["final_reply"], "corrected")
                    self.assertEqual(nodes, ["main_agent", "final_gate"])
            self.assertEqual(control.ainvoke.await_count, 2)
            retrieve.assert_not_awaited()

    async def test_insufficient_evidence_returns_to_main_once_without_starting_subagents(self):
        model, control = llm([MainDecision(action="retrieve", retrieval=RetrievalRequest(task_id="a", instruction="first query")),
                              MainDecision(action="retrieve", retrieval=RetrievalRequest(task_id="b", instruction="narrower query"))])
        with patch.object(agent, "get_llm", return_value=model), \
             patch.object(actions, "retrieve_evidence", AsyncMock(return_value={"status": "insufficient_evidence",
                 "result": "no evidence", "citations": [], "article_cards": [], "rag_context": ""})) as retrieve, \
             patch.object(runtime, "search_worker_node", AsyncMock()) as search:
            result, nodes = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, "compare", []))
        self.assertEqual(retrieve.await_count, 2)
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertEqual(result["execution_mode"], "direct")
        self.assertIn("停止自动重试", result["final_reply"])
        self.assertNotIn("subagent", nodes)
        model.ainvoke.assert_not_awaited()
        search.assert_not_awaited()

    async def test_direct_stream_emits_answer_without_fake_worker_progress(self):
        from app import main
        model, _ = llm([MainDecision(action="answer", reply="hello")])
        service = SimpleNamespace(repository=repository(), finish=AsyncMock(return_value={"reply": "hello", "interrupted": None,
            "cancelled": False, "articles": [], "citations": [], "draft_article_id": None}))
        config = {"configurable": {"thread_id": "stream", "run_id": RUN_ID, "execution_token": "first"}}
        with patch.object(agent, "get_llm", return_value=model), patch.object(main, "run_service", service):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            response = __import__("test_streaming").source_response(graph, create_initial_state(7, "hello", []), 11, 7, config)
            chunks = [chunk async for chunk in response.body_iterator]
        output = "".join(chunks)
        self.assertIn("__PROGRESS__:planner", output)
        self.assertIn('__REPLY__:{"content": "hello"}', output)
        self.assertNotIn("dispatcher:", output)
        service.finish.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
