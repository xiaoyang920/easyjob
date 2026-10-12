"""User intent, graph state and persistence arbitration for structured memory."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
os.environ["AGENT_SERVICE_KEY"] = "offline-service-key-32-bytes-long!!"

import copy
import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from sqlalchemy import text

from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver

from app import main, migrate
from app.graph import builder, main_agent as agent, staged_runtime as runtime
from app.graph.main_agent import MainDecision, RetrievalRequest
from app.graph.nodes import memory_retrieval
from app.graph.staged_plan import ExecutionTask
from app.graph.state_factory import create_initial_state
from app.models.memory_change import MemoryChange, validate_memory_changes
from app.services.memory import MemoryService, memory_service
from app.services.memory_policy import MemoryPolicyService
from app.services.run_service import RunService
from app.security.capabilities import effective_capabilities
from fakes import RUN_ID, repository
from test_main_agent import llm, run_updates
from test_phase0 import services
from test_streaming import parse_frames, result as stream_result


def row(**data):
    return SimpleNamespace(_mapping=data)


def state(text="以后默认简短回答", cid=11):
    value = create_initial_state(7, text, [])
    value.update(conversation_id=cid, run_id=RUN_ID, execution_token="executor")
    return value


def change(**values):
    return MemoryChange(kind="profile", scope="user", key="preferences.detail", value="brief",
                        source_quote="以后默认简短回答", **values)


class MemoryDatabase:
    """Transaction-aware DB fixture; actual service composes and executes SQL."""
    def __init__(self):
        self.profile = {"tech_stack": "[]", "interests": "[]", "experience": "unknown", "preferences": "{}"}
        self.records, self.receipts, self.queries, self.transactions = {}, {}, [], []
        self.jobs = {}
        self.alive = True
        self.fail_receipt = False

    @asynccontextmanager
    async def transaction(self):
        before = copy.deepcopy((self.profile, self.records, self.receipts, self.jobs))
        try:
            yield
        except BaseException:
            self.profile, self.records, self.receipts, self.jobs = before
            self.transactions.append("rollback")
            raise
        else:
            self.transactions.append("commit")

    async def fetch_one(self, sql, params):
        text(sql).bindparams(**params)
        self.queries.append((sql, params))
        if "FROM agent_run" in sql:
            return row(run_id=params["rid"]) if self.alive else None
        if "FROM user_memory_change" in sql:
            result = self.receipts.get(params["rid"])
            return row(**result) if result else None
        if "FROM user_profile" in sql:
            return row(**self.profile)
        if "FROM user_memory" in sql:
            for r in self.records.values():
                if 'CAST(content AS BINARY)=CAST(:content AS BINARY)' in sql:
                    if r['memory_type'] == 'decision' and r['user_id'] == params['uid'] and r['scope'] == params['scope'] and r['status'] == 'active' and r['content'] == params['content'] and (r['scope'] == 'user' or r['scope_conversation_id'] == params['cid']):
                        return row(**r)
                    continue
                if (r["user_id"], r["memory_type"], r["scope"], r["memory_key"], r["status"]) == (
                        params["uid"], params["type"], params["scope"], params["key"], "active") and (
                        r["scope"] == "user" or r["scope_conversation_id"] == params["cid"]):
                    return row(**r)
            return None
        raise AssertionError(sql)

    async def fetch_all(self, sql, params):
        text(sql).bindparams(**params)
        self.queries.append((sql, params))
        if 'memory_key IN' in sql:
            return [row(**r) for r in self.records.values() if r['user_id'] == params['uid']
                and r['memory_type'] == params['type'] and r['scope'] == params['scope'] and r['status'] == 'active'
                and r['memory_key'] in [v for k, v in params.items() if k.startswith('key') and k != 'key']
                and (r['scope'] == 'user' or r['scope_conversation_id'] == params['cid'])][:2]
        if "FROM user_memory_change" in sql:
            return [row(run_id=rid, result_json=r["result_json"]) for rid, r in self.receipts.items()
                    if r["user_id"] == params["uid"] and not r.get("index_synced")]
        if "SELECT memory_id FROM user_memory" in sql:
            return [row(memory_id=r["memory_id"]) for r in self.records.values()
                    if r["user_id"] == params["uid"] and r["status"] == "active" and
                    r["memory_id"] in [v for k, v in params.items() if k.startswith("id")]]
        return [row(**r) for r in self.records.values() if r["user_id"] == params["uid"] and
                r["memory_type"] == "constraint" and r["status"] == "active" and
                (r["scope"] == "user" or r["scope_conversation_id"] == params["cid"])][:33]

    async def execute(self, sql, params):
        text(sql).bindparams(**params)
        if 'INSERT IGNORE INTO agent_background_job' in sql:
            self.jobs.setdefault(params['id'], copy.deepcopy(params))
            return
        self.queries.append((sql, params))
        if "INSERT INTO user_profile" in sql:
            return
        if "UPDATE user_profile" in sql:
            self.profile.update(tech_stack=params["ts"], interests=params["it"], experience=params["exp"], preferences=params["pref"], summary="")
        elif "INSERT INTO user_memory_change" in sql:
            if self.fail_receipt:
                raise RuntimeError("receipt unavailable")
            self.receipts[params["rid"]] = {"user_id": params["uid"], "conversation_id": params["cid"],
                "change_hash": params["hash"], "result_json": params["result"]}
        elif "INSERT INTO user_memory" in sql:
            self.records[params["mid"]] = {"memory_id": params["mid"], "user_id": params["uid"],
                "content": params["content"], "memory_type": params["type"], "scope": params["scope"],
                "scope_conversation_id": params["scope_cid"], "memory_key": params["key"], "status": "active"}
        elif "UPDATE user_memory" in sql:
            if "UPDATE user_memory_change" in sql:
                self.receipts[params["rid"]]["index_synced"] = 1
            else:
                self.records[params["mid"]]["status"] = "inactive"
        else:
            raise AssertionError(sql)


class MemoryContractTests(unittest.TestCase):
    def test_aliases_are_one_identity_and_legacy_record_ids_remain_valid(self):
        s = state('这篇文章面向新手')
        a = MemoryChange(kind='constraint', key='audience', value='新手', source_quote=s['user_message'])
        b = MemoryChange(kind='constraint', key='target_audience', value='新手', source_quote=s['user_message'])
        self.assertEqual(a.key, 'article_audience')
        with self.assertRaises(ValueError):
            validate_memory_changes(s, [a, b])
        s['active_constraints'] = [{'id': '42', 'type': 'constraint', 'key': 'audience', 'scope': 'conversation'}]
        validate_memory_changes(s, [b.model_copy(update={'record_id': '42'})])
    def test_changes_are_bound_to_current_raw_user_message_and_known_records(self):
        s = state()
        validate_memory_changes(s, [change()])
        for overrides in ({"memory_source_message": "普通问题"}, {"memory_changes_applied": True}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                validate_memory_changes({**s, **overrides}, [change()])
        c = MemoryChange(kind="constraint", operation="remove", key="audience", scope="conversation", record_id="42", source_quote="取消这个要求")
        s = state("取消这个要求")
        s["active_constraints"] = [{"id": "42", "type": "constraint", "key": "audience", "scope": "conversation"}]
        validate_memory_changes(s, [c])
        with self.assertRaises(ValueError):
            validate_memory_changes(s, [c.model_copy(update={"record_id": "99"})])

    def test_no_identity_grants_arbitrary_profile_fields_or_duplicate_changes(self):
        for extra in ({"user_id": 9}, {"conversation_id": 99}, {"capabilities": ["memory_write"]},
                      {"key": "admin"}, {"value": {"nested": "object"}}, {"scope": "conversation"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                MemoryChange.model_validate({**change().model_dump(), **extra})
        with self.assertRaises(ValueError):
            validate_memory_changes(state(), [change(), change()])

    def test_recalled_decision_can_be_removed_but_execution_history_cannot(self):
        s = state("忘掉之前的决定")
        c = MemoryChange(kind="decision", key="article_format", scope="conversation", operation="remove", record_id="42", source_quote=s["user_message"])
        s["action_history"] = [{"task_id": "42"}]
        with self.assertRaises(ValueError):
            validate_memory_changes(s, [c])
        s["task_results"] = {"history": {"status": "succeeded", "retrieval_target": "memory", "memory_sources": [
            {"id": "memory:42", "type": "decision", "scope": "conversation", "key": "article_format"}]}}
        validate_memory_changes(s, [c])

    def test_network_constraint_restricts_even_forged_grants_but_never_enables_a_disabled_tool(self):
        s = state()
        s["active_constraints"] = [{"id": "42", "key": "web_search", "content": "deny"}]
        task = ExecutionTask(task_id="lookup", kind="search", actor="main", instruction="find", allow_web=True)
        ctx = runtime.task_context(s, task)
        ctx["capabilities"] = ["web_search", "platform_read"]
        with patch.object(agent.settings, "AGENT_WEB_SEARCH_ENABLED", True):
            self.assertNotIn("web_search", effective_capabilities(ctx))
            s["constraint_overrides"] = ["42"]
            self.assertIn("web_search", effective_capabilities(runtime.task_context(s, task)))
        s["active_constraints"][0]["content"] = "allow"
        with patch.object(agent.settings, "AGENT_WEB_SEARCH_ENABLED", False):
            self.assertNotIn("web_search", effective_capabilities(runtime.task_context(s, task)))


class MemoryPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.database = MemoryDatabase()
        self.service = MemoryPolicyService(self.database)
        self.sync = patch.object(memory_service, "sync_changes", AsyncMock(return_value=True))
        self.index = self.sync.start()
        self.addCleanup(self.sync.stop)

    async def test_profile_set_remove_and_exact_checkpoint_replay(self):
        s = state()
        result = await self.service.apply_changes(s, [change()])
        self.assertEqual(result["user_profile"]["preferences"], {"detail": "brief"})
        self.assertTrue(result["memory_changes_applied"])
        original_count = len(self.database.queries)
        replay = await self.service.apply_changes(s, [change()])
        self.assertEqual(result, replay)
        self.assertFalse(any("INSERT INTO user_memory_change" in q for q, _ in self.database.queries[original_count:]))
        s = state("以后不用简短回答")
        s.update(run_id="second", user_profile=result["user_profile"])
        c = MemoryChange(kind="profile", scope="user", key="preferences.detail", operation="remove", source_quote=s["user_message"])
        result = await self.service.apply_changes(s, [c])
        self.assertEqual(result["user_profile"]["preferences"], {})
        self.assertEqual(self.database.profile["summary"], "")

    async def test_receipt_failure_rolls_back_profile_and_never_updates_index(self):
        self.database.fail_receipt = True
        with self.assertRaises(RuntimeError):
            await self.service.apply_changes(state(), [change()])
        self.assertEqual(self.database.profile["preferences"], "{}")
        self.assertEqual(self.database.transactions, ["rollback"])
        self.index.assert_not_awaited()

    async def test_self_described_experience_preserves_other_profile_fields(self):
        self.database.profile.update(tech_stack='["Java"]', interests='["Redis"]',
                                     preferences='{"code_language":"Java"}')
        s = state('我是个新手你给我解释详细')
        s['user_profile'] = {'tech_stack': ['Java'], 'interests': ['Redis'],
                             'experience': 'unknown', 'preferences': {'code_language': 'Java'}}
        c = MemoryChange(kind='profile', scope='user', key='experience',
                         value='用户自述为新手，具体领域未说明', source_quote='我是个新手')
        validate_memory_changes(s, [c])
        result = await self.service.apply_changes(s, [c])
        self.assertEqual(result['user_profile']['experience'], c.value)
        self.assertEqual(result['user_profile']['preferences'], {'code_language': 'Java'})
        self.assertEqual(result['user_profile']['topics'], ['Redis', 'Java'])
        self.assertEqual(self.database.profile['tech_stack'], '[]')
        self.assertEqual(result['active_constraints'], [])
        self.assertIn(RUN_ID, self.database.receipts)

    async def test_topics_changes_preserve_background_and_detect_concurrent_edit(self):
        from app.models.memory_identity import MemoryConflict
        self.database.profile.update(tech_stack='["Java"]', interests='["Redis"]', experience='Python新手', preferences='{"code_language":"Java"}')
        s = state('记住我也长期关注Agent')
        s.update(await self.service.load_context(7, 11))
        c = MemoryChange(kind='profile', scope='user', key='topics', value=['Redis', 'Java', 'Agent'], source_quote='长期关注Agent')
        result = await self.service.apply_changes(s, [c])
        self.assertEqual(result['user_profile'], {'topics': ['Redis', 'Java', 'Agent'], 'experience': 'Python新手', 'preferences': {'code_language': 'Java'}})
        stale = state('以后只关注Python')
        stale.update(run_id='next', user_profile=s['user_profile'])
        with self.assertRaises(MemoryConflict):
            await self.service.apply_changes(stale, [MemoryChange(kind='profile', scope='user', key='topics', value=['Python'], source_quote='只关注Python')])
        self.assertEqual((await self.service.load_context(7, 11))['user_profile']['topics'], ['Redis', 'Java', 'Agent'])

    async def test_cancelled_run_and_changed_profile_reject_without_overwrite(self):
        self.database.alive = False
        with self.assertRaises(HTTPException):
            await self.service.apply_changes(state(), [change()])
        self.assertFalse(any("UPDATE user_profile" in q for q, _ in self.database.queries))
        self.database.alive = True
        self.database.profile["preferences"] = '{"detail":"detailed"}'
        with self.assertRaises(ValueError):
            await self.service.apply_changes(state(), [change()])
        self.assertEqual(self.database.profile["preferences"], '{"detail":"detailed"}')

    async def test_constraint_survives_next_run_but_not_another_conversation_then_is_deactivated(self):
        s = state("这篇文章面向初学者")
        c = MemoryChange(kind="constraint", key="article_audience", value="面向初学者", source_quote=s["user_message"])
        result = await self.service.apply_changes(s, [c])
        self.assertEqual(result["active_constraints"][0]["content"], "面向初学者")
        self.assertEqual((await self.service.load_context(7, 11))["active_constraints"], result["active_constraints"])
        self.assertEqual((await self.service.load_context(7, 12))["active_constraints"], [])
        self.assertEqual((await self.service.load_context(8, 11))["active_constraints"], [])
        s = state("取消初学者这个要求")
        s.update(run_id="next", active_constraints=result["active_constraints"], user_profile=result["user_profile"])
        c = MemoryChange(kind="constraint", key="article_audience", operation="remove", record_id=result["active_constraints"][0]["id"], source_quote=s["user_message"])
        result = await self.service.apply_changes(s, [c])
        self.assertEqual(result["active_constraints"], [])
        self.assertEqual(next(iter(self.database.records.values()))["status"], "inactive")
        self.assertEqual(self.index.await_args.args[1], [int(c.record_id)])

    async def test_decision_is_indexed_and_not_injected_as_a_constraint(self):
        s = state("我们决定这篇文章采用教程形式")
        c = MemoryChange(kind="decision", key="article_format", value="采用教程形式", source_quote=s["user_message"])
        result = await self.service.apply_changes(s, [c])
        self.assertEqual(result["active_constraints"], [])
        indexed = self.index.await_args.args[0][0]
        self.assertEqual((indexed["type"], indexed["scope"], indexed["scope_cid"]), ("decision", "conversation", 11))

    async def test_replacement_keeps_old_history_inactive_and_creates_new_record(self):
        s = state("这篇文章面向初学者")
        first = await self.service.apply_changes(s, [MemoryChange(kind="constraint", key="audience", value="初学者", source_quote=s["user_message"])])
        s = state("改成面向有经验的开发者")
        s.update(run_id="next", active_constraints=first["active_constraints"], user_profile=first["user_profile"])
        old_id = first["active_constraints"][0]["id"]
        result = await self.service.apply_changes(s, [MemoryChange(kind="constraint", key="audience", value="有经验的开发者", record_id=old_id, source_quote=s["user_message"])])
        self.assertNotEqual(result["active_constraints"][0]["id"], old_id)
        self.assertEqual(self.database.records[int(old_id)]["status"], "inactive")

    async def test_failed_index_is_durable_and_retried_before_history_lookup(self):
        self.index.return_value = False
        s = state("我们决定这篇文章采用教程形式")
        c = MemoryChange(kind="decision", key="article_format", value="采用教程形式", source_quote=s["user_message"])
        await self.service.apply_changes(s, [c])
        self.assertFalse(self.database.receipts[RUN_ID].get("index_synced"))
        with self.assertRaises(ConnectionError):
            await self.service.flush_pending_index(7)
        self.index.return_value = True
        await self.service.flush_pending_index(7)
        self.assertEqual(self.database.receipts[RUN_ID]["index_synced"], 1)
        self.assertEqual(self.index.await_args.args[0][0]["type"], "decision")

    async def test_index_timeout_leaves_committed_memory_available_for_retry(self):
        self.index.side_effect = TimeoutError()
        result = await self.service.apply_changes(state(), [change()])
        self.assertEqual(result["user_profile"]["preferences"], {"detail": "brief"})
        self.assertFalse(self.database.receipts[RUN_ID].get("index_synced"))

    async def test_changed_replay_and_unreferenced_replacement_are_rejected(self):
        s = state("这篇文章面向初学者")
        c = MemoryChange(kind="constraint", key="audience", value="初学者", source_quote=s["user_message"])
        await self.service.apply_changes(s, [c])
        with self.assertRaises(ValueError):
            await self.service.apply_changes(s, [c.model_copy(update={"value": "专家"})])
        s["run_id"] = "different-run"
        with self.assertRaises(ValueError):
            await self.service.apply_changes(s, [c.model_copy(update={'value': '专家'})])

    async def test_alias_repeat_is_noop_and_explicit_replacement_has_one_active_record(self):
        s = state('这篇文章面向初学者')
        c = MemoryChange(kind='constraint', key='audience', value='初学者', source_quote=s['user_message'])
        first = await self.service.apply_changes(s, [c])
        mid = first['active_constraints'][0]['id']
        # Simulate a legacy field name in storage, without rewriting user data.
        self.database.records[int(mid)]['memory_key'] = 'target_audience'
        s.update(run_id='repeat', active_constraints=first['active_constraints'])
        repeated = await self.service.apply_changes(s, [c.model_copy(update={'key': 'article_audience'})])
        self.assertEqual(len(self.database.records), 1)
        self.assertEqual(repeated['memory_change_log'][0]['operation'], 'unchanged')
        s.update(run_id='replace', user_message='以后这篇文章面向专家', memory_source_message='以后这篇文章面向专家')
        replacement = MemoryChange(kind='constraint', key='reader_level', value='专家', record_id=mid, source_quote=s['user_message'])
        after = await self.service.apply_changes(s, [replacement])
        self.assertEqual(len(after['active_constraints']), 1)
        self.assertEqual(after['active_constraints'][0]['content'], '专家')
        self.assertEqual(self.database.records[int(mid)]['status'], 'inactive')

    async def test_same_decision_under_a_different_key_is_not_saved_twice(self):
        s = state('我们决定采用教程形式')
        c = MemoryChange(kind='decision', key='article_format', value='教程形式', source_quote=s['user_message'])
        await self.service.apply_changes(s, [c])
        s['run_id'] = 'repeat'
        after = await self.service.apply_changes(s, [c.model_copy(update={'key': 'tutorial_choice'})])
        self.assertEqual(len(self.database.records), 1)
        self.assertEqual(after['memory_change_log'][0]['operation'], 'unchanged')
        s.update(run_id='other-conversation', conversation_id=12)
        await self.service.apply_changes(s, [c])
        self.assertEqual(len(self.database.records), 2)

    async def test_old_pending_upsert_cannot_restore_an_inactive_decision(self):
        self.index.return_value = False
        s = state("决定采用教程形式")
        c = MemoryChange(kind="decision", key="format", value="教程形式", source_quote=s["user_message"])
        await self.service.apply_changes(s, [c])
        mid = next(iter(self.database.records))
        self.database.records[mid]["status"] = "inactive"
        self.index.return_value = True
        await self.service.flush_pending_index(7)
        self.assertEqual(self.index.await_args.args, ([], [mid]))


class StartupAndGraphTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        history = patch('app.services.run_service.run_history.previous', AsyncMock(return_value=({}, {})))
        history.start()
        self.addCleanup(history.stop)
        fence = patch("app.graph.staged_runtime.run_repository", repository())
        fence.start()
        self.addCleanup(fence.stop)

    async def test_each_request_loads_profile_and_constraints_without_vector_recall(self):
        conversations, memory = services()
        memory.load_context.return_value = {"user_profile": {"preferences": {"language": "zh"}}, "active_constraints": []}
        for cid in (None, 11):
            request = main.ChatRequest(user_id=7, conversation_id=cid, message="普通问题")
            _, _, snapshot = await RunService(conversations, memory, repository()).prepare_chat(request, None)
            self.assertEqual(snapshot["user_profile"]["preferences"]["language"], "zh")
            self.assertEqual(snapshot["memory_context"], "")
        self.assertEqual(memory.load_context.await_count, 2)
        memory.recall.assert_not_awaited()

    async def test_context_load_failure_fails_run_instead_of_silently_dropping_constraints(self):
        conversations, memory = services()
        memory.load_context.side_effect = ConnectionError()
        repo = repository()
        with self.assertRaises(ConnectionError):
            await RunService(conversations, memory, repo).prepare_chat(main.ChatRequest(user_id=7, message="q"), None)
        repo.fail.assert_awaited_once()

    async def test_main_queues_in_same_call_and_passes_turn_overlay_without_claiming_persistence(self):
        c = change()
        model, control = llm([MainDecision(action="retrieve", retrieval=RetrievalRequest(instruction="history", target="memory"), memory_changes=[c]),
                              MainDecision(action="answer", reply="简短回答")])
        applied = {"memory_changes_queued": True, 'pending_memory_changes': [c.model_dump()], 'memory_write_status': 'pending'}
        with patch.object(agent, "get_llm", return_value=model), patch.object(agent.memory_policy_service, "enqueue_changes", AsyncMock(return_value=applied)) as save, \
             patch.object(memory_retrieval.memory_service, "recall_details", AsyncMock(return_value={"memories": []})):
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), state())
        self.assertEqual(control.ainvoke.await_count, 2)
        save.assert_awaited_once()
        messages = control.ainvoke.await_args_list[1].args[0]
        ctx = json.loads(messages[1].content)
        self.assertTrue(ctx["memory_changes_queued"])
        self.assertFalse(ctx["memory_changes_applied"])
        self.assertEqual(ctx["user_profile"]["preferences"]["detail"], "brief")
        self.assertNotIn('"preferences": {"detail": "brief"}', messages[0].content)
        self.assertIn('简短回答', result['final_reply'])
        self.assertIn('后台保存', result['final_reply'])

    async def test_memory_queue_failure_does_not_block_the_requested_action(self):
        from app.models.memory_identity import MemoryConflict
        decision = MainDecision(action='retrieve', retrieval=RetrievalRequest(instruction='find'), memory_changes=[change()])
        model, _ = llm([decision])
        with patch.object(agent, 'get_llm', return_value=model), \
             patch.object(agent.memory_policy_service, 'enqueue_changes', AsyncMock(side_effect=ConnectionError('database unavailable'))), \
             patch.object(agent, 'publish_route', AsyncMock()) as route:
            result = await agent.decide_main_action(state())
        self.assertEqual(result['main_action'], 'retrieve')
        self.assertEqual(result['memory_write_status'], 'failed')
        self.assertEqual(result['pending_memory_changes'][0]['value'], 'brief')
        route.assert_awaited_once()
        self.assertFalse(result.get('memory_changes_applied'))

    async def test_turn_override_is_not_persisted_and_reaches_execution_context(self):
        s = state("这次不用初学者这个要求")
        s["active_constraints"] = [{"id": "42", "content": "面向初学者", "type": "constraint", "key": "audience", "scope": "conversation"}]
        model, _ = llm([MainDecision(action="answer", reply="好的", constraint_overrides=["42"])])
        with patch.object(agent, "get_llm", return_value=model), patch.object(agent.memory_policy_service, "apply_changes", AsyncMock()) as save:
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), s)
        save.assert_not_awaited()
        ctx = runtime.task_context(result, ExecutionTask(task_id="draft", actor="main", kind="writing", instruction="write"))
        self.assertEqual(ctx["active_constraints"], [])
        self.assertEqual(result["active_constraints"], s["active_constraints"])
        self.assertEqual(create_initial_state(7, "next", [])["constraint_overrides"], [])

    async def test_old_history_quote_cannot_write_memory_and_receives_one_repair(self):
        model, control = llm([MainDecision(action="answer", reply="已记住", memory_changes=[change()]), MainDecision(action="answer", reply="正常回答")])
        s = state("普通问题")
        s["history_messages"] = [{"role": "user", "content": "以后默认简短回答"}]
        with patch.object(agent, "get_llm", return_value=model), patch.object(agent.memory_policy_service, "apply_changes", AsyncMock()) as save:
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), s)
        self.assertEqual(control.ainvoke.await_count, 2)
        save.assert_not_awaited()
        self.assertEqual(result["final_reply"], "正常回答")

    async def test_save_failure_never_claims_success_but_still_answers(self):
        model, _ = llm([MainDecision(action="answer", reply="已保存偏好", memory_changes=[change()])])
        with patch.object(agent, "get_llm", return_value=model), patch.object(agent.memory_policy_service, "enqueue_changes", AsyncMock(side_effect=RuntimeError("DB unavailable"))):
            result, _ = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), state())
        self.assertNotIn('已保存偏好', result['final_reply'])
        self.assertIn('未能提交', result['final_reply'])

    async def test_memory_update_activity_contains_no_profile_constraint_or_source_quote(self):
        s = state()
        s["user_profile"] = {"preferences": {"style": "private-style-marker"}}
        s["active_constraints"] = [{"id": "42", "content": "private-constraint-marker"}]
        model, _ = llm([MainDecision(action="answer", reply="好的", memory_changes=[change()])])
        service = SimpleNamespace(repository=repository(), finish=AsyncMock(return_value=stream_result("好的")))
        config = {"configurable": {"thread_id": "structured-memory-stream", "run_id": RUN_ID, "execution_token": "executor"}}
        with patch.object(agent, "get_llm", return_value=model), patch.object(main, "run_service", service), \
             patch.object(agent.memory_policy_service, "enqueue_changes", AsyncMock(return_value={"memory_changes_queued": True, 'memory_write_status': 'pending'})):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            frames = [f async for f in __import__("test_streaming").source_response(graph, s, 11, 7, config).body_iterator]
        events = parse_frames(frames, "__AGENT_EVENT__:")
        updates = [e for e in events if e.get("step") == "memory_update"]
        self.assertEqual([e["status"] for e in updates], ["active", "done"])
        raw = json.dumps(events, ensure_ascii=False)
        for secret in ("private-style-marker", "private-constraint-marker", s["user_message"]):
            self.assertNotIn(secret, raw)

    async def test_background_extraction_never_restores_profile_or_rules(self):
        service = MemoryService.__new__(MemoryService)
        service._llm = SimpleNamespace(with_structured_output=AsyncMock(side_effect=AssertionError('retired model called')))
        service._update_profile = AsyncMock()
        await service.extract_and_store(7, 11, [{"role": "user", "content": "old"}] * 4)
        service._update_profile.assert_not_awaited()


class SchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        pending = patch("app.services.memory_policy.memory_policy_service.flush_pending_index", AsyncMock())
        pending.start()
        self.addCleanup(pending.stop)

    async def test_memory_migration_replays_after_partial_upgrade_without_readding_columns(self):
        columns, receipt, executed = {"memory_id": "bigint", "memory_type": "varchar"}, {}, []
        async def fetch_all(sql):
            source = receipt if "TABLE_NAME='user_memory_change'" in sql else columns
            return [row(name=k, type=v) for k, v in source.items()]
        async def execute(sql, params=None):
            executed.append(sql)
            if "ADD COLUMN" in sql:
                name = sql.split("ADD COLUMN ")[1].split()[0]
                columns[name] = migrate.MEMORY_COLUMNS[name]
            if "CREATE TABLE" in sql:
                receipt.update(run_id="char", user_id="bigint", conversation_id="bigint", change_hash="char", result_json="json", index_synced="tinyint")
        connection = SimpleNamespace(fetch_all=fetch_all, execute=execute, fetch_one=AsyncMock(return_value=None), fetch_val=AsyncMock(return_value=1))
        @asynccontextmanager
        async def connect():
            yield connection
        await migrate.apply_memory_migration(SimpleNamespace(connection=connect))
        await migrate.apply_memory_migration(SimpleNamespace(connection=connect))
        self.assertEqual(sum("ADD COLUMN" in q for q in executed), 5)

    async def test_recall_uses_current_user_scope_status_and_never_loads_profile(self):
        service = MemoryService.__new__(MemoryService)
        service._search_memories = AsyncMock(return_value=[{"memory_id": 42}])
        service._get_profile = AsyncMock()
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[]), execute=AsyncMock())
        with patch("app.services.memory.db", database):
            result = await service.recall_details(7, "past decision", conversation_id=11, include_profile=False, strict=True)
        self.assertEqual(result["memories"], [])
        service._get_profile.assert_not_awaited()
        sql, params = database.fetch_all.await_args.args
        self.assertIn("status='active'", sql)
        self.assertIn("scope_conversation_id=:cid", sql)
        self.assertIn("memory_type='decision'", sql)
        self.assertEqual((params["uid"], params["cid"]), (7, 11))


if __name__ == "__main__":
    unittest.main()
