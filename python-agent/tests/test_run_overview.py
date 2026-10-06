import os
os.environ['DEEPSEEK_API_KEY']='offline-test'
os.environ['AGENT_SERVICE_KEY']='offline-service-key-32-bytes-long!!'
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app import main
from app.services.run_repository import RunRepository

class OverviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_is_owner_scoped_latest_only_and_excludes_draft_payload(self):
        db=SimpleNamespace(fetch_all=AsyncMock(return_value=[]))
        await RunRepository(db).overview(7)
        query,params=db.fetch_all.call_args.args
        self.assertEqual(params,{'uid':7})
        for part in ['r.user_id=:uid','c.user_id=:uid','c.status=1','NOT EXISTS','LIMIT 100']:self.assertIn(part,query)
        self.assertNotIn('result_json',query)

    async def test_overview_reconciles_leases_but_only_returns_navigation_metadata(self):
        row={'run_id':'one','conversation_id':12,'user_id':7,'title':'缓存一致性','status':'running',
             'updated_at':datetime(2026,10,5),'execution_token':'secret','result_json':'private body'}
        repo=SimpleNamespace(overview=AsyncMock(return_value=[row]),expire_existing=AsyncMock(),get=AsyncMock(return_value={**row,'status':'expired'}))
        service=SimpleNamespace(reconcile_saved=AsyncMock(return_value=row))
        with patch.object(main,'run_repository',repo),patch.object(main,'run_service',service):
            result=await main.run_overview(SimpleNamespace(user_id=7))
        self.assertEqual(result['items'][0]['status'],'expired')
        self.assertEqual(set(result['items'][0]),{'runId','conversationId','title','status','updatedAt'})
        repo.expire_existing.assert_awaited_once_with(12,7,'one')
