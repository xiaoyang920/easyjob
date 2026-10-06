"""Disposable local legacy-profile fixture for browser QA; Enter cleans it up."""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python-agent'))
from app.clients.mysql_client import db
from app.utils.snowflake import SnowflakeGenerator

async def main():
    assert db.url.hostname in {'localhost', '127.0.0.1', '::1'}
    marker = 'profile-topics-' + uuid4().hex[:10]
    uid = SnowflakeGenerator(worker_id=27).next_id()
    await db.connect()
    try:
        running = await db.fetch_val("SELECT COUNT(*) FROM agent_run WHERE status='running' AND deadline>UTC_TIMESTAMP(6)")
        print(f'Active runs: {running}', flush=True)
        await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
            VALUES(:uid,'画像测试',:email,'LocalProfileQa2026!',:marker,NOW(),2,1,0,0,1,1,0,0,0)''', {'uid': uid, 'email': marker+'@sample.invalid', 'marker': marker})
        await db.execute('''INSERT INTO user_profile(user_id,tech_stack,interests,experience,preferences,create_time,update_time)
            VALUES(:uid,'["Java", "Redis"]','["Redis", "Agent"]','Python 新手','{"code_language":"Java", "language":"中文"}',NOW(),NOW())''', {'uid': uid})
        print(f'Account: {marker}@sample.invalid / LocalProfileQa2026!', flush=True)
        await asyncio.to_thread(input, 'Enter after QA to clean fixture: ')
        row = await db.fetch_one('SELECT tech_stack,interests,experience FROM user_profile WHERE user_id=:uid', {'uid': uid})
        if row:
            assert row._mapping['tech_stack'] == '[]', 'Browser save must clear legacy topics'
            assert 'Redis' not in row._mapping['interests'], 'Removed topic must not return'
            assert row._mapping['experience'] == 'Python 新手', 'Background must survive topic editing'
            print('Real database save and topic removal verified.', flush=True)
    finally:
        if await db.fetch_val('SELECT COUNT(*) FROM user_info WHERE user_id=:uid AND person_introduction=:marker', {'uid': uid, 'marker': marker}) == 1:
            await db.execute('DELETE FROM user_profile WHERE user_id=:uid', {'uid': uid})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid AND person_introduction=:marker', {'uid': uid, 'marker': marker})
        await db.disconnect()
        print('Fixture cleaned.', flush=True)

if __name__ == '__main__': asyncio.run(main())
