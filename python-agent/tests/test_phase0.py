from rpc_fakes import public_reader
"""Offline regression: real LangGraph checkpoints, mocked external services."""
import os
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["AGENT_SERVICE_KEY"] = "offline-service-key-32-bytes-long!!"

import json
import unittest
from grounding_fakes import setUpModule, tearDownModule
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app import main, migrate
from app.clients.es_client import EsVectorStore, EsComponent
from app.graph import builder
from app.graph.state_factory import create_initial_state
from app.graph.nodes import writing_worker, search_worker
from app.graph import tool_executor
from app.graph.nodes.reflector import reflector_node
from app.models.draft import DraftOutput
from app.services.conversation import ConversationService
from app.services.memory import MemoryService
from app.services.query_rewrite import QueryRewriteService, QueryFilters, ResolvedFilters
from app.services.retrieval_service import RetrievalService
from app.services.citation_builder import CitationBuilder
from app.services.run_service import RunService
from app.services.save_draft_to_article_info import save_draft_to_article_info
from fakes import repository, RUN_ID, HASH, SERVICE_KEY, article_chunk


def row(**values):
    return SimpleNamespace(_mapping=values)


def snapshot(values=None, interrupted=False):
    return SimpleNamespace(values=values or {}, next=("writing_worker",) if interrupted else (),
                           tasks=(SimpleNamespace(interrupts=(SimpleNamespace(value={"draft": "preview", "draftHash": HASH}),)),)
                           if interrupted else ())


def services():
    conversations = SimpleNamespace(
        create_conversation=AsyncMock(return_value=11), require_owner=AsyncMock(),
        resolve_origin=AsyncMock(return_value=None),
        get_context_for_llm=AsyncMock(return_value=[]), add_message=AsyncMock(return_value=None),
        get_history=AsyncMock(return_value=[]),
        invalidate_cache=AsyncMock(),
    )
    memory = SimpleNamespace(should_recall=MagicMock(return_value=False), recall=AsyncMock(),
                             load_context=AsyncMock(return_value={"user_profile": {}, "active_constraints": []}),
                             should_extract=AsyncMock(return_value=False))
    return conversations, memory


class RagTests(unittest.IsolatedAsyncioTestCase):
    async def test_rewrite_preserves_filters_without_choosing_search_scope(self):
        service = QueryRewriteService()
        service.llm = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content=json.dumps({
            "semantic_queries": ["spring"], "keywords": ["spring"],
            "filters": {"tags": ["Spring"], "time_range": "week"},
            "search_mode": "platform", "need_web_search": True,
            "web_query": "Spring 入门 图文教程",
        }))))
        result = await service.rewrite("q", [])
        self.assertIsInstance(result["filters"], QueryFilters)
        self.assertEqual(result["filters"].tags, ["Spring"])
        self.assertNotIn("search_mode", result)
        self.assertNotIn("need_web_search", result)
        self.assertEqual(result["web_query"], "Spring 入门 图文教程")

    async def test_rewrite_failure_still_returns_complete_contract(self):
        service = QueryRewriteService()
        service.llm = SimpleNamespace(ainvoke=AsyncMock(side_effect=TimeoutError))
        result = await service.rewrite("q", [])
        self.assertEqual(result["semantic_queries"], ["q"])
        self.assertEqual(result["filters"], QueryFilters())
        self.assertEqual(result["status"], "degraded")
        self.assertNotIn("need_web_search", result)

    async def test_rrf_materializes_lists_and_deduplicates_soft_terms(self):
        service = RetrievalService.__new__(RetrievalService)
        service._vector_store = SimpleNamespace(search=AsyncMock(return_value=[article_chunk(aid="1")]))
        service._chunk_search = SimpleNamespace(search=AsyncMock(return_value=[article_chunk(aid="2")]))
        result = await service.hybrid_search(["q1", "q2"], ["Spring"],
                                            ResolvedFilters(soft_terms=["Spring", "Java"]))
        self.assertEqual(result[0]["article_id"], "1")
        self.assertEqual(result[0]["rrf_score"], 2 / 61)
        self.assertEqual(service._chunk_search.search.await_count, 2)

    async def test_filters_reach_knn_and_bm25(self):
        filters = {"term": {"user_id": 7}}
        vector = EsVectorStore.__new__(EsVectorStore)
        vector.embedding_service = SimpleNamespace(aembed=AsyncMock(return_value=[0.1]))
        vector.client = SimpleNamespace(search=AsyncMock(return_value={"hits": {"hits": []}}))
        await vector.search("q", 5, 0, filters=filters)
        self.assertEqual(vector.client.search.call_args.kwargs["knn"]["filter"], filters)
        lexical = EsComponent.__new__(EsComponent)
        lexical.client = vector.client
        await lexical.search("q", filters=filters)
        self.assertEqual(lexical.client.search.call_args.kwargs["body"]["query"]["bool"]["filter"], [filters])

    async def test_es_failure_is_not_an_empty_success(self):
        lexical = EsComponent.__new__(EsComponent)
        lexical.client = SimpleNamespace(search=AsyncMock(side_effect=RuntimeError("offline")))
        with self.assertRaises(RuntimeError):
            await lexical.search("q")

    async def test_mysql_verification_removes_unpublished_candidates(self):
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[row(article_id=1, title="published", content="<p>current public</p>")]))
        with patch.object(search_worker, "public_read", public_reader(database)):
            result = await search_worker._verify_candidates_from_mysql([
                article_chunk(aid="1", html="<p>current public</p>", content="current public", title="published"), article_chunk(aid="2"),
            ])
        self.assertEqual([doc["content"] for doc in result], ["current public"])
        self.assertEqual("published", database.fetch_all.call_args.args[0])

    async def test_citation_numbers_match_model_context_and_deduplicate(self):
        documents = [{"article_id": "1", "title": "A", "content": "text"}] * 2
        citations, context = CitationBuilder().build(documents)
        self.assertEqual(len(citations), 1)
        self.assertIn(f"[{citations[0].id}] A", context)
        self.assertEqual(citations[0].to_dict()["articleId"], "1")


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recall_rechecks_owner_and_restores_es_order(self):
        service = MemoryService.__new__(MemoryService)
        service._search_memories = AsyncMock(return_value=[{"memory_id": 2}, {"memory_id": 1}, {"memory_id": 3}])
        service._get_profile = AsyncMock(return_value=None)
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[
            row(memory_id=1, content="first", importance=0.5), row(memory_id=2, content="second", importance=0.5),
        ]), execute=AsyncMock())
        with patch("app.services.memory.db", database):
            result = await service.recall(7, "q")
        self.assertLess(result.index("second"), result.index("first"))
        self.assertIn("user_id = :uid", database.fetch_all.call_args.args[0])
        self.assertEqual(database.fetch_all.call_args.args[1]["uid"], 7)
        self.assertIn("user_id = :uid", database.execute.call_args.args[0])

    async def test_latest_user_message_and_missing_identity(self):
        service = MemoryService.__new__(MemoryService)
        self.assertEqual(service._find_last_user_text([
            {"role": "user", "content": "old"}, {"role": "assistant"}, {"role": "user", "content": "new"},
        ]), "new")
        self.assertEqual(await service.recall(0, "q"), "")


class WritingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fence = patch("app.graph.staged_runtime.run_repository.assert_executor", AsyncMock())
        self.fence.start()
        self.addCleanup(self.fence.stop)

    def initial(self):
        state = create_initial_state(7, "write", [])
        state.update(run_id=RUN_ID, execution_token="executor")
        return state

    async def make_graph(self):
        async def planner(state):
            return {"active_workers": ["writing"], "task_descriptions": {"writing": "draft"}}
        with patch.object(builder, "planner_node", planner), \
             patch.object(builder, "reflector_node", AsyncMock(return_value={"needs_retry": False})), \
             patch.object(builder, "synthesizer_node", AsyncMock(return_value={"final_reply": "saved"})):
            return builder._build_legacy_graph().compile(checkpointer=InMemorySaver())

    async def test_approval_preserves_preview_without_regeneration(self):
        graph = await self.make_graph()
        config = {"configurable": {"thread_id": "approval"}}
        generate = AsyncMock(return_value=DraftOutput(title="A", summary="S", content="# A\noriginal"))
        save = AsyncMock(return_value=99)
        with patch.object(writing_worker, "generate_draft", generate), \
             patch.object(writing_worker, "save_approved_draft", save):
            await graph.ainvoke(self.initial(), config)
            before = await graph.aget_state(config)
            self.assertTrue(before.tasks[0].interrupts)
            self.assertEqual(before.tasks[0].interrupts[0].value["draft"], "# A\noriginal")
            await graph.ainvoke(Command(resume="approve"), config)
            after = await graph.aget_state(config)
        self.assertEqual(generate.await_count, 1)
        self.assertEqual(save.await_count, 1)
        self.assertEqual(save.call_args.args[1].content, "# A\noriginal")
        self.assertEqual(len(after.values["worker_results"]), 1)
        self.assertEqual(after.values["draft_article_id"], 99)

    async def test_reject_does_not_save(self):
        graph = await self.make_graph()
        config = {"configurable": {"thread_id": "reject"}}
        with patch.object(writing_worker, "generate_draft", AsyncMock(return_value=DraftOutput(title="A", summary="S", content="text"))), \
             patch.object(writing_worker, "save_approved_draft", AsyncMock()) as save:
            await graph.ainvoke(self.initial(), config)
            await graph.ainvoke(Command(resume="reject"), config)
        save.assert_not_awaited()

    async def test_rich_text_manual_approval_preserves_html_without_regenerating(self):
        from app.models.draft import EditedDraft
        from app.services.draft_gateway import render_draft
        html = '<h2>手动标题</h2><p><strong>关键步骤</strong></p><pre><code class="language-java">int n = 1;</code></pre><table><tbody><tr><td>Redis</td></tr></tbody></table><p><img src="/uploads/test.png" alt="示意图"></p>'
        self.assertEqual(render_draft(EditedDraft(title="标题", summary="", content=html, content_format="html")), html)
        self.assertIn('&lt;', render_draft(DraftOutput(title="标题", summary="", content='<script>bad</script>')))
        with self.assertRaises(ValueError):
            EditedDraft(title="标题", summary="", content=html, content_format="unknown")
        graph = await self.make_graph()
        config = {"configurable": {"thread_id": "rich-manual-approval"}}
        with patch.object(writing_worker, "generate_draft", AsyncMock(return_value=DraftOutput(title="A", summary="", content="# A"))) as generate, \
             patch.object(writing_worker, "save_approved_draft", AsyncMock(return_value=99)) as save:
            await graph.ainvoke(self.initial(), config)
            pending = (await graph.aget_state(config)).tasks[0].interrupts[0].value
            await graph.ainvoke(Command(resume={"action": "approve", "runId": RUN_ID,
                "draftHash": pending["draftHash"], "editedDraft": {"title": "手动标题", "summary": "摘要", "content": html, "content_format": "html"}}), config)
        generate.assert_awaited_once()
        save.assert_awaited_once()
        self.assertEqual(save.call_args.args[0]['draft_html'], html)
        self.assertEqual(save.call_args.args[0]['approved_base_hash'], pending['draftHash'])
        self.assertNotEqual(save.call_args.args[0]['draft_hash'], pending['draftHash'])
        self.assertEqual(save.call_args.args[1].content, html)

    async def test_ai_revision_uses_manual_edits_and_waits_for_second_approval(self):
        graph = await self.make_graph()
        config = {"configurable": {"thread_id": "manual-revision"}}
        generate = AsyncMock(side_effect=[DraftOutput(title="A", summary="S", content="original"),
                                          DraftOutput(title="B", summary="S", content="AI revised")])
        with patch.object(writing_worker, "generate_draft", generate), \
             patch.object(writing_worker, "save_approved_draft", AsyncMock(return_value=99)) as save:
            await graph.ainvoke(self.initial(), config)
            pending = (await graph.aget_state(config)).tasks[0].interrupts[0].value
            await graph.ainvoke(Command(resume={"action": "补充例子", "runId": RUN_ID,
                "draftHash": pending["draftHash"], "editedDraft": {"title": "手动标题", "summary": "", "content": "manual text"}}), config)
            save.assert_not_awaited()
            self.assertIn("manual text", generate.call_args.args[0])
            self.assertIn("补充例子", generate.call_args.args[0])
            self.assertTrue((await graph.aget_state(config)).tasks[0].interrupts)
            await graph.ainvoke(Command(resume="approve"), config)
        self.assertEqual(save.call_args.args[1].content, "AI revised")

    async def test_unknown_reference_cannot_save_manually_edited_draft(self):
        graph = await self.make_graph()
        config = {"configurable": {"thread_id": "invalid-manual"}}
        with patch.object(writing_worker, "generate_draft", AsyncMock(return_value=DraftOutput(title="A", summary="", content="original"))), \
             patch.object(writing_worker, "save_approved_draft", AsyncMock()) as save:
            await graph.ainvoke(self.initial(), config)
            pending = (await graph.aget_state(config)).tasks[0].interrupts[0].value
            with self.assertRaises(ValueError):
                await graph.ainvoke(Command(resume={"action": "approve", "runId": RUN_ID,
                    "draftHash": pending["draftHash"], "editedDraft": {"title": "A", "summary": "", "content": "fake [unknown:1]"}}), config)
        save.assert_not_awaited()

    async def test_revision_requires_a_second_approval(self):
        graph = await self.make_graph()
        config = {"configurable": {"thread_id": "revision"}}
        generate = AsyncMock(side_effect=[DraftOutput(title="A", summary="S", content="old"),
                                          DraftOutput(title="A", summary="S", content="revised")])
        with patch.object(writing_worker, "generate_draft", generate), \
             patch.object(writing_worker, "save_approved_draft", AsyncMock(return_value=99)) as save:
            await graph.ainvoke(self.initial(), config)
            await graph.ainvoke(Command(resume="shorter"), config)
            state = await graph.aget_state(config)
            self.assertEqual(state.tasks[0].interrupts[0].value["draft"], "revised")
            save.assert_not_awaited()
            await graph.ainvoke(Command(resume="approve"), config)
        self.assertEqual(generate.await_count, 2)
        self.assertEqual(save.call_args.args[1].content, "revised")

    async def test_retired_writer_cannot_bypass_revision_gateway(self):
        execute = AsyncMock()
        with patch("app.services.save_draft_to_article_info.db", SimpleNamespace(execute=execute)):
            with self.assertRaises(RuntimeError):
                await save_draft_to_article_info(7, DraftOutput(title="A", summary="S", content="original"), 123)
        execute.assert_not_awaited()

    async def test_new_turn_does_not_reuse_old_results(self):
        async def planner(state):
            return {"active_workers": ["chat"], "task_descriptions": {"chat": state["user_message"]}}
        async def chat(state):
            return {"worker_results": [{"worker_name": "chat", "result": state["user_message"]}]}
        with patch.object(builder, "planner_node", planner), patch.object(builder, "chat_worker_node", chat), \
             patch.object(builder, "reflector_node", AsyncMock(return_value={"needs_retry": False})), \
             patch.object(builder, "synthesizer_node", AsyncMock(return_value={"final_reply": "done"})):
            graph = builder._build_legacy_graph().compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "turns"}}
        await graph.ainvoke(create_initial_state(7, "old", []), config)
        await graph.ainvoke(create_initial_state(7, "new", []), config)
        state = await graph.aget_state(config)
        self.assertEqual([r["result"] for r in state.values["worker_results"]], ["new"])

    async def test_confirmed_draft_does_not_enter_reflection_retry(self):
        with patch("app.graph.nodes.reflector.get_llm") as llm:
            result = await reflector_node({"draft_article_id": 99})
        self.assertFalse(result["needs_retry"])
        llm.assert_not_called()


class FailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_timeout_propagates_instead_of_becoming_success_text(self):
        with patch.object(tool_executor, "_run_tool_agent_inner", AsyncMock(side_effect=TimeoutError)):
            with self.assertRaises(TimeoutError):
                await tool_executor.run_tool_agent("prompt", "input")

    async def test_unknown_tool_call_is_rejected(self):
        model = SimpleNamespace(
            bind_tools=MagicMock(),
            ainvoke=AsyncMock(return_value=SimpleNamespace(content="", tool_calls=[
                {"name": "unauthorized", "args": {}, "id": "call-1"},
            ])),
        )
        model.bind_tools.return_value = model
        with patch.object(tool_executor, "get_llm", return_value=model), \
             patch.object(tool_executor, "get_langfuse_callback", return_value=None):
            with self.assertRaises(PermissionError):
                await tool_executor.run_tool_agent("prompt", "input")

    async def test_empty_completed_reply_is_not_persisted(self):
        conv, memory = services()
        with self.assertRaises(RuntimeError):
            await RunService(conv, memory).finish(11, 7, snapshot())
        conv.add_message.assert_not_awaited()


class EntryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        history = patch('app.services.run_service.run_history.previous', AsyncMock(return_value=({}, {})))
        history.start()
        self.addCleanup(history.stop)
        self.admission = patch.object(main, 'execution_admission', SimpleNamespace(acquire=AsyncMock(return_value='ticket'), release=AsyncMock()))
        self.admission.start()
        # These assertions exercise graph/result parity, not persistence transport.
        self.stream = patch.object(main, '_stream', __import__('test_streaming').source_response)
        self.stream.start()
        self.addCleanup(self.stream.stop)
        self.addCleanup(self.admission.stop)

    async def test_four_endpoints_preserve_identical_metadata(self):
        final = snapshot({"final_reply": "canonical", "article_cards": [{"articleId": "5"}],
                          "citations": [{"id": "1", "articleId": "5"}], "draft_article_id": 99})
        for path in ("/chat", "/chat/stream", "/chat/resume", "/chat/resume/stream"):
            with self.subTest(path=path):
                conv, memory = services()
                pending = snapshot({"user_id": 7}, interrupted=True) if "resume" in path else snapshot()
                calls = 0
                async def get_state(config):
                    nonlocal calls
                    calls += 1
                    return pending if calls == 1 and "resume" in path else final
                async def events(*args, **kwargs):
                    if False:
                        yield {}
                graph = SimpleNamespace(aget_state=get_state, ainvoke=AsyncMock(), astream_events=events)
                payload = {"user_id": 7, "conversation_id": 11}
                payload.update({"action": "approve", "run_id": RUN_ID, "draft_hash": HASH} if "resume" in path else {"message": "q"})
                with patch.object(main, "get_graph", AsyncMock(return_value=graph)), \
                     patch.object(main, "run_service", RunService(conv, memory, repository())):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test",
                                                 headers={"X-Agent-Key": SERVICE_KEY, "X-Agent-User": "7"}) as client:
                        response = await client.post(path, json=payload)
                self.assertEqual(response.status_code, 200)
                assistant = next(call for call in conv.add_message.call_args_list if call.args[1] == "assistant")
                self.assertEqual(assistant.args[2], "canonical")
                self.assertEqual(assistant.kwargs["draft_article_id"], 99)
                self.assertEqual(assistant.kwargs["citations"], final.values["citations"])
                self.assertEqual(assistant.kwargs["article_cards"], final.values["article_cards"])
                if "stream" in path:
                    self.assertIn("__REPLY__:", response.text)
                    self.assertIn("__CITATIONS__:", response.text)

    async def test_interrupted_and_cancelled_results_are_not_persisted(self):
        for state in (snapshot(interrupted=True), snapshot({"cancelled": True, "final_reply": "partial"})):
            conv, memory = services()
            await RunService(conv, memory).finish(11, 7, state)
            conv.add_message.assert_not_awaited()
            memory.should_extract.assert_not_awaited()

    async def test_resume_without_pending_approval_is_rejected(self):
        conv, memory = services()
        with self.assertRaises(HTTPException) as error:
            await RunService(conv, memory, repository()).prepare_resume(main.ResumeRequest(user_id=7, conversation_id=11, action="approve", run_id=RUN_ID, draft_hash=HASH),
                                                         SimpleNamespace(aget_state=AsyncMock(return_value=snapshot())))
        self.assertEqual(error.exception.status_code, 409)

    async def test_invalid_manual_reference_is_rejected_before_claiming_approval(self):
        conv, memory = services()
        repo = repository()
        request = main.ResumeRequest(user_id=7, conversation_id=11, action="approve", run_id=RUN_ID, draft_hash=HASH,
            edited_draft={"title": "标题", "summary": "", "content": "不存在 [unknown:1]"})
        graph = SimpleNamespace(aget_state=AsyncMock(return_value=snapshot(interrupted=True)))
        with self.assertRaises(HTTPException) as error:
            await RunService(conv, memory, repo).prepare_resume(request, graph)
        self.assertEqual(error.exception.status_code, 422)
        repo.claim_resume.assert_not_awaited()

    async def test_owner_failure_precedes_read_or_resume(self):
        conv, memory = services()
        conv.require_owner.side_effect = HTTPException(status_code=404)
        conv.resolve_origin.side_effect = HTTPException(status_code=404)
        with self.assertRaises(HTTPException):
            await RunService(conv, memory, repository()).prepare_chat(main.ChatRequest(user_id=7, conversation_id=11, message="q"), MagicMock())
        conv.get_context_for_llm.assert_not_awaited()
        conv.add_message.assert_not_awaited()

    async def test_database_failure_does_not_put_phantom_message_in_cache(self):
        service = ConversationService.__new__(ConversationService)
        service._redis = SimpleNamespace(get=AsyncMock(return_value="[]"), set=AsyncMock(), delete=AsyncMock())
        @asynccontextmanager
        async def transaction():
            yield
        with patch("app.services.conversation.db", SimpleNamespace(transaction=transaction, execute=AsyncMock(side_effect=RuntimeError("offline")))):
            with self.assertRaises(RuntimeError):
                await service.add_message(11, "assistant", "not saved")
        service._redis.set.assert_not_awaited()


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_upgrade_replays_and_preserves_existing_draft_column(self):
        columns = {"message_id": "bigint", "draft_article_id": "bigint"}
        executed = []
        async def fetch_all(query):
            return [row(name=name, type=kind) for name, kind in columns.items()]
        async def execute(query, params=None):
            executed.append(query)
            if "ADD COLUMN citations" in query:
                columns["citations"] = "json"
        connection = SimpleNamespace(fetch_all=fetch_all, execute=execute, fetch_one=AsyncMock(return_value=None),
                                     fetch_val=AsyncMock(return_value=1))
        @asynccontextmanager
        async def connect():
            yield connection
        database = SimpleNamespace(connection=connect)
        await migrate.apply_migration(database)
        await migrate.apply_migration(database)
        self.assertEqual(sum("ADD COLUMN" in sql for sql in executed), 1)
        self.assertEqual(columns["draft_article_id"], "bigint")

    async def test_startup_check_refuses_missing_column_without_writing(self):
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[row(name="message_id", type="bigint")]), execute=AsyncMock())
        with self.assertRaises(RuntimeError):
            await migrate.check_message_schema(database)
        database.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
