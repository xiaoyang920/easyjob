"""Loopback integration fixtures, real model calls, and ownership-scoped cleanup."""
import asyncio
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.config import settings
from app.utils.snowflake import snowflake
from app.services.conversation import ConversationService
from evaluation.local_samples import local_token

STATE = ROOT / 'temp/article-chat-fixtures.json'
REPORT = ROOT / 'logs/article-chat-live.json'


async def setup():
    previous = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else None
    if previous and previous['owned_articles']:
        raise RuntimeError('Previous articles exist; resume tests or clean before setup')
    uid = snowflake.next_id()
    email = 'article-chat-smoke@sample.invalid'
    if not previous and await db.fetch_val('SELECT user_id FROM user_info WHERE email=:email', {'email': email}):
        raise RuntimeError('Fixture email is already in use; refusing to overwrite')
    seed = await db.fetch_one("""SELECT a.* FROM article_info a JOIN user_info u ON u.user_id=a.user_id
        WHERE u.email='rag-eval-v1@sample.invalid' AND a.title='[评测样例] Spring Boot Starter 与条件自动配置'
        AND a.status=1 AND a.deleted=0""")
    other = await db.fetch_one("""SELECT a.article_id,a.title FROM article_info a JOIN user_info u ON u.user_id=a.user_id
        WHERE u.email='rag-eval-v1@sample.invalid' AND a.title='[评测样例] Spring Boot 第一个 REST 接口'
        AND a.status=1 AND a.deleted=0""")
    assert seed and other, 'Required seeded sample articles are missing'
    if previous:
        uid = previous['uid']
        assert await db.fetch_val("SELECT user_id FROM user_info WHERE user_id=:uid AND email=:email AND person_introduction='临时本地集成测试账号'", {'uid': uid, 'email': email}) == uid
    else:
        await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,sex,status,
        total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
        VALUES(:uid,'文章问答测试',:email,'ArticleChatTest2026!', '临时本地集成测试账号',NOW(),2,1,0,0,1,1,0,0,0)""", {'uid': uid, 'email': email})
    state = {'uid': uid, 'email': email, 'owned_articles': [], 'other_id': int(other['article_id']), 'other_title': other['title']}
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', timeout=35,
        headers={'Authorization': 'Bearer ' + local_token(uid)}) as client:
        for status in (1, 0):
            response = await client.post('/article/create', json={
                'title': '[文章问答测试] Spring Boot 条件装配' if status == 1 else '[文章问答测试] 未发布草稿',
                'content': seed['content'], 'summary': seed['summary'], 'categoryId': str(seed['category_id']),
                'contentType': seed['content_type'], 'isOriginal': 1, 'status': status, 'tagNames': []})
            response.raise_for_status()
            data = response.json()
            assert data['code'] == 200, data.get('message')
            state['owned_articles'].append(int(data['data']['articleId']))
            STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'fixture_user': email, 'article_id': state['owned_articles'][0], 'other_article_id': state['other_id']}, ensure_ascii=False), flush=True)


async def api_tests():
    state = json.loads(STATE.read_text(encoding='utf-8'))
    uid, aid, private = state['uid'], state['owned_articles'][0], state['owned_articles'][1]
    report = {'checks': [], 'real_model_calls': [], 'fixture_articles': state['owned_articles']}
    def checked(name):
        report['checks'].append(name)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(name + ': passed', flush=True)
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', timeout=310,
        headers={'Authorization': 'Bearer ' + local_token(uid)}) as client:
        async def request(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            value = response.json()
            assert value.get('code') == 200, (path, value.get('code'), value.get('message'))
            return value['data']
        async def chat(question, cid=None, origin=None):
            body = {'message': question, 'requestId': str(uuid4()), 'conversationId': str(cid) if cid else None}
            if origin: body['originArticleId'] = str(origin)
            start = time.monotonic()
            value = await request('POST', '/agent/chat', json=body)
            report['real_model_calls'].append({'question': question, 'elapsed_seconds': round(time.monotonic()-start, 3),
                'conversation_id': value['conversationId'], 'reply': value['reply'], 'citations': value.get('citations', [])})
            assert value['reply'].strip() and not value['reply'].startswith('{"interrupted"')
            return value
        before = await request('GET', '/agent/conversations', params={'scope': 'article', 'originArticleId': aid, 'limit': 1})
        assert before == []
        assert await db.fetch_val('SELECT COUNT(*) FROM ai_conversation WHERE user_id=:uid', {'uid': uid}) == 0
        checked('open_drawer_lookup_does_not_create_empty_conversation')
        first = await chat('请用两句话解释本文里的“用户提供自己的 Bean 时默认配置会退让”，并引用本文。', origin=aid)
        cid = int(first['conversationId'])
        state['first_cid'] = cid
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        assert any(str(c.get('articleId')) == str(aid) for c in first.get('citations', [])), 'Current article citation missing'
        checked('real_main_answers_current_article_with_verified_source')
        metadata = await request('GET', f'/agent/conversations/{cid}')
        assert str(metadata['originArticleId']) == str(aid)
        assert metadata['originArticleTitle'] == '[文章问答测试] Spring Boot 条件装配'
        latest = await request('GET', '/agent/conversations', params={'scope': 'article', 'originArticleId': aid, 'limit': 1})
        assert str(latest[0]['conversationId']) == str(cid)
        assert await request('GET', '/agent/conversations', params={'scope': 'general'}) == []
        checked('metadata_groups_and_latest_resume_share_the_same_conversation')
        second = await chat(f'只在本站，把当前文章和《{state["other_title"]}》（/article/{state["other_id"]}）对比，说明侧重点和阅读顺序，并分别引用两篇文章。不要联网。', cid=cid)
        sources = {str(c.get('articleId')) for c in second.get('citations', [])}
        assert {str(aid), str(state['other_id'])} <= sources, ('Cross article sources missing', sources)
        checked('real_main_retrieves_another_article_and_compares_with_current_article')
        rows = await request('GET', f'/agent/conversations/{cid}/messages')
        assert len(rows) == 4
        checked('article_drawer_and_assistant_read_same_persisted_messages')
        third = await chat('现在换个话题，直接用一句话解释 Redis 是什么，不需要搜索文章。', cid=cid)
        assert 'Redis' in third['reply'] and not third.get('citations')
        checked('article_origin_does_not_force_unrelated_questions_back_to_the_article')
        headers = {'X-Agent-Key': settings.AGENT_SERVICE_KEY, 'X-Agent-User': str(uid)}
        count = await db.fetch_val('SELECT COUNT(*) FROM ai_message WHERE conversation_id=:cid', {'cid': cid})
        async with httpx.AsyncClient(timeout=20) as agent:
            bad = await agent.post('http://127.0.0.1:8000/chat', headers=headers, json={
                'user_id': uid, 'conversation_id': cid, 'origin_article_id': state['other_id'], 'message': '不能改绑'})
            assert bad.status_code == 409
            hidden = await agent.post('http://127.0.0.1:8000/chat', headers=headers, json={
                'user_id': uid, 'origin_article_id': private, 'message': '不能读取未发布草稿'})
            assert hidden.status_code == 404
            outsider = await agent.get(f'http://127.0.0.1:8000/conversations/{cid}?user_id=1', headers={
                'X-Agent-Key': settings.AGENT_SERVICE_KEY, 'X-Agent-User': '1'})
            assert outsider.status_code == 404
        assert await db.fetch_val('SELECT COUNT(*) FROM ai_message WHERE conversation_id=:cid', {'cid': cid}) == count
        assert await db.fetch_val('SELECT COUNT(*) FROM ai_conversation WHERE user_id=:uid', {'uid': uid}) == 1
        checked('wrong_origin_private_article_and_foreign_conversation_rejected_without_writes')
    report['passed'] = True
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


async def inspect():
    state = json.loads(STATE.read_text(encoding='utf-8'))
    rows = await db.fetch_all('SELECT conversation_id,origin_article_id,message_count FROM ai_conversation WHERE user_id=:uid', {'uid': state['uid']})
    print(json.dumps([dict(r._mapping) for r in rows], ensure_ascii=False), flush=True)


async def cleanup():
    state = json.loads(STATE.read_text(encoding='utf-8'))
    uid = state['uid']
    owner = await db.fetch_one('SELECT email,person_introduction FROM user_info WHERE user_id=:uid', {'uid': uid})
    assert owner and owner['email'] == state['email'] and owner['person_introduction'] == '临时本地集成测试账号'
    owned = await db.fetch_all('SELECT article_id FROM article_info WHERE user_id=:uid', {'uid': uid})
    assert {int(r['article_id']) for r in owned} <= set(state['owned_articles'])
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', timeout=30,
        headers={'Authorization': 'Bearer ' + local_token(uid)}) as client:
        for aid in state['owned_articles']:
            response = await client.delete('/article/' + str(aid))
            assert response.json()['code'] == 200
    from app.clients.es_client import BaseEsClient
    from app.graph.builder import get_graph, close_graph
    es = BaseEsClient()
    try:
        deadline = time.monotonic() + 35
        while sum([await db.fetch_val("SELECT COUNT(*) FROM article_index_outbox WHERE article_id=:aid AND status NOT IN ('completed','dead')",
                                     {'aid': aid}) for aid in state['owned_articles']]):
            if time.monotonic() > deadline: raise TimeoutError('Outbox fixture deletion has not settled')
            await asyncio.sleep(1)
        jobs = await db.fetch_val("SELECT COUNT(*) FROM agent_background_job WHERE user_id=:uid AND status='running'", {'uid': uid})
        if jobs: raise RuntimeError('Fixture background job still running; retry cleanup when it settles')
        cids = [int(r['conversation_id']) for r in await db.fetch_all('SELECT conversation_id FROM ai_conversation WHERE user_id=:uid', {'uid': uid})]
        rids = [r['run_id'] for r in await db.fetch_all('SELECT run_id FROM agent_run WHERE user_id=:uid', {'uid': uid})]
        graph = await get_graph()
        for rid in rids: await graph.checkpointer.adelete_thread('run_' + rid)
        conversations = ConversationService()
        for cid in cids: await conversations.invalidate_cache(cid)
        for row in await db.fetch_all('SELECT memory_id FROM user_memory WHERE user_id=:uid', {'uid': uid}):
            await es.client.options(ignore_status=404).delete(index='user_memories', id=str(row['memory_id']))
        async with db.transaction():
            for table in ('agent_run_event',):
                await db.execute(f'DELETE e FROM {table} e JOIN agent_run r ON r.run_id=e.run_id WHERE r.user_id=:uid', {'uid': uid})
            for table in ('user_memory_change', 'user_memory', 'user_profile', 'agent_background_job', 'agent_run'):
                await db.execute(f'DELETE FROM {table} WHERE user_id=:uid', {'uid': uid})
            await db.execute('DELETE m FROM ai_message m JOIN ai_conversation c ON c.conversation_id=m.conversation_id WHERE c.user_id=:uid', {'uid': uid})
            await db.execute('DELETE FROM ai_conversation WHERE user_id=:uid', {'uid': uid})
            for aid in state['owned_articles']:
                await db.execute('DELETE FROM article_index_outbox WHERE article_id=:aid', {'aid': aid})
                await db.execute('DELETE FROM article_tag_relation WHERE article_id=:aid', {'aid': aid})
                await db.execute('DELETE FROM article_info WHERE article_id=:aid AND user_id=:uid', {'aid': aid, 'uid': uid})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:email', {'uid': uid, 'email': state['email']})
        assert not await db.fetch_val('SELECT COUNT(*) FROM ai_conversation WHERE user_id=:uid', {'uid': uid})
        report = json.loads(REPORT.read_text(encoding='utf-8')) if REPORT.exists() else {}
        report['fixtures_removed'] = True
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        STATE.unlink()
        print('Owned test articles, conversations, runs, checkpoints, jobs and account removed.', flush=True)
    finally:
        await es.client.close()
        await close_graph()


async def main():
    await db.connect()
    try: await {'setup': setup, 'api': api_tests, 'inspect': inspect, 'cleanup': cleanup}[sys.argv[1]]()
    finally: await db.disconnect()


if __name__ == '__main__': asyncio.run(main())
