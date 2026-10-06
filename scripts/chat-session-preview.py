"""Disposable loopback SSE fixture for browser QA. No model calls or existing user changes.

Run from python-agent: .venv/Scripts/python.exe ../scripts/chat-session-preview.py
Enter 'finish' to complete the background answer; Enter again to clean up.
"""
import asyncio, json, sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python-agent'))
from app.clients.mysql_client import db
from app.services.conversation import ConversationService
from app.services.run_repository import run_repository
from app.services.stream_delivery import stream_delivery
from app.graph.builder import get_graph, close_graph
from app.utils.snowflake import SnowflakeGenerator
conversation_service=ConversationService()

async def main():
    assert db.url.hostname in {'127.0.0.1','localhost','::1'}
    marker='chat-switch-'+uuid4().hex[:10]
    uid=SnowflakeGenerator(worker_id=27).next_id()
    cids=[];run=None
    await db.connect()
    try:
        await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
            VALUES(:uid,'会话切换测试',:email,'LocalChatQa2026!',:marker,NOW(),2,1,0,0,1,1,0,0,0)''',{'uid':uid,'email':marker+'@sample.invalid','marker':marker})
        for title in ['缓存一致性方案 · 生成中','RAG 入门 · 另一个对话']:
            cid=await conversation_service.create_conversation(uid);cids.append(cid)
            await conversation_service.add_message(cid,'user',title,postprocess=False)
            await db.execute('UPDATE ai_conversation SET title=:title WHERE conversation_id=:cid',{'cid':cid,'title':title})
        await conversation_service.add_message(cids[1],'assistant','这是独立的另一个会话。你可以在这里继续提问，原会话仍在生成。',postprocess=False)
        run,_=await run_repository.create(cids[0],uid,str(uuid4()),'qa-background-answer')
        await db.execute('UPDATE agent_run SET deadline=TIMESTAMPADD(MINUTE,15,UTC_TIMESTAMP(6)),executor_lease_until=TIMESTAMPADD(MINUTE,15,UTC_TIMESTAMP(6)) WHERE run_id=:rid',{'rid':run['run_id']})
        async def frame(value): await stream_delivery.append(run['run_id'],run['execution_token'],'data:'+value+'\n\n')
        await frame('__RUN_ID__:'+run['run_id'])
        await frame('__CONV_ID__:'+str(cids[0]))
        await frame('__PROGRESS__:planner')
        await frame('__REPLY__:'+json.dumps({'content':'正在整理缓存一致性的方案。切换会话后，我会继续处理这份回答。'},ensure_ascii=False))
        print(f'Account: {marker}@sample.invalid / LocalChatQa2026!',flush=True)
        print(f'Conversation A: {cids[0]}',flush=True)
        print(f'Conversation B: {cids[1]}',flush=True)
        command=await asyncio.to_thread(input,'Enter finish after switching to B: ')
        if command.strip()=='finish':
            reply='缓存一致性方案已整理完成。\n\n1. 先更新数据库，再删除缓存。\n2. 删除失败时，通过可靠队列重试。\n3. 用 TTL 限制旧值的持续时间。\n\n这份回答在你查看另一个会话时完成，结果仍然属于原会话。'
            await run_repository.settle(cids[0],uid,run['run_id'],run['execution_token'],'succeeded',{'reply':reply},append_message=lambda:conversation_service._append_message(cids[0],'assistant',reply))
            await conversation_service.invalidate_cache(cids[0])
            await frame('__REPLY__:'+json.dumps({'content':reply},ensure_ascii=False))
            await frame('__PROGRESS__:done');await frame('[DONE]')
            print('Background answer completed.',flush=True)
            await asyncio.to_thread(input,'Press Enter after QA to clean fixtures: ')
    finally:
        owned_runs = await db.fetch_all('SELECT run_id FROM agent_run WHERE user_id=:uid', {'uid': uid})
        graph = await get_graph() if owned_runs else None
        for owned in owned_runs:
            rid = owned._mapping['run_id']
            await graph.checkpointer.adelete_thread('run_' + rid)
            for table in ['agent_stream_frame','agent_run_event']:
                await db.execute(f'DELETE FROM {table} WHERE run_id=:rid',{'rid':rid})
            await db.execute('DELETE FROM agent_run WHERE run_id=:rid AND user_id=:uid',{'rid':rid,'uid':uid})
        for table in ['agent_background_job','agent_execution_lease']:
            await db.execute(f'DELETE FROM {table} WHERE user_id=:uid', {'uid': uid})
        for cid in cids:
            if await db.fetch_val('SELECT COUNT(*) FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid',{'cid':cid,'uid':uid})!=1:continue
            await conversation_service.delete_conversation(cid)
            await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid',{'cid':cid})
            await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid',{'cid':cid,'uid':uid})
        await db.execute('DELETE FROM user_info WHERE user_id=:uid AND person_introduction=:marker',{'uid':uid,'marker':marker})
        await close_graph()
        await db.disconnect()
        print('Fixtures cleaned.',flush=True)

if __name__=='__main__':asyncio.run(main())
