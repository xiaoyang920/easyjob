"""Real Main decisions and AI image history using the isolated UI fixtures."""
import asyncio
import importlib.util
import json
from pathlib import Path
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fixtures', ROOT / 'scripts/article-chat-smoke.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
db = fixtures.db


async def main():
    await db.connect()
    try:
        owner = json.loads(fixtures.STATE.read_text(encoding='utf-8'))
        state = json.loads((ROOT / 'temp/ui-pages-fixtures.json').read_text(encoding='utf-8'))
        assert owner['uid'] == state['uid']
        uid = owner['uid']
        report = {'checks': [], 'replies': []}
        path = ROOT / 'logs/nav-memory-live.json'
        def record(check):
            report['checks'].append(check)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(check + ': passed', flush=True)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', timeout=180,
                                    headers={'Authorization': 'Bearer ' + fixtures.local_token(uid)}) as client:
            cid = None
            async def chat(message):
                nonlocal cid
                response = await client.post('/agent/chat', json={'message': message, 'conversationId': cid, 'requestId': str(uuid4())})
                response.raise_for_status()
                data = response.json()
                assert data['code'] == 200, data.get('message')
                cid = data['data']['conversationId']
                report['replies'].append({'message': message, 'reply': data['data']['reply']})
                path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                return data['data']['reply']
            await chat('我主要做 Java 后端开发，以后默认用中文回答。请记住这个长期背景和语言偏好，只需简短确认。')
            profile = await db.fetch_one('SELECT interests,preferences FROM user_profile WHERE user_id=:uid', {'uid': uid})
            assert profile and 'Java' in profile['interests'] and ('中文' in profile['preferences'] or 'zh' in profile['preferences'])
            record('profile_and_language_saved_on_first_user_turn')
            await chat('本会话以后不要联网，请记住这条会话约束，只需简短确认。')
            assert await db.fetch_val("SELECT COUNT(*) FROM user_memory WHERE user_id=:uid AND scope_conversation_id=:cid AND memory_type='constraint' AND memory_key='web_search' AND status='active'", {'uid': uid, 'cid': int(cid)})
            record('conversation_constraint_saved_immediately')
            await chat('我已经确认本会话的 RAG 检索采用 RRF 融合方案。这是已经确定的决策，请记住，只需简短确认。')
            assert await db.fetch_val("SELECT COUNT(*) FROM user_memory WHERE user_id=:uid AND scope_conversation_id=:cid AND memory_type='decision' AND content LIKE '%RRF%' AND status='active'", {'uid': uid, 'cid': int(cid)})
            record('confirmed_decision_saved_immediately')
            reply = await chat('你们后端的长期画像、约束、决策和普通历史事件分别什么时候写入？普通事件是不是每六轮提取一次？请按实际实现说明。')
            assert ('6' in reply or '六' in reply) and ('300' in reply or '5 分钟' in reply or '5分钟' in reply or '五分钟' in reply)
            assert not ('不存在' in reply and '轮' in reply)
            record('main_explains_periodic_events_and_immediate_structured_changes')
        conversations = fixtures.ConversationService()
        visual = await conversations.create_conversation(uid)
        for upload in state['uploads']:
            await conversations.add_message(visual, 'user', '查看图片完整比例', image_paths=[upload['url'].removeprefix('/uploads/')], postprocess=False)
            await conversations.add_message(visual, 'assistant', '这是界面测试图片，可以点击查看完整原图。', postprocess=False)
        await db.execute("UPDATE ai_conversation SET title='AI 图片比例测试' WHERE conversation_id=:cid", {'cid': visual})
        await conversations.invalidate_cache(visual)
        report['visual_conversation_id'] = str(visual)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('AI image fixture ready: ' + str(visual), flush=True)
    finally:
        await db.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
