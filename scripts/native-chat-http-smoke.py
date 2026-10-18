"""Optional full native-image chat check through gateway -> Java -> RPC -> Agent.

Uses a disposable account, a seeded prior turn and a generated four-color image.
Makes one real model request. Cleans only its own fixtures after settlement.
"""
import asyncio
from io import BytesIO
import json
from pathlib import Path
import random
import secrets
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
import httpx
from PIL import Image, ImageDraw
from app.clients.mysql_client import db
from app.services.conversation import ConversationService
from app.services.run_repository import run_repository
from app.graph.builder import get_graph, close_graph


async def main():
    uid = (1 << 57) + secrets.randbits(48)
    suffix = secrets.token_hex(6)
    password = 'Qa-native-' + secrets.token_hex(12)
    email = f'native-qa-{suffix}@example.invalid'
    cid = None
    uploaded = None
    checks = {}
    await db.connect()
    conversations = ConversationService()
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8090/api', timeout=90, trust_env=False) as client:
        try:
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,status,sex,article_count,total_coin_count,current_coin_count,theme,role,follower_count,following_count,data_source)
                VALUES(:uid,:name,:email,:password,'Disposable native image QA',NOW(),1,2,0,0,0,1,1,0,0,'evaluation')''',
                {'uid':uid,'name':f'识图验收{suffix}','email':email,'password':password})
            login = (await client.post('/auth/login', json={'email':email,'password':password})).json()
            assert login['code'] == 200
            client.headers['Authorization'] = 'Bearer ' + login['data']['token']
            cid = await conversations.create_conversation(uid)
            await conversations.add_message(cid, 'user', '准备进行图片颜色识别。')
            await conversations.add_message(cid, 'assistant', '请上传待识别的图片。')
            history = await conversations._load_context(cid)
            assert len(history) == 2
            checks['real_mysql_prior_history_loaded'] = True
            colors = [('红色','#ff0000'),('蓝色','#0000ff'),('黄色','#ffff00'),('绿色','#00aa00')]
            random.SystemRandom().shuffle(colors)
            canvas = Image.new('RGB', (256,256))
            draw = ImageDraw.Draw(canvas)
            for index, (_, color) in enumerate(colors):
                x, y = index % 2 * 128, index // 2 * 128
                draw.rectangle((x,y,x+127,y+127), fill=color)
            image = BytesIO()
            canvas.save(image, format='PNG')
            upload = (await client.post('/file/upload-ai-chat', files={'file':('qa.png',image.getvalue(),'image/png')})).json()
            assert upload['code'] == 200
            uploaded = upload['data']
            checks['authenticated_image_upload'] = True
            frames = []
            async with client.stream('POST','/agent/chat/stream', json={'conversationId':str(cid),
                'requestId':str(uuid4()),'message':'请只根据图片回答：左上角和右下角分别是什么颜色？用中文各说一个颜色即可。',
                'imagePaths':[uploaded['path']],'mode':'agent'}) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line.startswith('data:'):
                        frames.append(line[5:].lstrip())
            run = await db.fetch_one('SELECT run_id,status,result_json FROM agent_run WHERE conversation_id=:cid ORDER BY created_at DESC LIMIT 1', {'cid':cid})
            assert run is not None, 'Chat did not create a run'
            assert run._mapping['status'] == 'succeeded', 'Chat did not settle successfully'
            result = json.loads(run._mapping['result_json'])
            reply = result['reply']
            assert colors[0][0] in reply and colors[3][0] in reply, 'Generated image colors missing from answer'
            assert any(frame.startswith('__ANSWER__:') for frame in frames), 'No streamed answer frames'
            checks.update(gateway_rpc_stream_completed=True, native_image_answer_correct=True,
                answer_chunks_received=True, run_settled_succeeded=True)
            current = await conversations._load_context(cid)
            assert any(item.get('image_paths') == [uploaded['path']] for item in current)
            checks['image_reference_survives_history_reload'] = True
        finally:
            if cid:
                runs = await db.fetch_all('SELECT run_id,status FROM agent_run WHERE conversation_id=:cid AND user_id=:uid', {'cid':cid,'uid':uid})
                active = any(row._mapping['status'] in ('running','awaiting_approval') for row in runs)
                if active:
                    await run_repository.cancel(cid, uid)
                    # Fence cancellation before cleaning the disposable conversation.
                    await asyncio.sleep(2)
                if runs:
                    graph = await get_graph()
                    for run in runs:
                        rid = run._mapping['run_id']
                        await graph.checkpointer.adelete_thread(f'run_{rid}')
                        for table in ('agent_stream_frame','agent_run_event','agent_answer_feedback'):
                            await db.execute(f'DELETE FROM {table} WHERE run_id=:rid', {'rid':rid})
                await conversations.invalidate_cache(cid)
                await db.execute('DELETE l FROM agent_execution_lease l WHERE l.user_id=:uid', {'uid':uid})
                await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid', {'cid':cid})
                await db.execute('DELETE FROM agent_run WHERE conversation_id=:cid AND user_id=:uid', {'cid':cid,'uid':uid})
                await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid', {'cid':cid,'uid':uid})
            if uploaded:
                (await client.delete('/file/delete', params={'fileUrl':uploaded['url']})).raise_for_status()
            await client.post('/auth/logout', headers={'X-Auth-Refresh':'1'})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid', {'uid':uid})
            await conversations._redis.client.aclose()
            await close_graph()
            await db.disconnect()
    checks['temporary_fixture_cleaned'] = True
    (ROOT/'logs/native-chat-http-smoke.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps(checks,indent=2))


if __name__ == '__main__':
    asyncio.run(main())
