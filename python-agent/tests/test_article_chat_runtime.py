from rpc_fakes import public_reader
"""Article origin is context, while each action owns its retrieval scope."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["AGENT_SERVICE_KEY"] = "offline-service-key-32-bytes-long!!"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

import hashlib
import json
import unittest
from grounding_fakes import setUpModule, tearDownModule
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver

from app import main
from app.graph import builder, main_agent as agent, action_runtime as actions, staged_runtime as runtime
from app.graph.main_agent import MainDecision, RetrievalRequest
from app.graph.staged_plan import ExecutionTask, DelegatedTask
from app.graph.state_factory import create_initial_state
from app.graph.nodes import search_worker
from app.services import evidence_verifier
from app.services.article_context import ArticleContextService
from app.services.query_rewrite import ResolvedFilters
from app.services.retrieval_service import RetrievalService
from app.services.run_service import RunService
from app.services.run_repository import digest
from fakes import repository, RUN_ID, SERVICE_KEY, article_chunk


def source(aid=42, title="当前文章", content="<p>自动配置根据条件创建 Bean。</p>"):
    return ArticleContextService(AsyncMock(return_value=[{
        "article_id": aid, "title": title, "content": content, "content_type": 1}]))


def conversations(origin=None):
    return SimpleNamespace(create_conversation=AsyncMock(return_value=11),
        resolve_origin=AsyncMock(return_value=origin), get_context_for_llm=AsyncMock(return_value=[]),
        add_message=AsyncMock(return_value=None), require_owner=AsyncMock())


def memory():
    return SimpleNamespace(load_context=AsyncMock(return_value={"user_profile": {}, "active_constraints": []}))


async def article_state():
    service = source()
    context = await service.load(42)
    state = create_initial_state(7, "解释当前文章", [])
    state.update(origin_article_id=42, article_context={k: v for k, v in context.items() if k not in ("content", "citation")},
                 task_results={"article_context": {**service.evidence(context), "source_context": True}})
    return state


def model(decisions):
    controller = SimpleNamespace(ainvoke=AsyncMock(side_effect=decisions))
    return SimpleNamespace(with_structured_output=Mock(return_value=controller)), controller


async def execute(state):
    graph = builder._build_graph().compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "article-chat"}, "recursion_limit": 80}
    nodes = []
    async for update in graph.astream(state, config, stream_mode="updates"):
        nodes.extend(update)
    return (await graph.aget_state(config)).values, nodes


class ArticleRunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        history = patch('app.services.run_service.run_history.previous', AsyncMock(return_value=({}, {})))
        history.start()
        self.addCleanup(history.stop)

    async def test_first_question_creates_bound_conversation_and_supplies_source_without_model_call(self):
        conv, repo, articles = conversations(), repository(), source()
        service = RunService(conv, memory(), repo, articles=articles)
        cid, _, state = await service.prepare_chat(main.ChatRequest(user_id=7, message="解释这里", origin_article_id=42), None)
        self.assertEqual(cid, 11)
        conv.create_conversation.assert_awaited_once_with(7, origin_article_id=42)
        self.assertEqual(state["origin_article_id"], 42)
        self.assertEqual(state["article_context"]["completeness"], "full")
        self.assertNotIn("content", state["article_context"])
        self.assertIn("自动配置", state["task_results"]["article_context"]["result"])
        self.assertEqual(repo.create.await_args.args[3], digest({"message": "解释这里", "images": [], "origin_article_id": 42}))

    async def test_ordinary_chat_does_not_read_article_or_change_existing_idempotency_hash(self):
        conv, repo, articles = conversations(), repository(), SimpleNamespace(load=AsyncMock())
        _, _, state = await RunService(conv, memory(), repo, articles=articles).prepare_chat(main.ChatRequest(user_id=7, message="你好"), None)
        self.assertEqual(repo.create.await_args.args[3], digest({"message": "你好", "images": []}))
        self.assertEqual(state["article_context"], {})
        articles.load.assert_not_awaited()

    async def test_existing_conversation_derives_origin_and_refreshes_current_version(self):
        conv, articles = conversations(42), source()
        service = RunService(conv, memory(), repository(), articles=articles)
        req = main.ChatRequest(user_id=7, conversation_id=11, message="继续解释")
        _, _, first = await service.prepare_chat(req, None)
        articles.reader.return_value[0]["content"] = "<p>更新后的规则。</p>"
        _, _, second = await service.prepare_chat(req, None)
        self.assertNotEqual(first["article_context"]["source_hash"], second["article_context"]["source_hash"])
        self.assertIn("更新后的规则", second["task_results"]["article_context"]["result"])
        conv.create_conversation.assert_not_awaited()
        self.assertEqual(articles.reader.await_count, 2)

    async def test_hidden_article_fails_before_conversation_creation_or_message_append(self):
        conv, repo, articles = conversations(), repository(), source()
        articles.reader.return_value = []
        with self.assertRaises(HTTPException) as error:
            await RunService(conv, memory(), repo, articles=articles).prepare_chat(main.ChatRequest(user_id=7, message="q", origin_article_id=42), None)
        self.assertEqual(error.exception.status_code, 404)
        conv.create_conversation.assert_not_awaited()
        conv.add_message.assert_not_awaited()
        repo.create.assert_not_awaited()

    async def test_same_request_id_cannot_be_reused_for_another_article(self):
        conv, repo = conversations(), repository()
        repo.find_request.return_value = {"input_hash": digest({"message": "q", "images": [], "origin_article_id": 41}),
                                         "conversation_id": 11}
        with self.assertRaises(HTTPException) as error:
            await RunService(conv, memory(), repo, articles=source()).prepare_chat(main.ChatRequest(user_id=7, message="q", origin_article_id=42, request_id=RUN_ID), None)
        self.assertEqual(error.exception.status_code, 409)
        conv.add_message.assert_not_awaited()

    async def test_unavailable_origin_does_not_lock_existing_chat_to_that_article(self):
        conv, articles = conversations(42), source()
        articles.reader.return_value = []
        _, _, state = await RunService(conv, memory(), repository(), articles=articles).prepare_chat(
            main.ChatRequest(user_id=7, conversation_id=11, message="解释 Redis"), None)
        self.assertEqual(state["article_context"]["availability"], "unavailable")
        self.assertIsNone(state["task_results"])
        conv.add_message.assert_awaited_once()

    async def test_replay_with_omitted_origin_uses_persisted_source_and_does_not_append_again(self):
        conv, repo = conversations(42), repository()
        repo.find_request.return_value = {"run_id": RUN_ID, "conversation_id": 11, "user_id": 7,
            "execution_token": "t", "input_hash": digest({"message": "q", "images": [], "origin_article_id": 42}),
            "status": "succeeded", "draft_article_id": None}
        cid, config, state = await RunService(conv, memory(), repo, articles=source()).prepare_chat(
            main.ChatRequest(user_id=7, conversation_id=11, message="q", request_id=RUN_ID), None)
        self.assertEqual(cid, 11)
        self.assertTrue(config["configurable"]["replay"])
        self.assertIsNone(state)
        conv.add_message.assert_not_awaited()


class ArticleGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_article_is_directly_answerable_with_checked_citation(self):
        state = await article_state()
        llm, control = model([MainDecision(action="answer", reply="根据条件创建 Bean。[article_context:1]")])
        with patch.object(agent, "get_llm", return_value=llm), \
             patch.object(actions, "retrieve_evidence", AsyncMock()) as retrieval, \
             patch.object(evidence_verifier, "public_read", AsyncMock(return_value=[
                 {"article_id": 42, "content": "<p>自动配置根据条件创建 Bean。</p>"}])):
            result, nodes = await execute(state)
        self.assertEqual(nodes, ["main_agent", "final_gate"])
        self.assertEqual(control.ainvoke.await_count, 1)
        retrieval.assert_not_awaited()
        self.assertEqual(result["citations"][0]["articleId"], "42")

    async def test_comparison_retrieves_other_articles_in_same_conversation_without_origin_filter(self):
        state = await article_state()
        state["user_message"] = "和另一篇条件装配文章对比"
        llm, control = model([MainDecision(action="retrieve", retrieval=RetrievalRequest(instruction="找另一篇条件装配文章")),
            MainDecision(action="answer", reply="当前文章解释条件，另一篇提供示例。[article_context:1][retrieve_1:1]")])
        other = {"status": "succeeded", "rag_context": "[retrieve_1:1] 另一篇条件装配示例",
                 "citations": [{"id": "retrieve_1:1", "articleId": "43", "title": "条件装配示例", "excerpt": "示例"}],
                 "article_cards": [{"articleId": "43", "title": "条件装配示例"}]}
        with patch.object(agent, "get_llm", return_value=llm), \
             patch.object(actions, "retrieve_evidence", AsyncMock(return_value=other)) as retrieval, \
             patch.object(evidence_verifier, "verify_public_evidence", AsyncMock()), \
             patch.object(runtime, "verify_public_evidence", AsyncMock()):
            result, nodes = await execute(state)
        self.assertEqual(result["origin_article_id"], 42)
        self.assertEqual({c["articleId"] for c in result["citations"]}, {"42", "43"})
        self.assertEqual(retrieval.await_args.args[0]["current_task"]["article_ids"], [])
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertIn("main_retrieve", nodes)

    async def test_source_preparation_does_not_consume_action_task_budget(self):
        state = await article_state()
        decision = MainDecision(action="retrieve", retrieval=RetrievalRequest(instruction="找其他文章"))
        with patch.object(agent.settings, "MAIN_MAX_TASKS", 1):
            self.assertNotIn("stop_reason", agent.validate_action(state, decision, 1))
            self.assertEqual(json.loads(agent.decision_context(state))["remaining_tasks"], 1)

    async def test_changed_or_unpublished_current_article_cannot_pass_final_delivery(self):
        state = await article_state()
        state.update(final_reply="解释。[article_context:1]", citations=state["task_results"]["article_context"]["citations"])
        for rows in ([], [SimpleNamespace(_mapping={"article_id": 42, "content": "已修改"})]):
            with self.subTest(rows=rows), patch.object(evidence_verifier, "public_read", AsyncMock(return_value=[dict(r._mapping) for r in rows])), self.assertRaises(ValueError):
                await runtime.final_gate(state)


class RetrievalScopeTests(unittest.IsolatedAsyncioTestCase):
    def test_memory_and_analysis_cannot_use_article_scope(self):
        for make in (lambda: RetrievalRequest(target="memory", instruction="回忆", article_ids=[42]),
                     lambda: DelegatedTask(task_id="a", instruction="分析", subagent="analysis", article_ids=[42]),
                     lambda: RetrievalRequest(instruction="查找", article_ids=[42, 42]),
                     lambda: RetrievalRequest(instruction="查找", article_ids=[-1])):
            with self.assertRaises(ValueError): make()

    def test_known_article_filter_is_applied_to_shared_knn_and_bm25_corpus(self):
        service = RetrievalService.__new__(RetrievalService)
        scoped = service._build_vector_filter(ResolvedFilters(article_ids=[42, 43]))
        global_scope = service._build_vector_filter(ResolvedFilters())
        self.assertIn({"terms": {"article_id": ["42", "43"]}}, scoped["bool"]["filter"])
        self.assertFalse(any("article_id" in c.get("terms", {}) for c in global_scope["bool"]["filter"]))

    def test_repeated_strategy_uses_article_set_not_order(self):
        def task(ids): return ExecutionTask(task_id="q", kind="search", actor="main", instruction="找段落", article_ids=ids)
        self.assertEqual(agent.task_fingerprint(task([42, 43])), agent.task_fingerprint(task([43, 42])))
        self.assertNotEqual(agent.task_fingerprint(task([42])), agent.task_fingerprint(task([43])))

    async def test_mysql_recheck_drops_candidates_outside_explicit_article_scope(self):
        html = "<p>current public evidence</p>"
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[SimpleNamespace(_mapping={"article_id": 42, "title": "RAG", "content": html})]))
        with patch.object(search_worker, "public_read", public_reader(database)):
            result = await search_worker._verify_candidates_from_mysql([article_chunk(), article_chunk(aid="43")], article_ids=[42])
        self.assertEqual([str(c["article_id"]) for c in result], ["42"])
        self.assertEqual(database.fetch_all.await_args.args[1], {"ids": ["42"]})

    async def test_metadata_and_scoped_listing_require_authenticated_owner_identity(self):
        headers = {"X-Agent-Key": SERVICE_KEY, "X-Agent-User": "7"}
        fake = AsyncMock(return_value={"conversationId": "11", "originArticleId": "42"})
        with patch.object(main.conversation_service, "get_conversation", fake):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                self.assertEqual((await client.get("/conversations/11?user_id=7")).status_code, 401)
                self.assertEqual((await client.get("/conversations/11?user_id=8", headers=headers)).status_code, 403)
                res = await client.get("/conversations/11?user_id=7", headers=headers)
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["data"]["originArticleId"], "42")
                self.assertEqual((await client.get("/conversations?user_id=7&scope=bad", headers=headers)).status_code, 422)
                self.assertEqual((await client.get("/conversations?user_id=7&origin_article_id=-1", headers=headers)).status_code, 422)
        fake.assert_awaited_once_with(11, 7)


if __name__ == "__main__": unittest.main()
