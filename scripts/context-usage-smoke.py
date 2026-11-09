"""Local HTTP/SQL integration of context telemetry with disposable fixtures, no LLM calls."""
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.services.context_usage import measured_context_usage
from app.services.conversation import ConversationService
from evaluation.context_extended_live import resources, identity, login, cleanup


async def main():
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)
        print('PASS ' + name, flush=True)

    async with resources() as (saver, client):
        fixtures = []
        try:
            fixture = await identity(); fixtures.append(fixture)
            other = await identity(); fixtures.append(other)
            await login(client, fixture)
            cid = await ConversationService().create_conversation(fixture['user_id'])
            foreign = await ConversationService().create_conversation(other['user_id'])
            path = f'/api/agent/conversations/{cid}/context-usage'
            initial = await client.get('/api/agent/context-usage')
            check('configured window without fake zero', initial.status_code == 200 and
                  initial.json()['data']['usedTokens'] is None and initial.json()['data']['limitTokens'] > 0)
            empty = await client.get(path)
            check('empty conversation is unknown', empty.status_code == 200 and empty.json()['data']['usedTokens'] is None)
            view = {'total_tokens': 65536, 'window': measured_context_usage({'total_tokens': 65536})}
            await db.execute('''INSERT INTO agent_run(run_id,conversation_id,user_id,request_id,input_hash,
                execution_token,status,deadline,executor_lease_until,result_json,data_source)
                VALUES(:rid,:cid,:uid,:req,:hash,:execution,'succeeded',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),
                       :result,'evaluation')''',
                {'rid': str(uuid4()), 'cid': cid, 'uid': fixture['user_id'], 'req': str(uuid4()), 'hash': 'a'*64,
                 'execution': str(uuid4()), 'result': json.dumps({'metrics': {'context_views': [
                     {'total_tokens': 1000}, view]}, 'private_fixture': 'must not appear'})})
            restored = await client.get(path)
            check('latest persisted request restored through website and gateway', restored.status_code == 200 and
                  restored.json()['data']['usedTokens'] == 65536)
            check('only public telemetry returned', 'must not appear' not in restored.text and
                  restored.json()['data']['limitTokens'] == view['window']['limitTokens'])
            denied = await client.get(f'/api/agent/conversations/{foreign}/context-usage')
            check('foreign conversation rejected', denied.status_code == 404)
            repeated = await client.get(path)
            check('refresh restores same measurement', repeated.json()['data'] == restored.json()['data'])
        finally:
            for fixture in fixtures:
                await login(client, fixture)
                await cleanup(client, saver, fixture)
    print(json.dumps({'passed': len(checks), 'model_calls': 0, 'fixtures_cleaned': True}))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print('Context usage smoke failed: ' + type(error).__name__)
        raise SystemExit(1)
