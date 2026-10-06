import hashlib
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from app.services.index_reconciliation import IndexReconciliation,article_difference,memory_difference

def article(**values):
    return {'article_id':7,'user_id':1,'title':'Title','content':'<p>body</p>','summary':'summary','tags':None,'category_id':2,'status':1,'deleted':0,'required_level':0,'view_count':4,**values}
def source(row):
    return {'title':row['title'],'content':row['content'],'summary':row['summary'],'tags':row['tags'],'categoryId':row['category_id'],'status':row['status'],'viewCount':row['view_count']}
def chunk(row,index=0):
    return {'source_hash':hashlib.sha256(row['content'].encode()).hexdigest(),'title':row['title'],'chunker_version':'html-dom-v1','chunk_index':index}
def record(value):return SimpleNamespace(_mapping=value)
@asynccontextmanager
async def transaction():yield

class DifferenceTests(unittest.TestCase):
    def test_current_articles_do_not_trigger_paid_reindex(self):
        row=article();self.assertIsNone(article_difference(row,source(row),[chunk(row)]))
    def test_missing_document_and_chunks_are_repaired(self):
        row=article();self.assertEqual(article_difference(row,None,[]),'missing_document')
        self.assertEqual(article_difference(row,source(row),[]),'missing_chunks')
    def test_private_and_level_gated_content_is_removed_from_vectors(self):
        for row in [article(status=0),article(deleted=1),article(status=2)]:self.assertEqual(article_difference(row,source(row),[]),'private_index')
        row=article(required_level=1);self.assertEqual(article_difference(row,source(row),[chunk(row)]),'restricted_chunks')
        self.assertIsNone(article_difference(row,source(row),[]))
    def test_stale_hash_and_holes_and_duplicate_indices_are_detected(self):
        row=article();bad=chunk(row);bad['source_hash']='stale'
        self.assertEqual(article_difference(row,source(row),[bad]),'chunk_version')
        for indices in [(0,2),(0,0)]:self.assertEqual(article_difference(row,source(row),[chunk(row,i) for i in indices]),'incomplete_chunks')
    def test_view_repair_is_monotonic(self):
        row=article();s=source(row);s['viewCount']=3;self.assertEqual(article_difference(row,s,[chunk(row)]),'view_count')
        s['viewCount']=20;self.assertIsNone(article_difference(row,s,[chunk(row)]))
    def test_manifest_detects_missing_final_chunk(self):
        row=article();first={**chunk(row),'chunk_count':2}
        self.assertEqual(article_difference(row,source(row),[first]),'incomplete_chunks')
    def test_image_only_article_is_not_reindexed_forever(self):
        row=article(content='<img src="/image.jpg">');self.assertIsNone(article_difference(row,source(row),[]))
    def test_only_active_decisions_are_indexed(self):
        row={'content':'decision','user_id':2,'memory_type':'decision','status':'active','scope':'global','scope_conversation_id':None}
        self.assertTrue(memory_difference(row,None));self.assertFalse(memory_difference(row,row))
        for v in [{'status':'inactive'},{'memory_type':'constraint'},{'memory_type':'event'}]:self.assertTrue(memory_difference({**row,**v},row))
        self.assertTrue(memory_difference(row,{**row,'user_id':3}))

class RepairTests(unittest.IsolatedAsyncioTestCase):
    def database(self, row=None,existing=0):
        return SimpleNamespace(transaction=transaction,fetch_one=AsyncMock(return_value=record(row) if row else None),fetch_val=AsyncMock(return_value=existing),execute=AsyncMock(),fetch_all=AsyncMock(return_value=[]))
    async def test_repair_rechecks_version_and_never_overwrites_content(self):
        old=article();database=self.database(article(content='changed'))
        self.assertFalse(await IndexReconciliation(database).article_repair(old,'document_version'))
        database.execute.assert_not_awaited()
    async def test_pending_and_dead_tasks_suppress_new_retries(self):
        row=article();database=self.database(row,1)
        self.assertFalse(await IndexReconciliation(database).article_repair(row,'missing_chunks'));database.execute.assert_not_awaited()
    async def test_view_count_uses_coalesced_sync_instead_of_embeddings(self):
        row=article();database=self.database(row)
        self.assertTrue(await IndexReconciliation(database).article_repair(row,'view_count'))
        self.assertIn('GREATEST',database.execute.await_args.args[0]);self.assertNotIn('outbox',database.execute.await_args.args[0])
    async def test_orphan_repair_cannot_delete_newly_published_article(self):
        database=self.database(article());self.assertFalse(await IndexReconciliation(database).article_repair(None,'orphan',7));database.execute.assert_not_awaited()
    async def test_orphan_repair_uses_existing_queue(self):
        database=self.database();self.assertTrue(await IndexReconciliation(database).article_repair(None,'orphan',7))
        self.assertIn('article_index_outbox',database.execute.await_args.args[0])
    async def test_stale_memory_snapshot_is_not_enqueued(self):
        row={'memory_id':8,'content':'old','user_id':1,'memory_type':'decision','status':'active'}
        database=self.database({**row,'status':'inactive'})
        self.assertFalse(await IndexReconciliation(database).memory_repair(row));database.execute.assert_not_awaited()
    async def test_failure_keeps_cursor_and_fences_lease(self):
        database=self.database();es=SimpleNamespace(options=lambda **k:None)
        service=IndexReconciliation(database,es);service.claim=AsyncMock(return_value={'kind':'article','last_id':100,'token':'mine'});service.batch=AsyncMock(side_effect=TimeoutError())
        self.assertTrue(await service.tick());sql,params=database.execute.await_args.args
        self.assertIn('lease_token=:t',sql);self.assertIn('lease_until>UTC_TIMESTAMP',sql);self.assertNotIn('last_id=',sql)
        self.assertEqual(params['e'],'TimeoutError');self.assertEqual(params['t'],'mine')
    async def test_chunk_orphans_include_articles_missing_from_fulltext_index(self):
        database=self.database();es=SimpleNamespace(options=lambda **k:es,search=AsyncMock(return_value={'aggregations':{'articles':{'buckets':[{'key':{'article':'7'}}]}}}))
        service=IndexReconciliation(database,es);service.article_repair=AsyncMock(return_value=True)
        self.assertEqual(await service.batch({'kind':'chunk_orphan','last_id':0},es),(0,1,1,False))
        service.article_repair.assert_awaited_once_with(None,'orphan',7)

    async def test_cleanup_bulk_delete_rechecks_status_and_current_reading_pointer(self):
        from app.services.operations import Operations
        def rows(sql,*args):
            if 'SELECT f.event_id' in sql:return [record({'event_id':9})]
            if 'SELECT job_id' in sql:return [record({'job_id':'job'})]
            if 'SELECT s.session_id' in sql:return [record({'session_id':'old'})]
            return []
        database=self.database();database.fetch_all.side_effect=rows
        await Operations(database).cleanup()
        queries=[call.args[0] for call in database.execute.await_args_list]
        self.assertTrue(any("NOT IN ('running','awaiting_approval')" in q for q in queries))
        self.assertTrue(all('updated_at<' in q for q in queries if 'DELETE FROM agent_background_job' in q or 'DELETE FROM article_index_outbox' in q))
        self.assertTrue(any('p.active_session<>s.session_id' in q for q in queries))

    async def test_cleanup_batches_have_time_and_volume_boundaries(self):
        from app.services.operations import Operations
        database=self.database()
        await Operations(database).cleanup()
        queries=[call.args[0] for call in database.fetch_all.await_args_list]
        self.assertTrue(all('LIMIT' in q for q in queries))

    async def test_reconciliation_success_uses_exact_lease_token(self):
        database=self.database();es=SimpleNamespace(options=lambda **k:None)
        service=IndexReconciliation(database,es);service.claim=AsyncMock(return_value={'kind':'memory','last_id':2,'token':'lease'});service.batch=AsyncMock(return_value=(4,2,1,True))
        await service.tick();sql,params=database.execute.await_args.args
        self.assertIn('lease_token=:t',sql);self.assertEqual(params['id'],4);self.assertEqual(params['delay'],60)
