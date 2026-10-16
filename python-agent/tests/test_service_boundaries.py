import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
import httpx
from app.rpc.discovery import Catalog
from app.rpc import blog_client
from app.services import draft_commit, service_queries


class Transaction:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_stable_routing_bounded_stale_cache_and_no_direct_fallback(self):
        catalog=Catalog()
        response=SimpleNamespace(json=lambda:[{'Service':{'Address':'127.0.0.1','Meta':{'rpc_port':'20881'}}}])
        catalog.http=AsyncMock(return_value=response)
        await catalog.refresh()
        self.assertEqual(await catalog.target(7),'127.0.0.1:20881')
        self.assertEqual(await catalog.target(7),'127.0.0.1:20881')
        catalog.http.assert_awaited_once()
        catalog.http.side_effect=httpx.ConnectError('offline')
        catalog.refreshed=time.monotonic()-6
        self.assertEqual(await catalog.target(7),'127.0.0.1:20881')
        catalog.refreshed=time.monotonic()-31
        with self.assertRaises(RuntimeError): await catalog.target(7)

    async def test_healthy_query_with_no_instances_withdraws_stale_peer_immediately(self):
        catalog=Catalog();catalog.peers=['old:1'];catalog.refreshed=time.monotonic()-6
        catalog.http=AsyncMock(return_value=SimpleNamespace(json=lambda:[]))
        await catalog.refresh()
        with self.assertRaises(RuntimeError): await catalog.target(7)


class SaveBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_save_permission_is_never_returned_in_public_run_result(self):
        from app.services.run_service import public_run_result
        self.assertEqual(public_run_result({'reply':'ok','draft_commit':{'permit':'secret'},'progress':{}}),{'reply':'ok'})

    def database(self, intent):
        return SimpleNamespace(fetch_all=AsyncMock(return_value=[SimpleNamespace(_mapping={
            'run_id':'r','user_id':7,'result_json':json.dumps({'draft_commit':intent})})]),
            execute=AsyncMock())

    async def test_unknown_receipt_never_marks_save_failed_or_retries_write(self):
        database=self.database({'exp':0,'hash':'h','aid':42})
        with patch.object(blog_client,'draft_receipt',AsyncMock(side_effect=blog_client.ServiceError(503,'offline'))), \
                patch.object(blog_client,'save_draft',AsyncMock()) as save:
            await draft_commit.reconcile(database)
        database.execute.assert_not_awaited();save.assert_not_awaited()

    async def test_committed_receipt_reconciles_only_matching_intent(self):
        database=self.database({'exp':0,'hash':'h','aid':42})
        with patch.object(blog_client,'draft_receipt',AsyncMock(return_value={'articleId':'42','draftHash':'h'})):
            await draft_commit.reconcile(database)
        sql,params=database.execute.await_args.args
        self.assertIn('$.draft_commit.hash',sql);self.assertIn('$.draft_commit.aid',sql)
        self.assertEqual(params,{'rid':'r','uid':7,'aid':42,'hash':'h'})

    async def test_no_receipt_only_expires_after_permission_and_transaction_deadline(self):
        database=self.database({'exp':int(time.time())+120,'hash':'h','aid':42})
        with patch.object(blog_client,'draft_receipt',AsyncMock(return_value=None)):
            await draft_commit.reconcile(database)
            database.execute.assert_not_awaited()
            database.fetch_all.return_value[0]._mapping['result_json']=json.dumps({'draft_commit':{'exp':time.time()-31}})
            await draft_commit.reconcile(database)
        self.assertEqual(database.execute.await_count,2)
        self.assertIn('JSON_REMOVE',database.execute.await_args_list[0].args[0])

    async def test_cancelled_executor_cannot_reserve_or_call_blog(self):
        database=SimpleNamespace(transaction=lambda:Transaction(),execute=AsyncMock(),
            fetch_one=AsyncMock(return_value=SimpleNamespace(_mapping={
                'conversation_id':11,'draft_hash':'h','result_json':'{}'})))
        with patch('app.services.run_repository.RunRepository._lock_conversation',AsyncMock()), \
                patch('app.services.run_repository.RunRepository.assert_executor',AsyncMock(side_effect=HTTPException(409,'cancelled'))):
            with self.assertRaises(HTTPException):
                await draft_commit.reserve({'user_id':7,'conversation_id':11,'run_id':'r','execution_token':'t'},
                    {'articleId':'42','draftHash':'h','baseDraftHash':'h'},database)
        database.execute.assert_not_awaited()


class OwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_article_bodies_use_bounded_rpc_batches(self):
        async def read(method,request):
            self.assertEqual(method,'ReadPublic');self.assertLessEqual(len(request.ids),4)
            return [{'article_id':value} for value in request.ids]
        with patch.object(blog_client.settings,'AGENT_SERVICE_KEY','offline-service-key-32-bytes-long!!'), \
                patch.object(blog_client,'call',AsyncMock(side_effect=read)) as call:
            rows=await blog_client.public_read('published',ids=range(1,10))
            self.assertEqual([r['article_id'] for r in rows],list(range(1,10)))
            self.assertEqual(call.await_count,3)

    async def test_startup_guard_checks_only_agent_owned_schema(self):
        from app.migrate import check_service_boundaries
        database=SimpleNamespace(fetch_val=AsyncMock(return_value=5))
        await check_service_boundaries(database)
        sql=database.fetch_val.await_args.args[0]
        self.assertNotIn('article_',sql)
        database.fetch_val.return_value=4
        with self.assertRaises(RuntimeError):await check_service_boundaries(database)

    async def test_query_type_and_time_range_rejected_before_database_access(self):
        database=SimpleNamespace(fetch_all=AsyncMock())
        with self.assertRaises(HTTPException):
            await service_queries.query(SimpleNamespace(kind='raw_sql'),7,database)
        with self.assertRaises(HTTPException):
            await service_queries.query(SimpleNamespace(kind='metric_rows',source='all',start='2020-01-01',end='2026-01-01'),7,database)
        database.fetch_all.assert_not_awaited()

    def test_java_mappers_do_not_access_agent_owned_tables(self):
        import re
        root=Path(__file__).resolve().parents[2]/'src/main/resources/mapper'
        forbidden=re.compile(r'\b(?:FROM|JOIN|UPDATE|INTO)\s+(?:agent_run|agent_background_job|ai_message|ai_conversation|user_profile|user_memory)\b',re.I)
        self.assertEqual([p.name for p in root.glob('*.xml') if forbidden.search(p.read_text(encoding='utf-8'))],[])
