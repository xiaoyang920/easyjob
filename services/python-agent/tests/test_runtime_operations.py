import asyncio
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from langchain_core.messages import HumanMessage
from app.config import settings
from app.services.run_metrics import RunMetrics, RunTokenBudgetExceeded
from app.services.stream_delivery import StreamDelivery
from app.services.operations import Operations


class TokenBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_image_reservation_does_not_tokenize_base64(self):
        def image_message(size):
            return HumanMessage(content=[{'type':'text','text':'继续识别这张图片'},
                {'type':'image_url','image_url':{'url':'data:image/png;base64,'+'A'*size}}])
        measured = {'budget_charged_tokens':33311, 'llm_calls':2,
                    'measured_input_tokens':31677, 'measured_output_tokens':1634}
        small, large = RunMetrics(measured), RunMetrics(measured)
        params = {'max_tokens':8192}
        with patch.object(settings, 'RUN_TOTAL_TOKEN_BUDGET', 524288):
            await small.on_chat_model_start({}, [[image_message(100)]], run_id='image', invocation_params=params)
            await large.on_chat_model_start({}, [[image_message(4_000_000)]], run_id='image', invocation_params=params)
        self.assertEqual(small.reservations, large.reservations)
        self.assertGreaterEqual(large.reservations['image'], 8192+1024)
        self.assertLess(large.snapshot()['budget_charged_tokens'], 50000)

    async def test_schema_and_visual_tokens_still_obey_the_total_budget(self):
        image = HumanMessage(content=[{'type':'image_url','image_url':{'url':'data:image/png;base64,AAAA'}}])
        with patch.object(settings, 'RUN_TOTAL_TOKEN_BUDGET', 1000):
            with self.assertRaises(RunTokenBudgetExceeded):
                await RunMetrics().on_chat_model_start({}, [[image]], run_id='image', invocation_params={'max_tokens':100})
        schema = {'type':'function','function':{'name':'tool','description':'details '*500,
                  'parameters':{'type':'object','properties':{}}}}
        with patch.object(settings, 'RUN_TOTAL_TOKEN_BUDGET', 400):
            with self.assertRaises(RunTokenBudgetExceeded):
                await RunMetrics().on_chat_model_start({}, [[HumanMessage('hello')]], run_id='tool',
                    invocation_params={'max_tokens':100,'tools':[schema]})

    async def test_parallel_reservations_cannot_both_spend_remaining_budget(self):
        metrics = RunMetrics()
        with patch.object(settings, 'RUN_TOTAL_TOKEN_BUDGET', 200):
            await metrics.on_chat_model_start({}, [[HumanMessage('first')]], run_id='a', invocation_params={'max_tokens': 100})
            with self.assertRaises(RunTokenBudgetExceeded):
                await metrics.on_chat_model_start({}, [[HumanMessage('second')]], run_id='b', invocation_params={'max_tokens': 100})
        self.assertEqual(metrics.calls, {'a'})

    async def test_measured_usage_releases_reservation_and_resume_carries_spend(self):
        metrics = RunMetrics()
        await metrics.on_llm_start({}, ['hello'], run_id='a', invocation_params={'max_tokens': 100})
        response = SimpleNamespace(llm_output={'token_usage': {'prompt_tokens': 10, 'completion_tokens': 5}}, generations=[])
        await metrics.on_llm_end(response, run_id='a')
        await metrics.on_llm_end(response, run_id='a')
        self.assertEqual(metrics.charged, 15)
        self.assertEqual(metrics.reservations, {})
        resumed = RunMetrics(metrics.snapshot())
        with patch.object(settings, 'RUN_TOTAL_TOKEN_BUDGET', 150):
            with self.assertRaises(RunTokenBudgetExceeded):
                await resumed.on_llm_start({}, ['hello'], run_id='b', invocation_params={'max_tokens': 110})

    async def test_unknown_provider_failure_is_conservatively_charged(self):
        metrics = RunMetrics()
        await metrics.on_llm_start({}, ['hello'], run_id='a', invocation_params={'max_tokens': 100})
        reserved = metrics.reservations['a']
        await metrics.on_llm_error(TimeoutError(), run_id='a')
        self.assertEqual(metrics.charged, reserved)
        self.assertFalse(metrics.snapshot()['token_usage_complete'])


class BoundedDeliveryTests(unittest.TestCase):
    def test_execution_limit_preserves_partial_sources_without_claiming_completion(self):
        from app.graph.main_agent import bounded_evidence_reply
        source={'id':'r:web1','url':'https://example.org/guide','articleId':'','title':'guide','excerpt':'only one relevant source'}
        state={'task_results':{'r':{'status':'succeeded','retrieval_target':'knowledge','citations':[source],
            'retrieval_report':{'quality':{'adequacy':'partial'}}}}}
        reply=bounded_evidence_reply(state,'limit')
        self.assertEqual(reply['citations'],[source]); self.assertIn('[r:web1]',reply['final_reply'])
        self.assertIn('当前未完成全部要求',reply['final_reply'])
        self.assertTrue(reply['final_reply'].startswith('limit'))
        self.assertNotIn(source['excerpt'], reply['final_reply'])
        self.assertNotIn(source['title'], reply['final_reply'])
        self.assertIsNone(reply['article_cards'])
        self.assertEqual(reply['delivery_evidence']['citations'], [source])

    def test_limit_does_not_turn_irrelevant_or_failed_results_into_evidence(self):
        from app.graph.main_agent import bounded_evidence_reply
        state={'task_results':{'r':{'status':'succeeded','citations':[{'id':'bad','excerpt':'unrelated'}],
            'retrieval_report':{'quality':{'adequacy':'none'}}}}}
        reply=bounded_evidence_reply(state,'limit')
        self.assertIsNone(reply['citations']); self.assertTrue(reply['final_reply'].startswith('limit'))
        self.assertIn('当前未完成全部要求', reply['final_reply'])


class FrameDatabase:
    def __init__(self): self.frames = []
    async def execute(self, sql, params):
        row = {**params, 'event_id': len(self.frames)+1, 'data': params['data']}
        self.frames.append(row); return row['event_id']
    async def fetch_val(self, sql, params): return next((r['event_id'] for r in self.frames if r['rid']==params['rid'] and r['token']==params['token']), None)
    async def fetch_all(self, sql, params): return [SimpleNamespace(_mapping=r) for r in self.frames if r['rid']==params['rid'] and r['token']==params['token'] and r['event_id']>params['after']]


class StreamDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_pruned_stream_replay_keeps_incomplete_outcome_and_failure_notice(self):
        import json
        for result in ({'reply': '检索已返回，但请求未完成。', 'delivery_status': 'incomplete'},
                       {'failure_notice': '草稿核验超时，未进入审批或保存。'}):
            with self.subTest(result=result):
                run = {'status': 'succeeded' if result.get('reply') else 'failed', 'execution_token': 't',
                    'deadline': datetime.utcnow() + timedelta(minutes=1), 'result_json': json.dumps(result)}
                repo = SimpleNamespace(get=AsyncMock(return_value=run))
                delivery = StreamDelivery(FrameDatabase(), SimpleNamespace(), repo)
                with patch('app.services.stream_delivery.asyncio.sleep', AsyncMock()):
                    frames = ''.join([f async for f in delivery.follow('r', 't')])
                self.assertNotIn('__PROGRESS__:done', frames)
                if result.get('reply'):
                    self.assertIn('"status": "error"', frames)
                    self.assertIn('__REPLY__:', frames)
                else:
                    self.assertIn(result['failure_notice'], frames)

    async def test_direct_answer_sequence_survives_disconnect_and_cursor_replay(self):
        import json
        database, admission = FrameDatabase(), SimpleNamespace(release=AsyncMock())
        repository = SimpleNamespace(get=AsyncMock(return_value={'status': 'running', 'execution_token': 't',
            'deadline': datetime.utcnow() + timedelta(minutes=1)}), fail=AsyncMock())
        delivery = StreamDelivery(database, admission, repository)
        ready, resume = asyncio.Event(), asyncio.Event()
        def frame(value):
            return 'data:__ANSWER__:' + json.dumps(value, ensure_ascii=False) + '\n\n'
        async def source():
            yield frame({'type': 'start', 'mode': 'direct'})
            yield frame({'type': 'delta', 'seq': 0, 'content': '实时'})
            ready.set()
            await resume.wait()
            yield frame({'type': 'delta', 'seq': 1, 'content': '回答'})
            yield frame({'type': 'end', 'chunks': 2})
            yield 'data:__REPLY__:{"content":"实时回答"}\n\n'
            yield 'data:[DONE]\n\n'
        delivery.start('r', 't', source(), 'ticket')
        await ready.wait()
        reader = delivery.follow('r', 't')
        while '"seq": 0' not in await anext(reader):
            pass
        await reader.aclose()
        self.assertIn(('r', 't'), delivery.tasks)
        resume.set()
        await asyncio.gather(*list(delivery.tasks.values()))
        replay = ''.join([f async for f in delivery.follow('r', 't', after=2)])
        self.assertNotIn('"type": "start"', replay)
        self.assertNotIn('"seq": 0', replay)
        self.assertIn('"seq": 1', replay)
        self.assertIn('"chunks": 2', replay)
        self.assertIn('实时回答', replay)
        repository.fail.assert_not_awaited()
        admission.release.assert_awaited_once_with('ticket')

    async def test_disconnect_does_not_cancel_producer_and_cursor_replays_remaining_frames(self):
        database = FrameDatabase()
        admission = SimpleNamespace(release=AsyncMock())
        repository = SimpleNamespace(get=AsyncMock(return_value={'status':'running','execution_token':'t','deadline':datetime.utcnow()+timedelta(minutes=1)}), fail=AsyncMock())
        delivery = StreamDelivery(database, admission, repository)
        ready, continue_run = asyncio.Event(), asyncio.Event()
        async def source():
            yield 'data:first\n\n'
            ready.set(); await continue_run.wait()
            yield 'data:second\n\n'
            yield 'data:[DONE]\n\n'
        delivery.start('r','t',source(),'ticket')
        await ready.wait()
        reader = delivery.follow('r','t')
        self.assertIn('first', await anext(reader))
        await reader.aclose()
        self.assertIn(('r','t'), delivery.tasks)
        continue_run.set(); await asyncio.gather(*list(delivery.tasks.values()))
        replay = ''.join([frame async for frame in delivery.follow('r','t',after=1)])
        self.assertNotIn('first',replay); self.assertIn('second',replay); self.assertIn('[DONE]',replay)
        repository.fail.assert_not_awaited(); admission.release.assert_awaited_once_with('ticket')

    async def test_persisted_result_replay_does_not_execute_source_again(self):
        database=FrameDatabase(); admission=SimpleNamespace(release=AsyncMock()); repo=SimpleNamespace(fail=AsyncMock())
        delivery=StreamDelivery(database,admission,repo)
        await delivery.append('r','t','data:[DONE]\n\n')
        executed=[]
        async def source(): executed.append(True); yield 'data:duplicate\n\n'
        delivery.start('r','t',source(),'ticket',replay=True)
        await asyncio.gather(*list(delivery.tasks.values()))
        self.assertEqual(executed,[]); self.assertEqual(len(database.frames),1)

    async def test_old_execution_generation_is_not_replayed(self):
        database=FrameDatabase(); repo=SimpleNamespace(get=AsyncMock(return_value={'execution_token':'superseded'}))
        delivery=StreamDelivery(database,SimpleNamespace(),repo)
        await delivery.append('r','old','data:old secret\n\n')
        frames=''.join([frame async for frame in delivery.follow('r','new')])
        self.assertNotIn('old secret',frames)
        self.assertIn('[ERROR]',frames)


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_checkpoint_cleanup_rechecks_terminal_age_before_touching_redis(self):
        from app.services.durable_jobs import BackgroundWorker
        from contextlib import asynccontextmanager
        from uuid import uuid4
        rid = str(uuid4())
        locked = []
        @asynccontextmanager
        async def transaction():
            locked.append(True)
            try: yield
            finally: locked.pop()
        database = SimpleNamespace(fetch_one=AsyncMock(return_value=None), transaction=transaction)
        saver = SimpleNamespace(adelete_thread=AsyncMock())
        async def delete(thread):
            self.assertEqual(locked, [True])
        saver.adelete_thread.side_effect = delete
        graph = SimpleNamespace(checkpointer=saver)
        worker = BackgroundWorker(SimpleNamespace(db=database))
        job = {'kind': 'checkpoint_cleanup', 'user_id': 7, 'conversation_id': 11, 'payload': {'run_id': rid}}
        with patch('app.graph.builder.get_graph', AsyncMock(return_value=graph)) as load:
            await worker.handle(job)
            load.assert_not_awaited()
            database.fetch_one.return_value = SimpleNamespace(_mapping={'run_id': rid})
            await worker.handle(job)
        saver.adelete_thread.assert_awaited_once_with('run_' + rid)
        query = database.fetch_one.call_args.args[0]
        self.assertIn('r.user_id=:uid', query)
        self.assertIn("('succeeded','failed','cancelled','expired')", query)
        self.assertIn('FOR UPDATE', query)
        self.assertIn(":success_days", query)
        self.assertIn(":failure_days", query)
    async def test_dependency_outage_returns_unready_without_leaking_diagnostics(self):
        service=Operations(SimpleNamespace())
        service.probe_sql=AsyncMock(); service.probe_redis=AsyncMock(); service.probe_checkpoint=AsyncMock()
        service.probe_es=AsyncMock(side_effect=ConnectionError('password=secret'))
        result=await service.readiness()
        self.assertEqual(result['status'],'unready'); self.assertEqual(result['dependencies']['elasticsearch'],'down')
        self.assertNotIn('secret',str(result))
        await service.readiness(); service.probe_es.assert_awaited_once()

    async def test_retention_preserves_active_runs_and_is_bounded(self):
        database=SimpleNamespace(fetch_all=AsyncMock(return_value=[]),execute=AsyncMock())
        service=Operations(database)
        with patch('app.rpc.blog_client.maintenance', AsyncMock(return_value={})) as blog:
            await service.cleanup()
        queries=[call.args[0] for call in database.fetch_all.await_args_list]
        self.assertTrue(any("NOT IN ('running','awaiting_approval')" in q for q in queries))
        self.assertTrue(all(any(f'LIMIT {n}' in q for n in (20,100,500)) for q in queries))
        database.execute.assert_not_awaited()
        blog.assert_awaited_once_with('cleanup')
        self.assertFalse(any('article_read' in q or 'article_index_outbox' in q for q in queries))
        self.assertTrue(any('r.draft_article_id IS NULL' in q for q in queries))
        self.assertTrue(any("('succeeded','failed','cancelled','expired')" in q for q in queries))

    async def test_quality_metrics_are_bounded_and_do_not_expose_conversation_content(self):
        import json
        def row(**v): return SimpleNamespace(_mapping=v)
        database = SimpleNamespace(fetch_all=AsyncMock(side_effect=[
            [row(status='succeeded', metrics=json.dumps({'llm_calls': 4, 'failed_llm_calls': 1,
                'measured_input_tokens': 100, 'measured_output_tokens': 20, 'token_usage_complete': False}))],
            [row(node='retrieval/rerank', status='degraded', duration_ms=8),
             row(node='round_1.main_agent', status='succeeded', duration_ms=12),
             row(node='approval', status='conflict', duration_ms=None)]]))
        result = await Operations(database).recent_quality()
        self.assertEqual(result['model_failure_rate'], .25)
        self.assertEqual(result['rerank_degraded_rate'], 1)
        self.assertEqual(result['approval_conflicts'], 1)
        self.assertEqual(result['stages']['main_agent']['p95_ms'], 12)
        self.assertTrue(all('LIMIT ' in c.args[0] for c in database.fetch_all.await_args_list))
        self.assertNotIn('result_json', str(result))

    async def test_old_metrics_do_not_fabricate_a_zero_model_failure_rate(self):
        database = SimpleNamespace(fetch_all=AsyncMock(side_effect=[
            [SimpleNamespace(_mapping={'status': 'succeeded', 'metrics': {'llm_calls': 2}})], []]))
        result = await Operations(database).recent_quality()
        self.assertIsNone(result['model_failure_rate'])
