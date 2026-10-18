"""Real-MySQL feedback lifecycle check. Uses disposable IDs and no model calls."""
import asyncio
import json
import secrets
import sys
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.services.conversation import ConversationService
from app.services.conversation_features import query
from app.rpc.codec import encode
from app.rpc.generated import easyjob_rpc_pb2 as pb
from fastapi import HTTPException

def request(kind,rid,edit=None,**values): return pb.AgentQuery(kind=kind,name=rid,edit=encode(edit or {}).object,**values)

async def main():
    rid=str(uuid4());uid=(1<<57)+secrets.randbits(48);cid=None;checks={}
    await db.connect()
    try:
        service=ConversationService();cid=await service.create_conversation(uid)
        mid=await service.add_message(cid,'user','临时反馈验收问题',postprocess=False)
        await db.execute('''INSERT INTO agent_run(run_id,conversation_id,user_id,request_id,input_hash,execution_token,status,deadline,result_json,data_source)
            VALUES(:rid,:cid,:uid,:rid,:hash,:token,'succeeded',UTC_TIMESTAMP(6),CAST(:result AS JSON),'evaluation')''',
            {'rid':rid,'cid':cid,'uid':uid,'hash':'a'*64,'token':str(uuid4()),'result':json.dumps({'user_message_id':str(mid)})})
        await service.add_message(cid,'assistant','临时反馈验收回答',postprocess=False,run_id=rid)
        await query(request('answer_feedback',rid,{'rating':'problem','reason':'citation','comment':'需要修正引用'}),uid)
        detail=await query(request('feedback_detail',rid),uid)
        assert detail['question']['content']=='临时反馈验收问题' and detail['answer']['content']=='临时反馈验收回答'
        assert detail['feedback']['review_state']=='pending';checks['reported_turn_and_comment']=True
        edit={'state':'resolved','note':'验收处理完成','version':detail['feedback']['review_version'],'generation':detail['feedback']['feedback_generation'],'commandId':str(uuid4())}
        await query(request('feedback_review',rid,edit),uid);await query(request('feedback_review',rid,edit),uid)
        assert await db.fetch_val('SELECT COUNT(*) FROM agent_feedback_review_log WHERE run_id=:rid',{'rid':rid})==1
        checks['review_retry_is_idempotent']=True
        detail=await query(request('feedback_detail',rid),uid)
        assert detail['feedback']['review_state']=='resolved' and len(detail['history'])==1
        await query(request('answer_feedback',rid,{'rating':''}),uid)
        await query(request('answer_feedback',rid,{'rating':'problem','reason':'incorrect','comment':'再次反馈'}),uid)
        # Even when the numeric version starts over, the old feedback generation cannot be reviewed.
        stale={**edit,'commandId':str(uuid4())}
        try: await query(request('feedback_review',rid,stale),uid)
        except HTTPException as e: assert e.status_code==409
        else: raise AssertionError('Old feedback generation overwrote a new submission')
        checks['withdraw_resubmit_invalidates_stale_review']=True
        detail=await query(request('feedback_detail',rid),uid)
        assert detail['feedback']['review_state']=='pending' and detail['feedback']['comment']=='再次反馈'
        await db.execute('UPDATE ai_conversation SET status=0 WHERE conversation_id=:cid',{'cid':cid})
        hidden=await query(request('feedback_detail',rid),uid)
        assert hidden['question'] is None and hidden['answer'] is None;checks['deleted_conversation_content_hidden']=True
        assert await db.fetch_val("SELECT COUNT(*) FROM agent_admin_audit WHERE kind='feedback_view' AND target=:rid",{'rid':rid})==4
        checks['detail_access_audited']=True
    finally:
        async with db.transaction():
            await db.execute('DELETE FROM agent_feedback_review_log WHERE run_id=:rid AND user_id=:uid',{'rid':rid,'uid':uid})
            await db.execute('DELETE FROM agent_admin_audit WHERE target=:rid AND actor_id=:uid',{'rid':rid,'uid':uid})
            await db.execute('DELETE FROM agent_answer_feedback WHERE run_id=:rid AND user_id=:uid',{'rid':rid,'uid':uid})
            await db.execute('DELETE FROM agent_run WHERE run_id=:rid AND user_id=:uid',{'rid':rid,'uid':uid})
            if cid:
                await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid',{'cid':cid})
                await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid',{'cid':cid,'uid':uid})
        await db.disconnect();checks['temporary_fixture_cleaned']=True
    print(json.dumps(checks,ensure_ascii=False,indent=2))
    (ROOT/'logs/feedback-review-smoke.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__': asyncio.run(main())
