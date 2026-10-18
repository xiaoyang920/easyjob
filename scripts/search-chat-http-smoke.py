"""Opt-in public search conversation through gateway -> Java -> Agent -> DeepSeek.

Creates and removes its own account, conversation, run and checkpoint. --live is
required because this makes real model and Search/Fetch requests.
"""
import argparse
import asyncio
import json
from pathlib import Path
import secrets
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
import httpx
from app.clients.mysql_client import db
from app.graph.builder import get_graph, close_graph
from app.rpc.blog_client import close_client
from app.services.conversation import ConversationService
from app.services.grounding import source_contents
from app.services.run_repository import run_repository


async def main(image_lookup=False):
    uid = (1 << 57) + secrets.randbits(48)
    suffix = secrets.token_hex(6)
    password = 'Qa-search-' + secrets.token_hex(12)
    email = f'search-qa-{suffix}@example.invalid'
    cid = None
    uploaded = None
    report = {'checks': {}}
    await db.connect()
    conversations = ConversationService()
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8090/api', timeout=180, trust_env=False) as client:
        try:
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,status,sex,article_count,total_coin_count,current_coin_count,theme,role,follower_count,following_count,data_source)
                VALUES(:uid,:name,:email,:password,'Disposable public search QA',NOW(),1,2,0,0,0,1,1,0,0,'evaluation')''',
                {'uid': uid, 'name': f'检索验收{suffix}', 'email': email, 'password': password})
            login = (await client.post('/auth/login', json={'email': email, 'password': password})).json()
            assert login['code'] == 200, 'Fixture login failed'
            client.headers['Authorization'] = 'Bearer ' + login['data']['token']
            overview = await client.get('/agent/run-overview')
            assert overview.status_code == 200 and overview.json()['code'] == 200, 'Gateway RPC probe failed'
            report['checks']['gateway_rpc_read_ok'] = True
            cid = await conversations.create_conversation(uid)
            message = '请联网搜索 Spring 官方的 REST 入门指南。只需给出一个 spring.io 官方指南链接，并用一句话说明它用于学习什么，不需要代码，也不用搜索站内文章。'
            image_paths = []
            if image_lookup:
                from io import BytesIO
                from PIL import Image, ImageDraw, ImageFont
                # Synthetic text poster, not a user's private image. No request
                # explicitly says "search" or "go online": Main must infer lookup intent.
                poster = Image.new('RGB', (1000, 420), '#f4f0e5')
                draw = ImageDraw.Draw(poster)
                font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 32)
                draw.text((45, 70), 'Building a RESTful Web Service', fill='#161616', font=font)
                draw.text((45, 150), '@RestController', fill='#476b29', font=font)
                draw.text((45, 215), '@GetMapping("/greeting")', fill='#476b29', font=font)
                draw.text((45, 320), 'Learning notes - source unknown', fill='#888888', font=font)
                data = BytesIO()
                poster.save(data, format='PNG')
                upload = (await client.post('/file/upload-ai-chat', files={'file': ('qa-source.png', data.getvalue(), 'image/png')})).json()
                assert upload['code'] == 200, 'Image fixture upload failed'
                uploaded = upload['data']
                image_paths = [uploaded['path']]
                message = '这张学习笔记对应哪篇原始教程？给出原文出处和一句用途说明。'
                report['checks']['synthetic_image_uploaded'] = True
            frames = []
            async with client.stream('POST', '/agent/chat/stream', json={'conversationId': str(cid),
                    'requestId': str(uuid4()), 'message': message,
                    'imagePaths': image_paths, 'mode': 'agent'}) as response:
                assert response.status_code == 200, 'Stream HTTP failed'
                async for line in response.aiter_lines():
                    if line.startswith('data:'):
                        frames.append(line[5:].lstrip())
            run = await db.fetch_one('SELECT run_id,status,result_json FROM agent_run WHERE conversation_id=:cid ORDER BY created_at DESC LIMIT 1', {'cid': cid})
            assert run is not None, 'No run created'
            report['run_status'] = run._mapping['status']
            assert run._mapping['status'] == 'succeeded', 'Run did not complete'
            result = json.loads(run._mapping['result_json'])
            assert result.get('reply'), 'Empty final answer'
            assert any(frame.startswith('__ANSWER__:') for frame in frames), 'No answer chunks received'
            report['checks']['answer_stream_and_settlement_ok'] = True
            graph = await get_graph()
            snapshot = await graph.aget_state({'configurable': {'thread_id': f"run_{run._mapping['run_id']}"}})
            state = snapshot.values
            retrievals = [r for r in state.get('task_results', {}).values() if r.get('retrieval_report', {}).get('web', {}).get('provider') == 'deepseek']
            assert retrievals, 'No DeepSeek retrieval record'
            assert any(r['retrieval_report']['web']['status'] == 'found' for r in retrievals), 'No public results delivered'
            report['checks']['running_agent_uses_deepseek_search'] = True
            if image_lookup:
                report['checks']['image_source_lookup_without_explicit_search_request'] = True
            citations = [c for r in retrievals for c in r.get('citations', []) if c.get('source') == 'web']
            assert any(c.get('contentScope') in ('page_content', 'page_excerpt') for c in citations), 'Only summaries retrieved'
            report['checks']['retrieved_page_body_with_scope'] = True
            raw = source_contents(state, citations)
            assert any(len(s['content']) > len(s.get('excerpt', '')) for s in raw), 'Verifier still limited to preview'
            report['checks']['verifier_gets_more_than_ui_preview'] = True
            report['grounding_status'] = (state.get('grounding_audit') or {}).get('status')
            assert report['grounding_status'] in ('verified', 'repaired'), 'Final audit not confirmed'
            report['checks']['final_grounding_gate_completed'] = True
            report['status'] = 'passed'
        except Exception as exc:
            report.update(status='failed', error_type=type(exc).__name__)
            if isinstance(exc, AssertionError):
                report['error'] = str(exc)
        finally:
            if cid:
                runs = await db.fetch_all('SELECT run_id,status FROM agent_run WHERE conversation_id=:cid AND user_id=:uid', {'cid': cid, 'uid': uid})
                if any(row._mapping['status'] in ('running', 'awaiting_approval') for row in runs):
                    await run_repository.cancel(cid, uid)
                    await asyncio.sleep(2)
                if runs:
                    graph = await get_graph()
                    for run in runs:
                        rid = run._mapping['run_id']
                        await graph.checkpointer.adelete_thread(f'run_{rid}')
                        for table in ('agent_stream_frame', 'agent_run_event', 'agent_answer_feedback'):
                            await db.execute(f'DELETE FROM {table} WHERE run_id=:rid', {'rid': rid})
                await conversations.invalidate_cache(cid)
                await db.execute('DELETE FROM agent_execution_lease WHERE user_id=:uid', {'uid': uid})
                await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid', {'cid': cid})
                await db.execute('DELETE FROM agent_run WHERE conversation_id=:cid AND user_id=:uid', {'cid': cid, 'uid': uid})
                await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid', {'cid': cid, 'uid': uid})
            if uploaded:
                (await client.delete('/file/delete', params={'fileUrl': uploaded['url']})).raise_for_status()
            await client.post('/auth/logout', headers={'X-Auth-Refresh': '1'})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid', {'uid': uid})
            await conversations._redis.client.aclose()
            await close_graph()
            await close_client()
            await db.disconnect()
            report['checks']['temporary_fixture_cleaned'] = True
            filename = 'image-source-chat-http-smoke.json' if image_lookup else 'search-chat-http-smoke.json'
            (ROOT / 'logs' / filename).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False, indent=2))
    return report['status'] == 'passed'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--image-lookup', action='store_true', help='Infer a source lookup from a synthetic image without explicit search wording')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required')
    raise SystemExit(0 if asyncio.run(main(args.image_lookup)) else 1)
