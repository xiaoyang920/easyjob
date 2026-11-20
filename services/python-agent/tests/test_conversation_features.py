import os
os.environ.setdefault('DEEPSEEK_API_KEY','offline-test')
os.environ.setdefault('AGENT_SERVICE_KEY','offline-service-key-32-bytes-long!!')
import unittest
from types import SimpleNamespace
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
from app.rpc.codec import encode
from app.rpc.generated import easyjob_rpc_pb2 as pb
from app.services.conversation_features import query

def row(**kw):return SimpleNamespace(_mapping=kw)
@asynccontextmanager
async def transaction():yield

class FeaturesTests(unittest.IsolatedAsyncioTestCase):
    def db(self):return SimpleNamespace(transaction=transaction,fetch_one=AsyncMock(return_value=None),fetch_all=AsyncMock(return_value=[]),fetch_val=AsyncMock(return_value=0),execute=AsyncMock())
    def q(self,kind,edit=None,**kw):return pb.AgentQuery(kind=kind,edit=encode(edit or {}).object,**kw)
    async def test_library_is_owner_scoped_and_escapes_sql_wildcards(self):
        db=self.db();q=self.q('conversation_library',state='general',name='x%_!',page=2,limit=20)
        with patch('app.services.conversation.ConversationService._enrich_origins',new=AsyncMock()):await query(q,7,db)
        sql,values=db.fetch_all.await_args.args
        self.assertIn('c.user_id=:uid',sql);self.assertIn('origin_article_id IS NULL',sql);self.assertIn('is_pinned DESC',sql)
        self.assertEqual(values,{'uid':7,'offset':20,'limit':20,'keyword':'%x!%!_!!%'})
    async def test_library_rejects_unbounded_pages_and_invalid_scopes(self):
        for q in [self.q('conversation_library',state='all',limit=101,page=1),self.q('conversation_library',state='other',limit=20,page=1)]:
            with self.assertRaises(HTTPException) as error:await query(q,7,self.db())
            self.assertEqual(error.exception.status_code,422)
    async def test_library_preserves_large_identifiers_at_the_browser_boundary(self):
        db=self.db();db.fetch_all.return_value=[row(conversation_id=9007199254740993,user_id=7,origin_article_id=None)]
        with patch('app.services.conversation.ConversationService._enrich_origins',new=AsyncMock()):
            result=await query(self.q('conversation_library',state='all',limit=20,page=1),7,db)
        self.assertEqual(result['rows'][0]['conversationId'],'9007199254740993')
        self.assertIsNone(result['rows'][0]['originArticleId'])
    async def test_edit_requires_owner_and_expected_metadata_version(self):
        db=self.db();q=self.q('conversation_edit',{'title':'新名称','version':1},name='42')
        with self.assertRaises(HTTPException) as error:await query(q,7,db)
        self.assertEqual(error.exception.status_code,404)
        db.fetch_one.return_value=row(title='旧',is_pinned=0,metadata_version=2)
        with self.assertRaises(HTTPException) as error:await query(q,7,db)
        self.assertEqual(error.exception.status_code,409);db.execute.assert_not_awaited()
        q.edit.CopyFrom(encode({'title':' 新名称 ','pinned':True,'version':2}).object)
        self.assertEqual(await query(q,7,db),{'version':3})
        sql,values=db.execute.await_args.args;self.assertEqual(values['uid'],7);self.assertEqual(values['pin'],1);self.assertEqual(values['title'],'新名称')
    async def test_feedback_never_accepts_an_unowned_or_unfinished_run(self):
        db=self.db();q=self.q('answer_feedback',{'rating':'helpful'},name='0d326ff2-b461-4eea-9d9d-024f0a45da37')
        with self.assertRaises(HTTPException) as error:await query(q,7,db)
        self.assertEqual(error.exception.status_code,404)
        db.fetch_one.return_value=row(status='running')
        with self.assertRaises(HTTPException) as error:await query(q,7,db)
        self.assertEqual(error.exception.status_code,409);db.execute.assert_not_awaited()
    async def test_completed_feedback_upserts_once_per_owner_and_can_be_removed(self):
        db=self.db();db.fetch_one.side_effect=[row(status='succeeded'),None]
        q=self.q('answer_feedback',{'rating':'problem','reason':'citation','comment':' 错误引用 '},name='0d326ff2-b461-4eea-9d9d-024f0a45da37')
        await query(q,7,db);sql,values=db.execute.await_args.args
        self.assertIn('ON DUPLICATE KEY UPDATE',sql);self.assertEqual(values['uid'],7);self.assertEqual(values['comment'],'错误引用')
        db.fetch_one.side_effect=[row(status='succeeded'),None];q.edit.CopyFrom(encode({'rating':''}).object);await query(q,7,db)
        self.assertIn('DELETE FROM agent_answer_feedback',db.execute.await_args.args[0])
    async def test_feedback_report_excludes_private_message_and_comment_content(self):
        db=self.db();await query(self.q('feedback_report',page=1,limit=20,source='business'),7,db)
        for call in db.fetch_all.await_args_list:
            self.assertNotIn('comment',call.args[0]);self.assertNotIn('ai_message',call.args[0])
