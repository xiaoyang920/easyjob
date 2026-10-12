import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'

import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.services.run_history import RunHistory, project_history, progress_snapshot
from app.graph import main_agent as main
from app.graph.state_factory import create_initial_state
from app.services.run_service import RunService, public_run_result
from fakes import repository

RID = '11111111-1111-4111-8111-111111111111'


def row(**data):
    return SimpleNamespace(_mapping=data)


def result(**extra):
    return {'task_id': 'search_1', 'kind': 'search', 'actor': 'main', 'status': 'succeeded',
            'retrieval_target': 'knowledge', 'result': '完整结果', 'instruction': '检索资料',
            'citations': [], 'article_cards': [], **extra}


def run(**extra):
    return {'run_id': RID, 'conversation_id': 11, 'user_id': 7, 'status': 'failed',
            'draft_article_id': None, 'created_at': datetime(2026, 10, 11, 1),
            'updated_at': datetime(2026, 10, 11, 1, 1),
            'result_json': json.dumps({'user_message_id': '1', 'progress': {
                'node': 'main_agent', 'tasks': {'search_1': 'succeeded'}, 'results': {'search_1': result()}}}), **extra}


class HistoryProjectionTests(unittest.TestCase):
    def test_internal_projection_is_not_returned_in_run_payload(self):
        public = public_run_result(json.dumps({'reply': 'ok', 'progress': {'results': 'private'}, 'user_message_id': '1'}))
        self.assertEqual(public, {'reply': 'ok'})

    def test_old_failures_remain_between_their_input_and_later_turns(self):
        messages = [{'messageId': '1', 'role': 'user', 'content': '第一问'},
                    {'messageId': '2', 'role': 'user', 'content': '下一问'},
                    {'role': 'assistant', 'content': '下一轮成功'}]
        second = run(run_id='second', result_json=json.dumps({'user_message_id': '2'}))
        projected = project_history(messages, [run(), second], {}, {})
        self.assertEqual([m.get('runId') for m in projected], [None, RID, None, 'second', None])
        self.assertNotIn('execution_token', projected[1])
        self.assertFalse(projected[1]['recoverable'])

    def test_frame_activities_keep_original_timestamps_and_distinct_status(self):
        activity = {'version': 1, 'kind': 'activity', 'id': 'search', 'label': '检索', 'status': 'done'}
        frames = {RID: [{'data': 'data:__AGENT_EVENT__:' + json.dumps(activity) + '\n\n',
                         'created_at': datetime(2026, 10, 11, 1, 0, 5)}]}
        history = project_history([{'messageId': '1', 'role': 'user'}], [run()], frames, {})
        self.assertEqual(history[1]['agentEvents'][0]['status'], 'done')
        self.assertEqual(history[1]['agentEvents'][0]['timestamp'], '2026-10-11T01:00:05Z')

    def test_old_cache_without_ids_uses_local_message_time_and_event_fallback(self):
        events = {RID: [{'node': 'round_2.main_agent', 'status': 'failed', 'created_at': datetime(2026, 10, 11, 1, 1)}]}
        messages = [{'role': 'user', 'content': '旧提问', 'createTime': '2026-10-11 09:00:02'},
                    {'role': 'user', 'content': '后续问题', 'createTime': '2026-10-11 09:02:00'}]
        projected = project_history(messages, [run(result_json='{}')], {}, events)
        self.assertEqual(projected[1]['runId'], RID)
        self.assertEqual(projected[1]['agentEvents'][0]['status'], 'error')

    def test_committed_draft_never_becomes_a_false_failure_message(self):
        self.assertEqual(project_history([], [run(draft_article_id=42)], {}, {}), [])

    def test_snapshot_excludes_private_failed_outputs_but_keeps_selected_readonly_work(self):
        state = {'task_results': {'ok': result(), 'draft': result(retrieval_target='drafts', draft_document={'secret': 'x'}),
                 'memory': result(retrieval_target='memory'), 'failed': result(status='tool_error'),
                 'previous': result(previous_run_id='older')}}
        snapshot = progress_snapshot(state, 'main_agent', 'failed')
        self.assertEqual(list(snapshot['results']), ['ok', 'previous'])
        self.assertEqual(snapshot['tasks']['failed'], 'tool_error')


class PreviousRunTests(unittest.IsolatedAsyncioTestCase):
    def service(self, previous=None, artifacts=None, verifier=None):
        database = SimpleNamespace(fetch_one=AsyncMock(return_value=row(**(previous or run()))),
            fetch_all=AsyncMock(side_effect=[[], artifacts or []]), fetch_val=AsyncMock(return_value='对比两篇文章'))
        return RunHistory(database, verifier or AsyncMock()), database

    async def test_verified_results_are_available_but_not_automatically_executed(self):
        service, database = self.service()
        summary, reusable = await service.previous(11, 7, 'current')
        self.assertEqual(summary['node'], 'main_agent')
        self.assertEqual(summary['original_request'], '对比两篇文章')
        self.assertEqual(list(reusable), ['previous_11111111_search_1'])
        self.assertEqual(next(iter(reusable.values()))['result'], '完整结果')
        self.assertEqual(database.fetch_one.await_args.args[1]['uid'], 7)

    async def test_partial_delegate_completion_loads_durable_artifact(self):
        service, _ = self.service(previous=run(result_json='{}'), artifacts=[row(task_id='a', result_json=json.dumps(result(task_id='a')))])
        summary, reusable = await service.previous(11, 7, 'current')
        self.assertIn('previous_11111111_a', reusable)
        self.assertEqual(summary['tasks']['a'], 'succeeded')

    async def test_abrupt_exit_uses_last_started_node_even_without_failure_snapshot(self):
        service, database = self.service(previous=run(status='expired'))
        database.fetch_all.side_effect = [[row(node='round_2.main_delegate', status='started')], []]
        summary, _ = await service.previous(11, 7, 'current')
        self.assertEqual(summary['node'], 'main_delegate')

    async def test_stale_sources_are_excluded_and_must_be_retrieved_again(self):
        verifier = AsyncMock(side_effect=ValueError('source changed'))
        service, _ = self.service(verifier=verifier)
        summary, reusable = await service.previous(11, 7, 'current')
        self.assertEqual(reusable, {})
        self.assertEqual(summary['unavailable_tasks'], ['search_1'])

    async def test_repeated_continuation_preserves_identity_and_original_web_age(self):
        tid = 'previous_11111111_search_1'
        old = result(task_id=tid, previous_run_id=RID, source_run_updated_at='2000-01-01T00:00:00Z')
        snapshot = progress_snapshot({'task_results': {tid: old}}, 'main_agent', 'failed')
        service, _ = self.service(previous=run(result_json=json.dumps({'progress': snapshot})))
        _, reusable = await service.previous(11, 7, 'current')
        self.assertEqual(list(reusable), [tid])
        self.assertEqual(reusable[tid]['source_run_updated_at'], '2000-01-01T00:00:00Z')
        old['citations'] = [{'url': 'https://example.com', 'id': 'web:1'}]
        snapshot = progress_snapshot({'task_results': {tid: old}}, 'main_agent', 'failed')
        service, _ = self.service(previous=run(result_json=json.dumps({'progress': snapshot})))
        summary, reusable = await service.previous(11, 7, 'current')
        self.assertEqual(reusable, {})
        self.assertEqual(summary['unavailable_tasks'], [tid])

    async def test_saved_side_effect_returns_identifier_without_reusable_work(self):
        service, database = self.service(previous=run(status='succeeded', draft_article_id=42))
        summary, reusable = await service.previous(11, 7, 'current')
        self.assertEqual(summary['saved_draft_id'], '42')
        self.assertEqual(reusable, {})
        self.assertEqual(database.fetch_all.await_count, 1)

    async def test_successful_ordinary_turn_does_not_resurrect_an_older_failure(self):
        service, database = self.service(previous=run(status='succeeded'))
        self.assertEqual(await service.previous(11, 7, 'current'), ({}, {}))
        database.fetch_all.assert_not_awaited()


class MainContinuationTests(unittest.IsolatedAsyncioTestCase):
    def test_inherited_artifacts_do_not_consume_new_action_budget(self):
        self.assertEqual(main.execution_task_count({'old': result(previous_run_id=RID),
            'page': result(source_context=True), 'new': result()}), 1)

    async def decide(self, selected):
        state = create_initial_state(7, '继续', [])
        tid = 'previous_11111111_search_1'
        state['previous_run'] = {'status': 'failed', 'reusable_results': {tid: result(task_id=tid, previous_run_id=RID)}}
        controller = SimpleNamespace(ainvoke=AsyncMock(return_value=main.MainDecision(action='answer', reply='整理完成',
            reuse_previous_results=selected, answer_dependencies=selected)))
        model = SimpleNamespace(with_structured_output=Mock(return_value=controller))
        with patch.object(main, 'get_llm', return_value=model), patch.object(main, 'assert_run', AsyncMock()), \
             patch.object(main, 'publish_route', AsyncMock()):
            return await main.decide_main_action(state)

    async def test_continue_explicitly_selects_a_verified_artifact_in_one_main_call(self):
        output = await self.decide(['previous_11111111_search_1'])
        self.assertEqual(output['final_reply'], '整理完成')
        self.assertIn('previous_11111111_search_1', output['task_results'])

    async def test_unrelated_question_does_not_import_old_results(self):
        output = await self.decide([])
        self.assertNotIn('task_results', output)

    async def test_invented_reuse_identifier_is_rejected(self):
        output = await self.decide(['invented'])
        self.assertIn('未通过校验', output['final_reply'])


class PreparationTests(unittest.IsolatedAsyncioTestCase):
    def service(self):
        conv = SimpleNamespace(resolve_origin=AsyncMock(return_value=None),
            get_context_for_llm=AsyncMock(return_value=[]), add_message=AsyncMock(return_value=123))
        repo = repository()
        repo.record_input = AsyncMock()
        history = SimpleNamespace(previous=AsyncMock(return_value=({'status': 'failed'}, {'old': result()})))
        service = RunService(conv, SimpleNamespace(load_context=AsyncMock(return_value={})), repo, history=history)
        request = SimpleNamespace(conversation_id=11, request_id='request', user_id=7,
            origin_article_id=None, message='继续', image_paths=[])
        return service, request

    async def test_preparation_supplies_candidates_without_auto_importing_them(self):
        service, request = self.service()
        with patch('app.services.run_service.preprocess_message', AsyncMock(return_value='继续')):
            _, _, state = await service.prepare_chat(request, None)
        service.repository.record_input.assert_awaited_once_with(RID, 'executor', 123)
        self.assertIn('old', state['previous_run']['reusable_results'])
        self.assertFalse(state['task_results'])

    async def test_image_preprocessing_failure_still_records_question_anchor(self):
        service, request = self.service()
        async def fail(*args):
            service.repository.record_input.assert_awaited_once_with(RID, 'executor', 123)
            raise TimeoutError('image unavailable')
        with patch('app.services.run_service.preprocess_message', fail), self.assertRaises(TimeoutError):
            await service.prepare_chat(request, None)
        service.repository.fail.assert_awaited_once_with(RID, 'executor')
        service.history.previous.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
