"""Real direct Agent HTTP checks with disposable fixtures. No model calls or emails."""
import asyncio
import hashlib
import json
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
import yaml
from redis.asyncio import Redis

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.config import settings
from app.utils.snowflake import snowflake


async def main():
    checks, users, emails, sids, conversations, runs = [], [], [], set(), [], []
    isolated, log_file, config_path = None, None, None
    redis = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB,
                  password=settings.REDIS_PASSWORD or None, decode_responses=True)
    def expect(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        print(('PASS ' if condition else 'FAIL ') + name, flush=True)
        if not condition:
            raise AssertionError(name)
    await db.connect()
    try:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8090', timeout=15, trust_env=False) as client:
            tokens = []
            for _ in range(2):
                tag = secrets.token_hex(6)
                email = f'agent-direct-{tag}@example.invalid'; emails.append(email)
                code = '123456'
                digest = hashlib.sha256(email.encode()).hexdigest()
                await redis.set('auth:v2:code:login:' + digest, hashlib.sha256((email + ':' + code).encode()).hexdigest(), ex=600)
                reply = await client.post('/api/auth/register', json={'email': email, 'password': 'Smoke-' + secrets.token_hex(14), 'nickName': 'direct-' + tag, 'code': code})
                expect('register_fixture_' + str(len(users)), reply.status_code == 200)
                data = reply.json()['data']; users.append(int(data['userId'])); tokens.append(data['token'])
                sids.add(jwt.decode(data['token'], options={'verify_signature': False})['sid'])
                client.cookies.clear()  # Each fixture has a separate login session.
            uid = users[0]
            headers = {'Authorization': 'Bearer ' + tokens[0]}
            other = {'Authorization': 'Bearer ' + tokens[1]}
            cid, mid = snowflake.next_id(), snowflake.next_id()
            conversations.append(cid)
            await db.execute('INSERT INTO ai_conversation(conversation_id,user_id,title,message_count,create_time,update_time,status) VALUES(:cid,:uid,:title,1,NOW(),NOW(),1)',
                             {'cid': cid, 'uid': uid, 'title': 'direct transport fixture'})
            await db.execute("INSERT INTO ai_message(message_id,conversation_id,role,content,create_time) VALUES(:mid,:cid,'user','transport fixture',NOW())", {'mid': mid, 'cid': cid})
            rid, execution = str(uuid4()), str(uuid4()); runs.append(rid)
            sid = jwt.decode(tokens[0], options={'verify_signature': False})['sid']
            await db.execute("""INSERT INTO agent_run(run_id,conversation_id,user_id,request_id,input_hash,execution_token,status,deadline,executor_lease_until,auth_sid,auth_version,data_source)
                VALUES(:rid,:cid,:uid,:req,:hash,:execution,'running',TIMESTAMPADD(MINUTE,5,UTC_TIMESTAMP(6)),TIMESTAMPADD(MINUTE,5,UTC_TIMESTAMP(6)),:sid,0,'evaluation')""",
                {'rid': rid, 'cid': cid, 'uid': uid, 'req': str(uuid4()), 'hash': 'a'*64, 'execution': execution, 'sid': sid})
            await db.execute('INSERT INTO agent_stream_frame(run_id,execution_token,data) VALUES(:rid,:execution,:data)',
                             {'rid': rid, 'execution': execution, 'data': 'data:__RUN_ID__:' + rid + '\n\n'})

            result = await client.get('/api/agent/conversations', headers=headers)
            rows = result.json().get('data')
            expect('conversation_list_direct_and_large_id', result.status_code == 200 and any(r['conversationId'] == str(cid) for r in rows))
            expect('metadata_does_not_expose_summary', all('summary' not in r and 'summaryUptoMsgId' not in r for r in rows))
            result = await client.get(f'/api/agent/conversations/{cid}/messages?limit=20', headers=headers)
            expect('history_page_contract', result.status_code == 200 and result.json()['data']['items'][0]['messageId'] == str(mid))
            result = await client.get(f'/api/agent/conversations/{cid}/questions', headers=headers)
            expect('question_navigation', result.status_code == 200 and result.json()['data']['items'])
            expect('conversation_owner_enforced', (await client.get(f'/api/agent/conversations/{cid}', headers=other)).status_code == 404)
            expect('run_owner_enforced', (await client.get(f'/api/agent/runs/{rid}/events', headers=other)).status_code == 404)
            expect('memory_direct', (await client.get('/api/agent/memory', headers=headers)).status_code == 200)
            result = await client.get('/api/agent/library', headers=headers)
            expect('library_direct', result.status_code == 200 and result.json()['data']['total'] == 1)
            result = await client.get(f'/api/agent/conversations/{cid}', headers=headers)
            version = result.json()['data']['metadataVersion']
            expect('conversation_edit', (await client.patch(f'/api/agent/conversations/{cid}', headers=headers,
                json={'title': 'updated fixture', 'version': version})).status_code == 200)
            expect('stale_conversation_edit_conflict', (await client.patch(f'/api/agent/conversations/{cid}', headers=headers,
                json={'title': 'stale fixture', 'version': version})).status_code == 409)
            expect('delivery_metrics_direct', (await client.post(f'/api/agent/runs/{rid}/delivery-metrics', headers=headers,
                json={'firstAnswerMs': 123})).status_code == 200)
            expect('browser_identity_override_rejected', (await client.post('/api/agent/chat', headers=headers,
                json={'message':'not executed', 'userId': users[1]})).status_code == 422)
            expect('internal_operations_not_exposed', (await client.get('/api/agent/internal/metrics', headers=headers)).status_code == 404)
            async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', trust_env=False) as direct:
                expect('direct_external_bearer_rejected', (await direct.get('/api/agent/conversations', headers=headers)).status_code == 401)
                expect('direct_forged_identity_rejected', (await direct.get('/api/agent/conversations', headers={'X-Easyjob-Identity':'forged','X-Agent-User':str(uid)})).status_code == 401)

            # Independent gateway: Java HTTP destination is deliberately unreachable.
            # This proves public Agent reads and validation do not use Java's HTTP proxy.
            config = yaml.safe_load((ROOT / 'temp/gateway-runtime.yml').read_text(encoding='utf-8'))
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0)); port = reservation.getsockname()[1]
            config['server'] = {'address':'127.0.0.1', 'port':port}
            cloud = config.setdefault('spring',{}).setdefault('cloud',{})
            cloud['consul'] = {'enabled':False, 'discovery':{'enabled':False}}
            cloud.setdefault('gateway',{})['routes'] = [
                {'id':'agent-api','uri':'http://127.0.0.1:8000','predicates':['Path=/api/agent/**']},
                {'id':'unavailable-blog','uri':'http://127.0.0.1:1','predicates':['Path=/api/**']}]
            config_path = ROOT / 'temp' / ('agent-direct-isolated-' + secrets.token_hex(4) + '.yml')
            config_path.write_text(yaml.safe_dump(config),encoding='utf-8')
            log_file = (ROOT / 'temp/agent-direct-isolated.log').open('w', encoding='utf-8')
            isolated = subprocess.Popen(['D:/jdk/bin/java.exe','-jar',str(ROOT/'gateway/target/validated-build/easyjob-gateway-0.0.1-SNAPSHOT.jar'),
                '--spring.config.additional-location=' + config_path.as_uri()], cwd=ROOT, stdout=log_file, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=5) as isolated_client:
                ready = False
                for _ in range(60):
                    if isolated.poll() is not None: break
                    try:
                        response = await isolated_client.get('/api/agent/conversations', headers=headers)
                        if response.status_code == 200: ready = True; break
                    except httpx.HTTPError: pass
                    await asyncio.sleep(1)
                expect('agent_available_with_java_http_destination_offline', ready)
                expect('isolated_java_destination_really_unavailable', (await isolated_client.get('/api/article/list', timeout=20)).status_code == 503)
                response = await isolated_client.get('/api/agent/run-overview', headers=headers)
                expect('agent_status_independent_of_java_http', response.status_code == 200)

            # Stream keeps running until its authenticated subscriber is revoked.
            async with client.stream('GET', f'/api/agent/runs/{rid}/events', headers=headers) as response:
                expect('direct_sse_connected', response.status_code == 200)
                lines = response.aiter_lines()
                found = False
                for _ in range(4):
                    line = await asyncio.wait_for(anext(lines), 5)
                    if '__RUN_ID__:' in line: found = True; break
                expect('direct_sse_frame_preserved', found)
                start = time.monotonic()
                result = await client.delete('/api/account/sessions/' + sid, headers=headers)
                expect('session_revoked', result.status_code == 200)
                async def drain():
                    async for _ in lines: pass
                await asyncio.wait_for(drain(), 10)
                revoke_ms = round((time.monotonic() - start) * 1000)
                expect('revocation_closes_python_subscriber', True)
            state = await db.fetch_val('SELECT status FROM agent_run WHERE run_id=:rid', {'rid': rid})
            expect('closing_subscriber_does_not_cancel_execution', state == 'running')
            expect('revoked_session_cannot_reconnect', (await client.get('/api/agent/conversations', headers=headers)).status_code == 401)
            await db.execute("UPDATE agent_run SET status='succeeded',result_json='{}' WHERE run_id=:rid", {'rid':rid})
            # Use second fixture for a separate cancel path, without starting a model.
            expect('foreign_cancel_rejected', (await client.post(f'/api/agent/chat/{cid}/cancel', headers=other)).status_code == 404)
        report = {'passed':len(checks),'checks':checks,'sse_revocation_ms':revoke_ms,'model_calls':0,'emails_sent':0}
        (ROOT/'temp/agent-direct-smoke-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='checks'}),flush=True)
    finally:
        if isolated:
            isolated.terminate()
            try: isolated.wait(timeout=10)
            except subprocess.TimeoutExpired: isolated.kill(); isolated.wait()
        if log_file: log_file.close()
        if config_path: config_path.unlink(missing_ok=True)
        for rid in runs:
            for table in ('agent_stream_frame','agent_run_event','agent_answer_feedback','agent_run'):
                await db.execute(f'DELETE FROM {table} WHERE run_id=:rid', {'rid':rid})
        for cid in conversations:
            await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid',{'cid':cid})
            await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid',{'cid':cid})
        for sid in sids: await redis.delete('auth:v2:session:'+sid)
        for uid in users:
            await redis.delete('auth:v2:devices:'+str(uid),'easyjob:userSpaceInfo:'+str(uid))
            await db.execute('DELETE FROM auth_outbox WHERE user_id=:uid',{'uid':uid})
            await db.execute('DELETE FROM auth_audit WHERE target_id=:uid OR actor_id=:uid',{'uid':uid})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid',{'uid':uid})
        for email in emails:
            key='auth:v2:code:login:'+hashlib.sha256(email.encode()).hexdigest()
            await redis.delete(key,key+':attempts')
        await redis.aclose()
        await db.disconnect()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print('Direct Agent smoke failed:',type(error).__name__,str(error) if isinstance(error,AssertionError) else 'inspect sanitized service logs',flush=True)
        raise SystemExit(1)
