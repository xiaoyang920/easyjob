"""Create a disposable local MySQL schema, rehearse migration, run Java SQL/concurrency tests, drop only that schema."""
import asyncio
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse, unquote
import uuid
import pymysql
from databases import Database

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.config import settings
from app.social_migration import apply_social_migration

BASE='''
CREATE TABLE user_info(user_id BIGINT PRIMARY KEY,nick_name VARCHAR(100),avatar VARCHAR(255),person_introduction VARCHAR(255),status TINYINT(1) DEFAULT 1,following_count INT DEFAULT 0,follower_count INT DEFAULT 0);
CREATE TABLE user_focus(user_id BIGINT,focus_user_id BIGINT,focus_time DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE conversation(conversation_id BIGINT PRIMARY KEY,conversation_type INT,creator_id BIGINT,last_message_id BIGINT,last_message_content VARCHAR(100),last_message_time DATETIME,create_time DATETIME DEFAULT CURRENT_TIMESTAMP,update_time DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE conversation_member(id BIGINT PRIMARY KEY,conversation_id BIGINT,user_id BIGINT,last_read_message_id BIGINT,unread_count INT DEFAULT 0,is_muted INT DEFAULT 0,is_top INT DEFAULT 0,is_deleted INT DEFAULT 0,join_time DATETIME DEFAULT CURRENT_TIMESTAMP,update_time DATETIME DEFAULT CURRENT_TIMESTAMP,UNIQUE KEY(conversation_id,user_id));
CREATE TABLE message(message_id BIGINT PRIMARY KEY,conversation_id BIGINT,sender_id BIGINT,message_type INT DEFAULT 1,content TEXT,status TINYINT(1) DEFAULT 0,reply_to_message_id BIGINT,client_message_id VARCHAR(64),extra_data JSON,create_time DATETIME DEFAULT CURRENT_TIMESTAMP,KEY(conversation_id,message_id));
CREATE TABLE article_info(article_id BIGINT PRIMARY KEY,user_id BIGINT,title VARCHAR(200),cover_image VARCHAR(255),status INT DEFAULT 1,deleted INT DEFAULT 0,required_level INT DEFAULT 0);
'''

async def main():
    url=urlparse(settings.mysql_url)
    if url.hostname not in {'localhost','127.0.0.1','::1'}:raise RuntimeError('Isolated tests only use local MySQL')
    name='easyjob_social_test_'+uuid.uuid4().hex[:12]
    if not re.fullmatch(r'easyjob_social_test_[a-f0-9]{12}',name):raise RuntimeError('Invalid disposable schema')
    conn=pymysql.connect(host=url.hostname,port=url.port or 3306,user=unquote(url.username or ''),password=unquote(url.password or ''),autocommit=True,charset='utf8mb4')
    database=None
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4')
            cur.execute(f'USE `{name}`')
            for statement in BASE.split(';'):
                if statement.strip():cur.execute(statement)
            cur.execute("INSERT INTO user_info(user_id,nick_name) VALUES(1,'旧用户1'),(2,'旧用户2')")
            cur.execute('INSERT INTO user_focus(user_id,focus_user_id) VALUES(1,2),(1,2)')
            cur.execute('INSERT INTO conversation(conversation_id,conversation_type,creator_id) VALUES(10,1,1),(11,1,1)')
            cur.execute('INSERT INTO conversation_member(id,conversation_id,user_id) VALUES(1,10,1),(2,10,2),(3,11,1),(4,11,2)')
            cur.execute("INSERT INTO message(message_id,conversation_id,sender_id,content) VALUES(101,10,1,'旧消息1'),(102,11,2,'旧消息2')")
        database=Database(url._replace(path='/'+name).geturl())
        await database.connect()
        await apply_social_migration(database)
        assert await database.fetch_val('SELECT COUNT(*) FROM message WHERE conversation_id=10')==2
        assert await database.fetch_val('SELECT COUNT(*) FROM direct_chat_alias WHERE old_conversation_id=11 AND conversation_id=10')==1
        assert await database.fetch_val('SELECT COUNT(*) FROM user_focus')==1
        assert await database.fetch_val('SELECT COUNT(*) FROM user_focus_027_backup')==2
        assert await database.fetch_val("SELECT COUNT(*) FROM direct_chat_state WHERE permission_source='LEGACY' AND state='ACCEPTED'")==1
        await database.execute("INSERT INTO direct_chat_state(user_low_id,user_high_id,state,initiator_id) VALUES(7,8,'PENDING',7)")
        await apply_social_migration(database)
        assert await database.fetch_val("SELECT state FROM direct_chat_state WHERE user_low_id=7 AND user_high_id=8")=='PENDING'
        print('Migration rehearsal passed: duplicate history retained, aliases valid, replay does not grant new consent.',flush=True)
        await database.disconnect();database=None
        env=os.environ.copy();env.update(SOCIAL_TEST_JDBC_URL=f'jdbc:mysql://{url.hostname}:{url.port or 3306}/{name}?useUnicode=true&characterEncoding=UTF-8&serverTimezone=UTC',SOCIAL_TEST_USERNAME=unquote(url.username or ''),SOCIAL_TEST_PASSWORD=unquote(url.password or ''))
        command=['mvn.cmd' if os.name=='nt' else 'mvn','-q','-Dnet.bytebuddy.experimental=true','-Dtest=SocialDatabaseTests,SocialPolicyTests,MessageDeliveryTests,ChatMultiSessionTests','test']
        result=await asyncio.to_thread(subprocess.run,command,cwd=ROOT,env=env,check=False)
        if result.returncode:raise RuntimeError('Social test suite failed')
        print('Isolated social SQL/concurrency suite passed.',flush=True)
    finally:
        if database is not None:await database.disconnect()
        # Exact generated schema name is checked above; never use the configured application database.
        with conn.cursor() as cur:cur.execute(f'DROP DATABASE IF EXISTS `{name}`')
        conn.close()

if __name__=='__main__':asyncio.run(main())
