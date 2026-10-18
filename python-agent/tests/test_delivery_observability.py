import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from fastapi import HTTPException
from app.rpc.codec import encode
from app.services.service_queries import query

class DeliveryObservabilityTests(unittest.IsolatedAsyncioTestCase):
    def request(self, **values):
        return SimpleNamespace(kind='delivery_metrics',name=str(uuid4()),edit=encode({'first_answer_ms':1250}).object,**values)
    async def test_only_owner_can_report_and_sample_is_first_write_wins(self):
        database=SimpleNamespace(fetch_one=AsyncMock(return_value=SimpleNamespace(_mapping={'run_id':'x'})),execute=AsyncMock())
        request=self.request()
        self.assertTrue(await query(request,7,database))
        sql,values=database.execute.call_args.args
        self.assertIn('user_id=:uid',sql);self.assertIn('IS NULL',sql)
        self.assertEqual(json.loads(values['metrics'])['first_answer_ms'],1250)
        database.fetch_one.return_value=None
        with self.assertRaises(HTTPException) as error:await query(request,8,database)
        self.assertEqual(error.exception.status_code,404)
        self.assertEqual(database.execute.await_count,1)
    async def test_invalid_or_non_integer_measurements_do_not_write(self):
        database=SimpleNamespace(fetch_one=AsyncMock(),execute=AsyncMock())
        for value in [-1,3600001,True,'100',1.5,None]:
            request=self.request();request.edit=encode({'first_answer_ms':value}).object
            with self.assertRaises(HTTPException):await query(request,7,database)
        database.execute.assert_not_awaited()
    async def test_stage_aggregation_is_bounded_filtered_and_keeps_failures(self):
        database=SimpleNamespace(fetch_all=AsyncMock(return_value=[SimpleNamespace(_mapping=row) for row in [
            {'node':'retrieval/rerank','status':'succeeded','duration_ms':100},
            {'node':'retrieval/rerank','status':'degraded','duration_ms':500},
            {'node':'final_gate','status':'failed','duration_ms':900}]]))
        request=SimpleNamespace(kind='metric_stages',source='business',start='2026-10-01T00:00:00',end='2026-10-08T00:00:00')
        rows=await query(request,7,database)
        rerank=next(row for row in rows if row['name']=='retrieval/rerank')
        self.assertEqual((rerank['count'],rerank['p95_ms'],rerank['degraded']),(2,500,1))
        self.assertEqual(next(row for row in rows if row['name']=='final_gate')['failed'],1)
        sql,values=database.fetch_all.call_args.args
        self.assertIn('LIMIT 50000',sql);self.assertIn('LIMIT 10000',sql);self.assertEqual(values['source'],'business')
