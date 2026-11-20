import os
os.environ.setdefault('DEEPSEEK_API_KEY','offline-test')
os.environ.setdefault('AGENT_SERVICE_KEY','offline-service-key-32-bytes-long!!')
import unittest
from types import SimpleNamespace
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from fastapi import HTTPException
from app.rpc.codec import encode
from app.rpc.generated import easyjob_rpc_pb2 as pb
from app.services.feedback_review import query

RID='117f57d9-93d7-42de-8de4-491eb297b823'
GEN='7364b086-ea4e-442a-aa59-83ec2d2dba48'
COMMAND='5b8aa8f5-1e35-4ebd-9656-c99c139949b1'
def row(**values): return SimpleNamespace(_mapping=values)
@asynccontextmanager
async def transaction(): yield
def database(): return SimpleNamespace(transaction=transaction,fetch_one=AsyncMock(return_value=None),fetch_all=AsyncMock(return_value=[]),execute=AsyncMock())
def request(kind='feedback_review',**changes):
    edit={'state':'resolved','note':'修正引用并复测','version':2,'commandId':COMMAND,'generation':GEN,**changes}
    return pb.AgentQuery(kind=kind,name=RID,edit=encode(edit).object)
def locked(**changes): return row(user_id=7,review_state='pending',review_version=2,feedback_generation=GEN,**changes)

class FeedbackReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_review_is_rejected_before_database_access(self):
        for change in [{'state':'bad'},{'note':''},{'note':'a'*1001},{'version':True},{'version':-1},{'generation':'bad'},{'commandId':None}]:
            db=database()
            with self.assertRaises(HTTPException) as error: await query(request(**change),9,db)
            self.assertEqual(error.exception.status_code,422);db.fetch_one.assert_not_awaited()

    async def test_missing_feedback_cannot_be_processed(self):
        db=database()
        with self.assertRaises(HTTPException) as error: await query(request(),9,db)
        self.assertEqual(error.exception.status_code,404);db.execute.assert_not_awaited()

    async def test_changed_version_or_withdrawn_and_resubmitted_feedback_cannot_be_overwritten(self):
        for change in [{'version':1},{'generation':'6f0dbbad-66fa-4638-ade2-22c54362d497'}]:
            db=database();db.fetch_one.side_effect=[locked(),None]
            with self.assertRaises(HTTPException) as error: await query(request(**change),9,db)
            self.assertEqual(error.exception.status_code,409);db.execute.assert_not_awaited()

    async def test_success_changes_state_and_keeps_a_review_record(self):
        db=database();db.fetch_one.side_effect=[locked(),None]
        result=await query(request(),9,db)
        self.assertEqual(result,{'version':3,'state':'resolved'})
        self.assertEqual(db.execute.await_count,2)
        sql,values=db.execute.await_args.args
        self.assertIn('agent_feedback_review_log',sql);self.assertEqual(values['uid'],7);self.assertEqual(values['actor'],9);self.assertEqual(values['generation'],GEN)

    async def test_exact_retry_is_idempotent_but_command_reuse_by_another_actor_fails(self):
        receipt=row(run_id=RID,actor_id=9,to_state='resolved',note='修正引用并复测',expected_version=2,feedback_generation=GEN)
        db=database();db.fetch_one.side_effect=[row(user_id=7,review_state='resolved',review_version=3,feedback_generation=GEN),receipt]
        self.assertEqual(await query(request(),9,db),{'version':3,'state':'resolved'});db.execute.assert_not_awaited()
        db.fetch_one.side_effect=[locked(),receipt]
        with self.assertRaises(HTTPException) as error: await query(request(),10,db)
        self.assertEqual(error.exception.status_code,409);db.execute.assert_not_awaited()

    async def test_detail_reads_only_exact_reported_turn_and_audits_access(self):
        db=database();db.fetch_one.side_effect=[row(run_id=RID,user_id=9007199254740993,conversation_id='42',conversation_status=1,input_message_id='9007199254740999',handled_by=9),row(content='问题'),row(content='回答')]
        result=await query(request('feedback_detail'),9,db)
        self.assertEqual(result['feedback']['user_id'],'9007199254740993');self.assertNotIn('input_message_id',result['feedback'])
        self.assertEqual(result['question']['content'],'问题');self.assertEqual(result['answer']['content'],'回答')
        question_sql,values=db.fetch_one.await_args_list[1].args
        self.assertIn('message_id=:mid',question_sql);self.assertEqual(values,{'cid':42,'mid':9007199254740999})
        self.assertIn('run_id=:rid',db.fetch_one.await_args_list[2].args[0])
        self.assertEqual(db.execute.await_args.args[1]['kind'],'feedback_view')

    async def test_deleted_conversation_does_not_expose_message_content(self):
        db=database();db.fetch_one.return_value=row(run_id=RID,user_id=7,conversation_id='42',conversation_status=0,input_message_id='123')
        result=await query(request('feedback_detail'),9,db)
        self.assertIsNone(result['question']);self.assertIsNone(result['answer']);self.assertEqual(db.fetch_one.await_count,1)

    async def test_missing_input_link_never_guesses_an_unrelated_question(self):
        db=database();db.fetch_one.side_effect=[row(run_id=RID,user_id=7,conversation_id='42',conversation_status=1,input_message_id=None),row(content='回答')]
        result=await query(request('feedback_detail'),9,db)
        self.assertIsNone(result['question']);self.assertEqual(db.fetch_one.await_count,2)
