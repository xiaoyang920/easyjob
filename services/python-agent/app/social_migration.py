"""Explicit social upgrade. DDL is replayable; history normalization is transactional.

Duplicate conversations are retained as aliases, with all message IDs preserved.
No running service invokes this upgrade automatically.
"""
import hashlib
from pathlib import Path

MIGRATION = Path(__file__).resolve().parent.parent / 'migrations/027_friends_and_messaging.sql'

async def apply_social_migration(database):
    checksum = hashlib.sha256(MIGRATION.read_bytes()+Path(__file__).read_bytes()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_social_schema',10)") != 1:
            raise RuntimeError('无法取得朋友功能迁移锁')
        try:
            exists = await connection.fetch_val("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='social_migration_state'")
            previous = exists and await connection.fetch_one('SELECT version FROM social_migration_state LIMIT 1')
            if previous:
                if previous['version'] != checksum:
                    raise RuntimeError('朋友功能迁移校验和发生变化')
                return
            # Only types 1/2 have been supported by the public send endpoint.
            if await connection.fetch_val('SELECT COUNT(*) FROM message WHERE message_type=3'):
                raise RuntimeError('发现旧类型3消息，请确认其类型后再迁移，避免把旧消息解释为文章')
            invalid = await connection.fetch_val("""SELECT COUNT(*) FROM (
                SELECT c.conversation_id FROM conversation c LEFT JOIN conversation_member cm ON cm.conversation_id=c.conversation_id
                WHERE c.conversation_type=1 GROUP BY c.conversation_id HAVING COUNT(DISTINCT cm.user_id)<>2) invalid_chats""")
            if invalid:
                raise RuntimeError('存在成员数量不是2的旧单聊，请先核对；迁移不会隐藏这些聊天')
            for statement in MIGRATION.read_text(encoding='utf-8').split(';'):
                if statement.strip():
                    await connection.execute(statement.strip())
            # Preserve every original follow row before normalizing duplicates.
            await connection.execute('CREATE TABLE IF NOT EXISTS user_focus_027_backup AS SELECT * FROM user_focus WHERE 1=0')
            async with connection.transaction():
                await connection.execute('INSERT INTO user_focus_027_backup SELECT * FROM user_focus')
                await connection.execute('CREATE TEMPORARY TABLE social_follow_normalized AS SELECT user_id,focus_user_id,MIN(focus_time) focus_time FROM user_focus GROUP BY user_id,focus_user_id')
                await connection.execute('DELETE FROM user_focus')
                await connection.execute('INSERT INTO user_focus(user_id,focus_user_id,focus_time) SELECT user_id,focus_user_id,focus_time FROM social_follow_normalized')
                await connection.execute('DROP TEMPORARY TABLE social_follow_normalized')
                await connection.execute('''INSERT IGNORE INTO direct_chat_state(user_low_id,user_high_id,conversation_id,state,permission_source)
                    SELECT pairs.lo,pairs.hi,MIN(pairs.cid),IF(MAX(pairs.has_message)=1,'ACCEPTED','NONE'),IF(MAX(pairs.has_message)=1,'LEGACY',NULL)
                    FROM (SELECT MIN(cm.user_id) lo,MAX(cm.user_id) hi,c.conversation_id cid,
                        EXISTS(SELECT 1 FROM message m WHERE m.conversation_id=c.conversation_id) has_message
                        FROM conversation c JOIN conversation_member cm ON cm.conversation_id=c.conversation_id
                        WHERE c.conversation_type=1 GROUP BY c.conversation_id HAVING COUNT(DISTINCT cm.user_id)=2) pairs
                    GROUP BY pairs.lo,pairs.hi''')
                await connection.execute('''INSERT IGNORE INTO direct_chat_alias(old_conversation_id,conversation_id)
                    SELECT c.conversation_id,d.conversation_id FROM conversation c
                    JOIN conversation_member a ON a.conversation_id=c.conversation_id
                    JOIN conversation_member b ON b.conversation_id=c.conversation_id AND a.user_id<b.user_id
                    JOIN direct_chat_state d ON d.user_low_id=a.user_id AND d.user_high_id=b.user_id
                    WHERE c.conversation_type=1 AND c.conversation_id<>d.conversation_id''')
                await connection.execute('UPDATE message m JOIN direct_chat_alias a ON a.old_conversation_id=m.conversation_id SET m.conversation_id=a.conversation_id')
                await connection.execute('''UPDATE conversation_member cm JOIN (
                    SELECT COALESCE(a.conversation_id,m.conversation_id) cid,m.user_id,MAX(m.is_top) top_flag,MAX(m.is_muted) muted_flag,
                      MIN(m.is_deleted) hidden_flag,MIN(COALESCE(m.last_read_message_id,0)) read_id
                    FROM conversation_member m LEFT JOIN direct_chat_alias a ON a.old_conversation_id=m.conversation_id
                    GROUP BY COALESCE(a.conversation_id,m.conversation_id),m.user_id
                    ) merged ON merged.cid=cm.conversation_id AND merged.user_id=cm.user_id
                    SET cm.is_top=merged.top_flag,cm.is_muted=merged.muted_flag,cm.is_deleted=merged.hidden_flag,cm.last_read_message_id=merged.read_id''')
                await connection.execute('UPDATE conversation_member cm JOIN direct_chat_alias a ON a.old_conversation_id=cm.conversation_id SET cm.is_deleted=1')
                await connection.execute('''UPDATE conversation c JOIN (SELECT conversation_id,MAX(message_id) mid FROM message GROUP BY conversation_id) latest
                    ON latest.conversation_id=c.conversation_id JOIN message m ON m.message_id=latest.mid
                    SET c.last_message_id=m.message_id,c.last_message_content=LEFT(m.content,100),c.last_message_time=m.create_time''')
                await connection.execute('''UPDATE conversation_member cm SET unread_count=(SELECT COUNT(*) FROM message m
                    WHERE m.conversation_id=cm.conversation_id AND m.sender_id<>cm.user_id AND m.message_id>COALESCE(cm.last_read_message_id,0))''')
                await connection.execute('''UPDATE user_info u SET following_count=(SELECT COUNT(*) FROM user_focus f WHERE f.user_id=u.user_id),
                    follower_count=(SELECT COUNT(*) FROM user_focus f WHERE f.focus_user_id=u.user_id)''')
            indexes = await connection.fetch_all("SELECT column_name,non_unique FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='user_focus' AND index_name='uq_user_focus_pair' ORDER BY seq_in_index")
            if indexes:
                if [r['column_name'] for r in indexes] != ['user_id','focus_user_id'] or any(r['non_unique'] for r in indexes):
                    raise RuntimeError('关注唯一索引不兼容')
            else:
                await connection.execute('CREATE UNIQUE INDEX uq_user_focus_pair ON user_focus(user_id,focus_user_id)')
            if not await connection.fetch_val("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='user_focus' AND index_name='ix_focus_reverse'"):
                await connection.execute('CREATE INDEX ix_focus_reverse ON user_focus(focus_user_id,user_id)')
            await connection.execute('INSERT INTO social_migration_state(version) VALUES(:v)', {'v':checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_social_schema')")
