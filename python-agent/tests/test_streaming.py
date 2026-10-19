"""Public SSE lifecycle; real model token streaming is in test_answer_stream."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
os.environ["AGENT_SERVICE_KEY"] = "offline-service-key-32-bytes-long!!"

import json
import unittest
from grounding_fakes import setUpModule, tearDownModule
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app import main
from app.graph import builder, main_agent as agent, staged_runtime as runtime, action_runtime as actions
from app.graph.main_agent import MainArtifact, MainDecision, RetrievalRequest
from app.graph.nodes import writing_worker
from app.graph.staged_plan import DependencyPlan, DelegatedTask, DraftRequest
from app.graph.state_factory import create_initial_state
from app.models.draft import DraftOutput
from app.services.run_service import interrupt_payload
from test_main_agent import llm, evidence
from fakes import repository, RUN_ID


def source_response(*args):
    from starlette.responses import StreamingResponse
    return StreamingResponse(main._stream_source(*args), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})


def parse_frames(frames, prefix):
    return [json.loads(frame[len('data:' + prefix):].strip()) for frame in frames if frame.startswith('data:' + prefix)]


def result(reply="hello", interrupted=None, draft=None):
    return {"reply": reply, "articles": [], "citations": [], "interrupted": interrupted,
            "cancelled": False, "draft_article_id": draft}


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_stopped_decision_delivers_notice_without_claiming_request_completed(self):
        async def events(*args, **kwargs):
            if False:
                yield
        stopped = {**result('检索已返回，但后续处理未能继续。'), 'delivery_status': 'incomplete'}
        repo = repository()
        graph = SimpleNamespace(astream_events=events, aget_state=AsyncMock(return_value=SimpleNamespace()))
        service = SimpleNamespace(repository=repo, finish=AsyncMock(return_value=stopped))
        config = {'configurable': {'run_id': RUN_ID, 'execution_token': 'token'}}
        with patch.object(main, 'run_service', service):
            frames = [frame async for frame in main._stream_source(graph, {}, 11, 7, config)]
        self.assertEqual(parse_frames(frames, '__AGENT_EVENT__:')[-1]['status'], 'error')
        self.assertFalse(any('__PROGRESS__:done' in frame or '[ERROR]' in frame for frame in frames))
        self.assertEqual(parse_frames(frames, '__REPLY__:')[0]['content'], stopped['reply'])
        self.assertEqual(frames[-1], 'data:[DONE]\n\n')

    async def test_main_artifact_emits_completed_main_activity_without_exposing_body(self):
        decision = MainDecision(action="retrieve", retrieval=RetrievalRequest(task_id="source", instruction="find"),
            artifacts=[MainArtifact(task_id="notes", instruction="整理需求", result="private intermediate body")])
        model, control = llm([decision, MainDecision(action="answer", reply="found [source:1]", answer_dependencies=["source"])])
        service = SimpleNamespace(repository=repository(), finish=AsyncMock(return_value=result("found [source:1]")))
        config = {"configurable": {"thread_id": "artifact-events", "run_id": RUN_ID, "execution_token": "t"}}
        with patch.object(agent, "get_llm", return_value=model), patch.object(main, "run_service", service), \
             patch.object(actions, "retrieve_evidence", AsyncMock(return_value=evidence("source"))):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            frames = [frame async for frame in source_response(graph, create_initial_state(7, "find", []), 11, 7, config).body_iterator]
        events = parse_frames(frames, '__AGENT_EVENT__:')
        notes = [event for event in events if event.get("id") == "notes/task"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["status"], "done")
        self.assertEqual(notes[0]["actor"], "main")
        self.assertNotIn("private intermediate body", "".join(frames))
        self.assertEqual(control.ainvoke.await_count, 2)
        model.ainvoke.assert_not_awaited()

    async def test_each_main_round_retains_its_own_activity(self):
        model, _ = llm([MainDecision(action="retrieve", retrieval=RetrievalRequest(task_id="source", instruction="find")),
                        MainDecision(action="answer", reply="found [source:1]")])
        service = SimpleNamespace(repository=repository(), finish=AsyncMock(return_value=result("found [source:1]")))
        config = {"configurable": {"thread_id": "round-events", "run_id": RUN_ID, "execution_token": "t"}}
        with patch.object(agent, "get_llm", return_value=model), patch.object(main, "run_service", service), \
             patch.object(actions, "retrieve_evidence", AsyncMock(return_value=evidence("source"))):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            frames = [frame async for frame in source_response(graph, create_initial_state(7, "find", []), 11, 7, config).body_iterator]
        rounds = [event for event in parse_frames(frames, '__AGENT_EVENT__:') if event.get("step") == "main_agent"]
        self.assertEqual({event["id"] for event in rounds}, {"main/round_1/main_agent", "main/round_2/main_agent"})
        self.assertEqual([event["status"] for event in rounds], ["active", "done", "active", "done"])

    async def test_activity_is_live_and_answer_starts_only_after_finish(self):
        model, _ = llm([MainDecision(action="answer", reply="hello")])
        repo = repository()
        service = SimpleNamespace(repository=repo, finish=AsyncMock(return_value=result()))
        state = create_initial_state(7, "private user text", [])
        state.update(run_id=RUN_ID, execution_token="private-token", memory_context="private-memory")
        config = {"configurable": {"thread_id": "stream-real", "run_id": RUN_ID, "execution_token": "private-token"}}
        with patch.object(agent, "get_llm", return_value=model), patch.object(runtime, "run_repository", repo), \
             patch.object(main, "run_service", service):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            response = source_response(graph, state, 11, 7, config)
            frames = []
            async for frame in response.body_iterator:
                if frame.startswith('data:__ANSWER__:'):
                    service.finish.assert_awaited_once()
                frames.append(frame)
        events = parse_frames(frames, '__AGENT_EVENT__:')
        self.assertEqual(events[0]['label'], '理解请求')
        self.assertEqual(events[0]['status'], 'active')
        self.assertTrue(any(event.get('kind') == 'commentary' for event in events))
        self.assertTrue(any(event.get('label') == '核对引用与来源' and event['status'] == 'done' for event in events))
        public = json.dumps(events)
        self.assertNotIn('private-token', public)
        self.assertNotIn('private-memory', public)
        self.assertNotIn('private user text', public)
        answers = parse_frames(frames, '__ANSWER__:')
        self.assertEqual(''.join(event['content'] for event in answers if event['type'] == 'delta'), 'hello')
        self.assertEqual(response.headers['x-accel-buffering'], 'no')

    async def test_failed_final_gate_never_emits_answer(self):
        model, _ = llm([MainDecision(action="answer", reply="unverified text")])
        repo = repository()
        repo.get.return_value = None
        service = SimpleNamespace(repository=repo, finish=AsyncMock(return_value=result()))
        config = {"configurable": {"thread_id": "failed-stream", "run_id": RUN_ID, "execution_token": "t"}}
        with patch.object(agent, "get_llm", return_value=model), patch.object(main, "run_service", service), \
             patch.object(builder, "final_gate", AsyncMock(side_effect=ValueError('stale source'))):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            frames = [frame async for frame in source_response(graph, create_initial_state(7, "q", []), 11, 7, config).body_iterator]
        service.finish.assert_not_awaited()
        self.assertEqual(parse_frames(frames, '__ANSWER__:'), [])
        self.assertEqual(parse_frames(frames, '__REPLY__:'), [])
        self.assertTrue(any('[ERROR]' in frame for frame in frames))
        self.assertEqual(parse_frames(frames, '__AGENT_EVENT__:')[-1]['status'], 'error')

    async def test_parallel_tasks_have_distinct_live_activity_ids(self):
        import asyncio
        plan = DependencyPlan(tasks=[DelegatedTask(task_id="a", subagent="search", instruction="研究主题A"),
                                    DelegatedTask(task_id="b", subagent="search", instruction="研究主题B")])
        model, _ = llm([MainDecision(action="delegate", plan=plan, delegation_reason="parallel research"),
                        MainDecision(action="answer", reply="combined")])
        repo = repository()
        service = SimpleNamespace(repository=repo, finish=AsyncMock(return_value=result('combined')))
        ready, started = asyncio.Event(), set()
        async def search(state):
            started.add(state['task_id'])
            if len(started) == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 2)
            return {"worker_results": [{"worker_name": "search", "result": "result"}]}
        config = {"configurable": {"thread_id": "parallel-stream", "run_id": RUN_ID, "execution_token": "t"}}
        with patch.object(agent, "get_llm", return_value=model), patch.object(runtime, "search_worker_node", search), \
             patch.object(main, "run_service", service):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            frames = [frame async for frame in source_response(graph, create_initial_state(7, "compare", []), 11, 7, config).body_iterator]
        events = parse_frames(frames, '__AGENT_EVENT__:')
        task_events = [event for event in events if event.get('step') == 'task']
        self.assertEqual({event['id'] for event in task_events}, {'a/task', 'b/task'})
        self.assertEqual([event['status'] for event in task_events[:2]], ['active', 'active'])
        self.assertTrue(all(event['actor'] == 'subagent' for event in task_events))
        self.assertEqual(len(next(event for event in events if event['kind'] == 'plan')['tasks']), 2)

    async def test_approval_stream_pauses_and_resumes_without_regenerating_preview(self):
        request = DraftRequest(task_id="draft", instruction="生成草稿")
        model, _ = llm([MainDecision(action="write_draft", draft_request=request)])
        repo = repository()
        async def finish(cid, uid, snapshot, config):
            preview = interrupt_payload(snapshot)
            return result('草稿已保存', interrupted=preview, draft=snapshot.values.get('draft_article_id'))
        service = SimpleNamespace(repository=repo, finish=AsyncMock(side_effect=finish))
        state = create_initial_state(7, "write", [])
        state.update(run_id=RUN_ID, execution_token="first")
        config = {"configurable": {"thread_id": "approval-stream", "run_id": RUN_ID, "execution_token": "first"}}
        with patch.object(agent, "get_llm", return_value=model), patch.object(runtime, "run_repository", repo), \
             patch.object(main, "run_service", service), \
             patch.object(writing_worker, "generate_draft", AsyncMock(return_value=DraftOutput(title='Title', summary='S', content='# Draft'))) as generate, \
             patch.object(writing_worker, "save_approved_draft", AsyncMock(return_value=99)) as save:
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            paused = [frame async for frame in source_response(graph, state, 11, 7, config).body_iterator]
            preview = parse_frames(paused, '__INTERRUPTED__:')[0]
            self.assertEqual(parse_frames(paused, '__ANSWER__:'), [])
            self.assertEqual(parse_frames(paused, '__AGENT_EVENT__:')[-1]['status'], 'awaiting')
            save.assert_not_awaited()
            config['configurable']['execution_token'] = 'second'
            resumed = [frame async for frame in source_response(graph, Command(resume={"action": "approve", "runId": RUN_ID,
                "draftHash": preview['draftHash']}), 11, 7, config).body_iterator]
        self.assertEqual(generate.await_count, 1)
        self.assertEqual(save.await_count, 1)
        self.assertEqual(save.call_args.args[0]['execution_token'], 'second')
        events = parse_frames(resumed, '__AGENT_EVENT__:')
        self.assertTrue(any(event.get('step') == 'save_draft' and event['status'] == 'done' for event in events))
        self.assertEqual(events[-1]['status'], 'complete')

    async def test_verified_chunking_preserves_unicode_code_and_literal_backslashes(self):
        text = ('中文🙂\n```python\npath = "C:\\new\\file"\n```\n' * 60)
        frames = list(main._answer_frames(text))
        chunks = parse_frames(frames, '__ANSWER__:')
        self.assertGreater(sum(event['type'] == 'delta' for event in chunks), 1)
        self.assertEqual(''.join(event['content'] for event in chunks if event['type'] == 'delta'), text)
        self.assertEqual(parse_frames(frames, '__REPLY__:')[0]['content'], text)
