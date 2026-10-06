"""Isolated loopback fixtures and regression checks for chat/profile/notification UI."""
import asyncio
import importlib.util
import json
import sys
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('article_smoke', ROOT / 'scripts/article-chat-smoke.py')
article = importlib.util.module_from_spec(spec)
spec.loader.exec_module(article)
db, token, snowflake = article.db, article.local_token, article.snowflake
STATE = ROOT / 'temp/ui-pages-fixtures.json'
REPORT = ROOT / 'logs/ui-pages-api.json'


def save(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


async def setup():
    assert not STATE.exists(), 'Previous fixtures exist; clean before setup'
    a = json.loads(article.STATE.read_text(encoding='utf-8'))
    uid, peer = a['uid'], snowflake.next_id()
    email = 'ui-pages-peer@sample.invalid'
    assert not await db.fetch_val('SELECT COUNT(*) FROM user_info WHERE email=:email', {'email': email})
    state = {'uid': uid, 'peer': peer, 'peer_email': email, 'uploads': [], 'cid': None}
    save(state)
    await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,
        sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
        VALUES(:uid,'界面联调',:email,'UiPagesTest2026!','临时本地集成测试账号',NOW(),2,1,0,0,1,1,0,0,0)""",
        {'uid': peer, 'email': email})
    await db.execute("UPDATE user_info SET nick_name='阅读与代码' WHERE user_id=:uid", {'uid': uid})
    seed = await db.fetch_one('SELECT * FROM article_info WHERE article_id=:aid', {'aid': a['owned_articles'][0]})
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', timeout=30,
                                 headers={'Authorization': 'Bearer ' + token(uid)}) as client:
        async def call(method, path, **kwargs):
            res = await client.request(method, path, **kwargs)
            res.raise_for_status()
            data = res.json()
            assert data['code'] == 200, data.get('message')
            return data['data']
        for title in ('[界面测试] Redis 缓存与数据一致性', '[界面测试] RAG 从检索到回答'):
            created = await call('POST', '/article/create', json={'title': title, 'content': seed['content'],
                'summary': seed['summary'], 'categoryId': str(seed['category_id']), 'contentType': seed['content_type'],
                'isOriginal': 1, 'status': 1, 'tagNames': []})
            a['owned_articles'].append(int(created['articleId']))
            article.STATE.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding='utf-8')
        state['cid'] = (await call('POST', '/chat/conversation/create', json={'targetUserId': str(peer)}))['conversationId']
        save(state)
        for size, label, color in (((1200, 300), 'WIDE 1200 x 300', '#d3f795'), ((300, 1200), 'TALL 300 x 1200', '#f3a093')):
            image = Image.new('RGB', size, color)
            draw = ImageDraw.Draw(image)
            draw.rectangle((4, 4, size[0] - 5, size[1] - 5), outline='#11110f', width=8)
            draw.text((25, 25), label, fill='#11110f')
            draw.text((25, size[1] - 40), 'BOTTOM EDGE', fill='#11110f')
            content = BytesIO()
            image.save(content, format='PNG')
            uploaded = await call('POST', '/file/upload-message', files={'file': ('ui-test.png', content.getvalue(), 'image/png')})
            state['uploads'].append(uploaded)
            save(state)
            await call('POST', '/chat/message/send', json={'conversationId': state['cid'], 'messageType': 2, 'content': uploaded['url']})
    for read, content, typ in ((0, '收藏了你的文章', 3), (1, '赞了你的文章', 2), (0, '评论了你的文章', 1)):
        await db.execute("""INSERT INTO notification(notification_id,user_id,sender_id,sender_nickname,type,
            article_id,article_title,content,is_read,create_time)
            VALUES(:id,:uid,:peer,'界面联调',:type,:aid,'Spring Boot 条件装配',:content,:read,NOW())""",
            {'id': snowflake.next_id(), 'uid': uid, 'peer': peer, 'type': typ, 'aid': a['owned_articles'][0],
             'content': content, 'read': read})
    print('Isolated chat, wide/portrait uploads, notifications and profile cards ready.', flush=True)


async def api():
    state = json.loads(STATE.read_text(encoding='utf-8'))
    cid = state['cid']
    checks = []
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', timeout=30,
                                 headers={'Authorization': 'Bearer ' + token(state['uid'])}) as client:
        async def call(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            data = response.json()
            assert data['code'] == 200, data.get('message')
            return data['data']
        async def summary():
            rows = await call('GET', '/chat/conversations')
            return next(row['lastMessage'] for row in rows if row['conversationId'] == cid)
        assert await summary() == '[图片]'
        checks.append('image_summary_after_reload')
        url = state['uploads'][0]['url']
        await call('POST', '/chat/message/send', json={'conversationId': cid, 'messageType': 1, 'content': url})
        assert await summary() == url  # A text URL must remain text, rather than guessed to be an image.
        checks.append('text_url_is_not_misclassified')
        image = await call('POST', '/chat/message/send', json={'conversationId': cid, 'messageType': 2, 'content': url})
        await call('POST', '/chat/message/' + image['messageId'] + '/recall')
        assert await summary() == '[消息已撤回]'
        checks.append('recalled_image_summary')
        async with db.transaction():
            await db.execute('UPDATE message SET status=2 WHERE message_id=:mid', {'mid': image['messageId']})
        assert await summary() == '[消息已删除]'
        checks.append('deleted_image_summary')
        # Restore the actual latest two uploaded images for browser screenshots.
        await db.execute('DELETE FROM message WHERE conversation_id=:cid AND message_id>=:first', {'cid': cid, 'first': image['messageId']})
        rows = await db.fetch_all('SELECT message_id,content FROM message WHERE conversation_id=:cid AND message_type=2 AND status=0 ORDER BY message_id DESC', {'cid': cid})
        latest = rows[0]
        await db.execute('DELETE FROM message WHERE conversation_id=:cid AND message_id>:mid', {'cid': cid, 'mid': latest['message_id']})
        await db.execute('UPDATE conversation SET last_message_id=:mid,last_message_content=:content WHERE conversation_id=:cid',
                         {'mid': latest['message_id'], 'content': latest['content'], 'cid': cid})
        for upload in state['uploads']:
            res = await client.get('http://127.0.0.1:3000' + upload['url'])
            res.raise_for_status()
            picture = Image.open(BytesIO(res.content))
            assert picture.size in ((1200, 300), (300, 1200))
        checks.append('uploaded_image_dimensions_preserved')
    REPORT.write_text(json.dumps({'checks': checks}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': len(checks), 'checks': checks}), flush=True)


async def cleanup():
    state = json.loads(STATE.read_text(encoding='utf-8'))
    a = json.loads(article.STATE.read_text(encoding='utf-8'))
    assert state['uid'] == a['uid']
    peer = await db.fetch_one('SELECT email,person_introduction FROM user_info WHERE user_id=:uid', {'uid': state['peer']})
    assert peer['email'] == state['peer_email'] and peer['person_introduction'] == '临时本地集成测试账号'
    # The optional, explicit upload root is checked before removing only the generated files.
    if len(sys.argv) > 2:
        root = Path(sys.argv[2]).resolve()
        candidates = []
        for upload in state['uploads']:
            assert upload['fileName'] == 'ui-test.png' and upload['url'].startswith('/uploads/messages/')
            target = (root / upload['url'].removeprefix('/uploads/')).resolve()
            assert target.is_relative_to(root / 'messages') and target.is_file()
            assert Image.open(target).size in ((1200, 300), (300, 1200))
            candidates.append(target)
        for target in candidates:
            target.unlink()
    if state['cid']:
        members = await db.fetch_all('SELECT user_id FROM conversation_member WHERE conversation_id=:cid', {'cid': state['cid']})
        assert {int(m['user_id']) for m in members} == {state['uid'], state['peer']}
        async with db.transaction():
            for table in ('message', 'conversation_member', 'conversation'):
                await db.execute(f'DELETE FROM {table} WHERE conversation_id=:cid', {'cid': state['cid']})
    await db.execute('DELETE FROM notification WHERE user_id=:uid AND sender_id=:peer', {'uid': state['uid'], 'peer': state['peer']})
    await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:email', {'uid': state['peer'], 'email': state['peer_email']})
    await article.cleanup()
    STATE.unlink()
    report = json.loads(REPORT.read_text(encoding='utf-8'))
    report['database_fixtures_removed'] = True
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('UI fixture accounts, messages and notifications removed.', flush=True)


async def main():
    await db.connect()
    try:
        await {'setup': setup, 'api': api, 'cleanup': cleanup}[sys.argv[1]]()
    finally:
        await db.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
