"""Explicit, replayable metadata upgrade: python -m app.migrate.

MySQL DDL auto-commits. Add missing columns individually so partial upgrades
can be retried. The application only checks the schema at startup.
"""
import asyncio
import hashlib
import re
from pathlib import Path

from app.clients.mysql_client import db

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "001_message_metadata.sql"
REQUIRED_COLUMNS = {"draft_article_id": "bigint", "citations": "json"}
RUNTIME_MIGRATION = MIGRATION.with_name("002_agent_runs.sql")
MEMORY_MIGRATION = MIGRATION.with_name("003_structured_memory.sql")
CONTENT_MIGRATION = MIGRATION.with_name("004_message_content_capacity.sql")
JOBS_MIGRATION = MIGRATION.with_name("005_durable_jobs.sql")
ARTICLE_CONVERSATION_MIGRATION = MIGRATION.with_name("006_article_conversations.sql")
DELIVERY_MIGRATION = MIGRATION.with_name("007_delivery_and_admission.sql")
OPTIMIZATION_MIGRATION = MIGRATION.with_name("008_query_and_reading_indexes.sql")
HEARTBEAT_MIGRATION = MIGRATION.with_name("009_executor_heartbeat.sql")
READING_MIGRATION = MIGRATION.with_name("010_reading_levels.sql")
ADMIN_MIGRATION = MIGRATION.with_name("011_admin_console.sql")
REVISION_MIGRATION = MIGRATION.with_name("012_article_revisions.sql")
VIEW_SYNC_MIGRATION = MIGRATION.with_name("013_article_view_sync.sql")
MEMORY_COLUMNS = {"memory_type": "varchar", "scope": "varchar", "scope_conversation_id": "bigint",
                  "status": "varchar", "memory_key": "varchar", "source_quote": "varchar"}


async def memory_columns(database):
    rows = await database.fetch_all("""SELECT COLUMN_NAME AS name, DATA_TYPE AS type FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='user_memory'""")
    return {r._mapping["name"]: r._mapping["type"].lower() for r in rows}


async def check_memory_schema(database):
    columns = await memory_columns(database)
    receipts = await database.fetch_all("""SELECT COLUMN_NAME AS name, DATA_TYPE AS type FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='user_memory_change'""")
    receipt_columns = {r._mapping["name"]: r._mapping["type"].lower() for r in receipts}
    if any(columns.get(k) != v for k, v in MEMORY_COLUMNS.items()) or any(receipt_columns.get(k) != v for k, v in
            {"run_id": "char", "user_id": "bigint", "conversation_id": "bigint", "change_hash": "char", "result_json": "json", "index_synced": "tinyint"}.items()):
        raise RuntimeError("结构化记忆字段未就绪；请备份并运行 python -m app.migrate")


async def apply_memory_migration(database):
    sql = MEMORY_MIGRATION.read_text(encoding="utf-8")
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema', 10)") != 1:
            raise RuntimeError("无法取得数据库迁移锁")
        try:
            columns = await memory_columns(connection)
            if not columns:
                raise RuntimeError("user_memory表不存在；请先部署记忆业务表")
            previous = await connection.fetch_one("SELECT checksum FROM agent_schema_migration WHERE version=:version",
                                                  {"version": MEMORY_MIGRATION.name})
            if previous and previous._mapping["checksum"] != checksum:
                raise RuntimeError("结构化记忆迁移校验和发生变化")
            for statement in sql.split(";"):
                statement = statement.strip()
                if not statement:
                    continue
                match = re.fullmatch(r"ALTER TABLE user_memory ADD COLUMN (\w+) .+", statement)
                if match:
                    name = match.group(1)
                    if name in columns:
                        if columns[name] != MEMORY_COLUMNS[name]:
                            raise RuntimeError(f"已存在记忆字段{name}类型不兼容")
                        continue
                await connection.execute(statement)
            await check_memory_schema(connection)
            await connection.execute("INSERT IGNORE INTO agent_schema_migration (version,checksum) VALUES (:version,:checksum)",
                                     {"version": MEMORY_MIGRATION.name, "checksum": checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def check_runtime_schema(database):
    rows = await database.fetch_all("""SELECT TABLE_NAME AS name FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('agent_run','agent_run_event')""")
    if {r._mapping["name"] for r in rows} != {"agent_run", "agent_run_event"}:
        raise RuntimeError("运行状态表未就绪；请备份并运行 python -m app.migrate")
    columns = await database.fetch_all("""SELECT COLUMN_NAME AS name, DATA_TYPE AS type, EXTRA AS extra
        FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_run'""")
    expected = {"run_id": "char", "conversation_id": "bigint", "user_id": "bigint", "request_id": "char",
                "input_hash": "char", "execution_token": "char", "status": "varchar", "deadline": "datetime",
                "draft_hash": "char", "draft_article_id": "bigint", "result_json": "json", "active_conversation_id": "bigint"}
    actual = {r._mapping["name"]: r._mapping["type"].lower() for r in columns}
    if any(actual.get(name) != kind for name, kind in expected.items()):
        raise RuntimeError("agent_run 字段结构不兼容")
    generated = next(r._mapping["extra"] for r in columns if r._mapping["name"] == "active_conversation_id")
    indexes = await database.fetch_all("""SELECT INDEX_NAME AS name, COLUMN_NAME AS column_name FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_run' AND NON_UNIQUE=0""")
    keys = {}
    for index in indexes:
        keys.setdefault(index._mapping["name"], set()).add(index._mapping["column_name"])
    if "GENERATED" not in generated.upper() or keys.get("uq_agent_active_conversation") != {"active_conversation_id"} or keys.get("uq_agent_request") != {"user_id", "request_id"}:
        raise RuntimeError("agent_run 缺少运行占用或幂等约束")


async def apply_runtime_migration(database):
    sql = RUNTIME_MIGRATION.read_text(encoding="utf-8")
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema', 10)") != 1:
            raise RuntimeError("无法取得数据库迁移锁")
        try:
            previous = await connection.fetch_one("SELECT checksum FROM agent_schema_migration WHERE version=:version",
                                                  {"version": RUNTIME_MIGRATION.name})
            if previous and previous._mapping["checksum"] != checksum:
                raise RuntimeError("运行表迁移校验和发生变化")
            for statement in sql.split(";"):
                if statement.strip():
                    await connection.execute(statement.strip())
            await check_runtime_schema(connection)
            await connection.execute("INSERT IGNORE INTO agent_schema_migration (version,checksum) VALUES (:version,:checksum)",
                                     {"version": RUNTIME_MIGRATION.name, "checksum": checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def _columns(database) -> dict[str, str]:
    rows = await database.fetch_all(
        """SELECT COLUMN_NAME AS name, DATA_TYPE AS type FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_message'"""
    )
    return {row._mapping["name"]: row._mapping["type"].lower() for row in rows}


async def check_message_schema(database):
    columns = await _columns(database)
    if any(columns.get(name) != kind for name, kind in REQUIRED_COLUMNS.items()):
        raise RuntimeError("ai_message 元数据结构未就绪；请先备份数据库并运行 python -m app.migrate")


async def check_content_schema(database):
    columns = await _columns(database)
    if columns.get('content') not in ('mediumtext', 'longtext'):
        raise RuntimeError("ai_message.content 容量不足；请先备份数据库并运行 python -m app.migrate")


async def apply_content_migration(database):
    """Only widen TEXT. Preserve existing nullability, collation and comment."""
    checksum = hashlib.sha256(CONTENT_MIGRATION.read_bytes()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema', 10)") != 1:
            raise RuntimeError("无法取得数据库迁移锁")
        try:
            previous = await connection.fetch_one("SELECT checksum FROM agent_schema_migration WHERE version=:version",
                                                  {'version': CONTENT_MIGRATION.name})
            if previous and previous._mapping['checksum'] != checksum:
                raise RuntimeError("消息正文容量迁移校验和发生变化")
            row = await connection.fetch_one("""SELECT DATA_TYPE AS type, IS_NULLABLE AS nullable,
                COLUMN_DEFAULT AS default_value, COLLATION_NAME AS collation, COLUMN_COMMENT AS comment, EXTRA AS extra
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ai_message' AND COLUMN_NAME='content'""")
            if not row:
                raise RuntimeError("ai_message.content 不存在")
            column = row._mapping
            if column['type'].lower() == 'text':
                if column['default_value'] is not None or column['extra'] or not re.fullmatch(r'[a-zA-Z0-9_]+', column['collation'] or ''):
                    raise RuntimeError("消息正文列有特殊定义，请人工确认后扩容")
                nullable = 'NULL' if column['nullable'] == 'YES' else 'NOT NULL'
                await connection.execute(
                    f"ALTER TABLE ai_message MODIFY COLUMN content MEDIUMTEXT COLLATE {column['collation']} {nullable} COMMENT :comment",
                    {'comment': column['comment']})
            elif column['type'].lower() not in ('mediumtext', 'longtext'):
                raise RuntimeError("消息正文列类型不兼容，拒绝自动转换")
            await check_content_schema(connection)
            await connection.execute("INSERT IGNORE INTO agent_schema_migration (version,checksum) VALUES (:version,:checksum)",
                                     {'version': CONTENT_MIGRATION.name, 'checksum': checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def apply_migration(database):
    sql = MIGRATION.read_text(encoding="utf-8")
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    async with database.connection() as connection:
        acquired = await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema', 10)")
        if acquired != 1:
            raise RuntimeError("无法取得数据库迁移锁")
        try:
            columns = await _columns(connection)
            if not columns:
                raise RuntimeError("ai_message 表不存在；请先部署项目业务表")
            await connection.execute("""CREATE TABLE IF NOT EXISTS agent_schema_migration (
                version VARCHAR(100) PRIMARY KEY, checksum CHAR(64) NOT NULL,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            previous = await connection.fetch_one(
                "SELECT checksum FROM agent_schema_migration WHERE version = :version",
                {"version": MIGRATION.name},
            )
            if previous and previous._mapping["checksum"] != checksum:
                raise RuntimeError("已执行迁移的校验和发生变化")
            for statement in sql.split(";"):
                if not statement.strip():
                    continue
                match = re.fullmatch(r"ALTER TABLE ai_message ADD COLUMN (\w+) .+", statement.strip())
                if not match:
                    raise RuntimeError("非法的元数据迁移语句")
                name = match.group(1)
                if name in columns and columns[name] != REQUIRED_COLUMNS[name]:
                    raise RuntimeError(f"已存在字段 {name} 类型不兼容")
                if name not in columns:
                    await connection.execute(statement.strip())
            await check_message_schema(connection)
            await connection.execute(
                "INSERT IGNORE INTO agent_schema_migration (version, checksum) VALUES (:version, :checksum)",
                {"version": MIGRATION.name, "checksum": checksum},
            )
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def check_jobs_schema(database):
    expected = {
        "agent_background_job": {"job_id": "char", "kind": "varchar", "user_id": "bigint", "conversation_id": "bigint", "payload": "json"},
        "article_index_outbox": {"job_id": "char", "article_id": "bigint", "action": "varchar", "routing_key": "varchar"},
    }
    shared = {"status": "varchar", "attempts": "int", "available_at": "datetime", "lease_until": "datetime",
              "lease_token": "char", "last_error": "varchar", "created_at": "datetime", "updated_at": "datetime"}
    for table, columns in expected.items():
        rows = await database.fetch_all("""SELECT COLUMN_NAME AS name, DATA_TYPE AS type FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:table""", {"table": table})
        actual = {r._mapping["name"]: r._mapping["type"].lower() for r in rows}
        if any(actual.get(k) != v for k, v in {**shared, **columns}.items()):
            raise RuntimeError(f"可靠任务表 {table} 未就绪；请运行 python -m app.migrate")


async def apply_jobs_migration(database):
    sql = JOBS_MIGRATION.read_text(encoding="utf-8")
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema', 10)") != 1:
            raise RuntimeError("无法取得数据库迁移锁")
        try:
            old = await connection.fetch_one("SELECT checksum FROM agent_schema_migration WHERE version=:version", {"version": JOBS_MIGRATION.name})
            if old and old._mapping["checksum"] != checksum:
                raise RuntimeError("可靠任务迁移校验和发生变化")
            for statement in sql.split(';'):
                if statement.strip():
                    await connection.execute(statement.strip())
            await check_jobs_schema(connection)
            await connection.execute("INSERT IGNORE INTO agent_schema_migration (version,checksum) VALUES (:version,:checksum)",
                                     {"version": JOBS_MIGRATION.name, "checksum": checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def _article_conversation_columns(database):
    rows = await database.fetch_all("""SELECT COLUMN_NAME AS name, DATA_TYPE AS type, IS_NULLABLE AS nullable
        FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ai_conversation'""")
    return {r._mapping["name"]: dict(r._mapping) for r in rows}


async def _article_conversation_indexes(database):
    rows = await database.fetch_all("""SELECT COLUMN_NAME AS column_name, SEQ_IN_INDEX AS position, NON_UNIQUE AS non_unique
        FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ai_conversation'
        AND INDEX_NAME='idx_ai_conv_origin' ORDER BY SEQ_IN_INDEX""")
    return [dict(r._mapping) for r in rows]


async def check_article_conversation_schema(database):
    columns = await _article_conversation_columns(database)
    origin = columns.get("origin_article_id") or {}
    indexes = await _article_conversation_indexes(database)
    if (origin.get("type", "").lower() != "bigint" or origin.get("nullable") != "YES"
            or [i["column_name"] for i in indexes] != ["user_id", "origin_article_id", "status", "update_time", "conversation_id"]
            or any(i["non_unique"] != 1 for i in indexes)):
        raise RuntimeError("文章会话字段或索引未就绪；请运行 python -m app.migrate")


async def apply_article_conversation_migration(database):
    """Add a nullable source and nonunique lookup index, preserving old conversations."""
    sql = ARTICLE_CONVERSATION_MIGRATION.read_text(encoding="utf-8")
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema', 10)") != 1:
            raise RuntimeError("无法取得数据库迁移锁")
        try:
            old = await connection.fetch_one("SELECT checksum FROM agent_schema_migration WHERE version=:version",
                                             {"version": ARTICLE_CONVERSATION_MIGRATION.name})
            if old and old._mapping["checksum"] != checksum:
                raise RuntimeError("文章会话迁移校验和发生变化")
            columns = await _article_conversation_columns(connection)
            if not columns:
                raise RuntimeError("ai_conversation 表不存在；请先部署项目业务表")
            if "origin_article_id" in columns:
                origin = columns["origin_article_id"]
                if origin["type"].lower() != "bigint" or origin["nullable"] != "YES":
                    raise RuntimeError("来源文章字段类型或空值约束不兼容")
            indexes = await _article_conversation_indexes(connection)
            if indexes and ([i["column_name"] for i in indexes] != ["user_id", "origin_article_id", "status", "update_time", "conversation_id"]
                            or any(i["non_unique"] != 1 for i in indexes)):
                raise RuntimeError("已存在来源文章索引不兼容")
            for statement in sql.split(";"):
                statement = statement.strip()
                if not statement:
                    continue
                if statement == "ALTER TABLE ai_conversation ADD COLUMN origin_article_id BIGINT NULL DEFAULT NULL":
                    if "origin_article_id" not in columns:
                        await connection.execute(statement)
                elif statement == "CREATE INDEX idx_ai_conv_origin ON ai_conversation (user_id, origin_article_id, status, update_time, conversation_id)":
                    if not indexes:
                        await connection.execute(statement)
                else:
                    raise RuntimeError("非法的文章会话迁移语句")
            await check_article_conversation_schema(connection)
            await connection.execute("INSERT IGNORE INTO agent_schema_migration (version,checksum) VALUES (:version,:checksum)",
                                     {"version": ARTICLE_CONVERSATION_MIGRATION.name, "checksum": checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def check_delivery_schema(database):
    tables = await database.fetch_all("""SELECT TABLE_NAME AS name FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('agent_execution_gate','agent_execution_lease','agent_stream_frame')""")
    if len(tables) != 3:
        raise RuntimeError("执行限流与流式恢复表未就绪；请运行 python -m app.migrate")
    column = await database.fetch_val("""SELECT DATA_TYPE FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='message' AND COLUMN_NAME='client_message_id'""")
    indexes = await database.fetch_all("""SELECT COLUMN_NAME AS name FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='message' AND INDEX_NAME='uq_message_client'
        AND NON_UNIQUE=0 ORDER BY SEQ_IN_INDEX""")
    if column != 'varchar' or [r._mapping['name'] for r in indexes] != ['sender_id','client_message_id']:
        raise RuntimeError("私信幂等结构未就绪；请运行 python -m app.migrate")


async def apply_delivery_migration(database):
    sql = DELIVERY_MIGRATION.read_text(encoding='utf-8')
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema', 10)") != 1:
            raise RuntimeError("无法取得数据库迁移锁")
        try:
            previous = await connection.fetch_val("SELECT checksum FROM agent_schema_migration WHERE version=:v", {'v': DELIVERY_MIGRATION.name})
            if previous and previous != checksum:
                raise RuntimeError("流式恢复迁移校验和发生变化")
            for statement in sql.split(';'):
                statement = statement.strip()
                if not statement: continue
                if statement.startswith('ALTER TABLE message'):
                    if await connection.fetch_val("""SELECT COUNT(*) FROM information_schema.COLUMNS
                        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='message' AND COLUMN_NAME='client_message_id'"""):
                        continue
                if statement.startswith('CREATE UNIQUE INDEX uq_message_client'):
                    if await connection.fetch_val("""SELECT COUNT(*) FROM information_schema.STATISTICS
                        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='message' AND INDEX_NAME='uq_message_client'"""):
                        continue
                await connection.execute(statement)
            await check_delivery_schema(connection)
            await connection.execute("INSERT IGNORE INTO agent_schema_migration (version,checksum) VALUES (:v,:c)", {'v': DELIVERY_MIGRATION.name, 'c': checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def apply_optimization_migration(database):
    sql = OPTIMIZATION_MIGRATION.read_text(encoding='utf-8')
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得数据库迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v': OPTIMIZATION_MIGRATION.name})
            if previous and previous != checksum:
                raise RuntimeError('查询与阅读量迁移校验和发生变化')
            for statement in sql.split(';'):
                statement = statement.strip()
                if not statement: continue
                match = re.fullmatch(r'CREATE INDEX (\w+) ON (\w+)\(([\w,]+)\)', statement)
                if match:
                    name, table, columns = match.groups()
                    rows = await connection.fetch_all('''SELECT COLUMN_NAME AS col FROM information_schema.STATISTICS
                        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:t AND INDEX_NAME=:i ORDER BY SEQ_IN_INDEX''', {'t': table, 'i': name})
                    if rows:
                        if [r._mapping['col'] for r in rows] != columns.split(','): raise RuntimeError('已存在索引定义不兼容: ' + name)
                        continue
                await connection.execute(statement)
            await check_optimization_schema(connection)
            await connection.execute('INSERT IGNORE INTO agent_schema_migration(version,checksum) VALUES (:v,:c)', {'v': OPTIMIZATION_MIGRATION.name, 'c': checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def check_optimization_schema(database):
    receipt = await database.fetch_all('''SELECT COLUMN_NAME AS name,DATA_TYPE AS type FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='article_read_receipt' ''')
    columns = {r._mapping['name']: r._mapping['type'] for r in receipt}
    if columns != {'article_id': 'bigint', 'reader_hash': 'char', 'read_day': 'date', 'created_at': 'datetime'}:
        raise RuntimeError('阅读去重表未就绪，请运行 python -m app.migrate')
    rows = await database.fetch_all('''SELECT COLUMN_NAME AS col FROM information_schema.STATISTICS WHERE
        TABLE_SCHEMA=DATABASE() AND TABLE_NAME='article_read_receipt' AND INDEX_NAME='PRIMARY' ORDER BY SEQ_IN_INDEX''')
    if [r._mapping['col'] for r in rows] != ['article_id', 'reader_hash', 'read_day']:
        raise RuntimeError('阅读去重唯一约束未就绪')


async def check_heartbeat_schema(database):
    column = await database.fetch_one('''SELECT DATA_TYPE AS type, IS_NULLABLE AS nullable FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_run' AND COLUMN_NAME='executor_lease_until' ''')
    if not column or column._mapping['type'] != 'datetime' or column._mapping['nullable'] != 'YES':
        raise RuntimeError('执行心跳字段未就绪，请运行 python -m app.migrate')


async def apply_heartbeat_migration(database):
    sql = HEARTBEAT_MIGRATION.read_text(encoding='utf-8')
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得数据库迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v': HEARTBEAT_MIGRATION.name})
            if previous and previous != checksum:
                raise RuntimeError('执行心跳迁移校验和发生变化')
            exists = await connection.fetch_val('''SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_run' AND COLUMN_NAME='executor_lease_until' ''')
            if not exists:
                await connection.execute(sql.strip().rstrip(';'))
            await check_heartbeat_schema(connection)
            await connection.execute('INSERT IGNORE INTO agent_schema_migration(version,checksum) VALUES (:v,:c)', {'v': HEARTBEAT_MIGRATION.name, 'c': checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def apply_reading_migration(database):
    sql = READING_MIGRATION.read_text(encoding='utf-8')
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得数据库迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v': READING_MIGRATION.name})
            if previous and previous != checksum:
                raise RuntimeError('阅读等级迁移校验和发生变化')
            exists = await connection.fetch_val("""SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='article_info' AND COLUMN_NAME='required_level'""")
            for statement in sql.split(';'):
                statement = statement.strip()
                if not statement or (statement.startswith('ALTER TABLE') and exists):
                    continue
                await connection.execute(statement)
            await connection.execute('INSERT IGNORE INTO agent_schema_migration(version,checksum) VALUES (:v,:c)', {'v': READING_MIGRATION.name, 'c': checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def apply_admin_migration(database):
    sql = ADMIN_MIGRATION.read_text(encoding='utf-8')
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得数据库迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v': ADMIN_MIGRATION.name})
            if previous and previous != checksum:
                raise RuntimeError('管理后台迁移校验和发生变化')
            for statement in sql.split(';'):
                if statement.strip():
                    await connection.execute(statement.strip())
            await connection.execute('INSERT IGNORE INTO agent_schema_migration(version,checksum) VALUES (:v,:c)', {'v': ADMIN_MIGRATION.name, 'c': checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def apply_revision_migration(database):
    sql = REVISION_MIGRATION.read_text(encoding='utf-8')
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得数据库迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v': REVISION_MIGRATION.name})
            if previous and previous != checksum:
                raise RuntimeError('文章版本迁移校验和发生变化')
            for statement in sql.split(';'):
                statement = statement.strip()
                if not statement:
                    continue
                if statement.startswith('ALTER TABLE'):
                    column = re.search(r'ADD COLUMN (\w+)', statement).group(1)
                    exists = await connection.fetch_val("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='article_info' AND COLUMN_NAME=:c", {'c': column})
                    if exists:
                        continue
                await connection.execute(statement)
            await connection.execute('INSERT IGNORE INTO agent_schema_migration(version,checksum) VALUES (:v,:c)', {'v': REVISION_MIGRATION.name, 'c': checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def apply_view_sync_migration(database):
    sql = VIEW_SYNC_MIGRATION.read_text(encoding='utf-8')
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得数据库迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v': VIEW_SYNC_MIGRATION.name})
            if previous and previous != checksum:
                raise RuntimeError('阅读量同步迁移校验和发生变化')
            for statement in sql.split(';'):
                if statement.strip(): await connection.execute(statement.strip())
            await connection.execute('INSERT IGNORE INTO agent_schema_migration(version,checksum) VALUES (:v,:c)', {'v': VIEW_SYNC_MIGRATION.name, 'c': checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def main():
    await db.connect()
    try:
        await apply_migration(db)
        await apply_runtime_migration(db)
        await apply_memory_migration(db)
        await apply_content_migration(db)
        await apply_jobs_migration(db)
        await apply_article_conversation_migration(db)
        await apply_delivery_migration(db)
        await apply_optimization_migration(db)
        await apply_heartbeat_migration(db)
        await apply_reading_migration(db)
        await apply_admin_migration(db)
        await apply_revision_migration(db)
        await apply_view_sync_migration(db)
        await apply_maintenance_migration(db)
        await apply_task_recovery_migration(db)
        await apply_admin_user_migration(db)
        await apply_category_migration(db)
        await apply_statistics_category_migration(db)
        await apply_platform_completion(db)
        from app.services.revision_migration import apply_revision_workspace_migration
        await apply_revision_workspace_migration(db)
        await apply_service_boundaries(db)
        print("001..021: applied (legacy data preserved)")
    finally:
        await db.disconnect()


async def apply_maintenance_migration(database):
    migration=MIGRATION.with_name('014_maintenance_cursor.sql')
    checksum=hashlib.sha256(migration.read_bytes()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)")!=1:raise RuntimeError('无法取得迁移锁')
        try:
            previous=await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v',{'v':migration.name})
            if previous and previous!=checksum:raise RuntimeError('维护迁移校验和发生变化')
            for statement in migration.read_text(encoding='utf-8').split(';'):
                if statement.strip().startswith('CREATE INDEX ix_reading_cleanup'):
                    exists=await connection.fetch_val("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='reading_session' AND index_name='ix_reading_cleanup'")
                    if exists:continue
                if statement.strip():await connection.execute(statement.strip())
            await connection.execute('INSERT IGNORE INTO agent_schema_migration(version,checksum) VALUES (:v,:c)',{'v':migration.name,'c':checksum})
        finally:await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")

async def check_maintenance_schema(database):
    columns=await database.fetch_all("SELECT COLUMN_NAME AS column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='maintenance_cursor'")
    names={r._mapping['column_name'] for r in columns}
    if not {'kind','last_id','last_key','next_at','lease_token','lease_until'}<=names:
        raise RuntimeError('维护表未迁移，请执行 python -m app.migrate')


async def apply_task_recovery_migration(database):
    migration = MIGRATION.with_name('015_task_recovery.sql')
    checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v': migration.name})
            if previous and previous != checksum:
                raise RuntimeError('子任务恢复迁移校验和发生变化')
            for statement in migration.read_text(encoding='utf-8').split(';'):
                if statement.strip().startswith('ALTER TABLE'):
                    exists = await connection.fetch_val("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_run' AND column_name='recovery_count'")
                    if exists:
                        continue
                if statement.strip():
                    await connection.execute(statement.strip())
            await check_task_recovery_schema(connection)
            await connection.execute('INSERT IGNORE INTO agent_schema_migration(version,checksum) VALUES (:v,:c)', {'v': migration.name, 'c': checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def check_task_recovery_schema(database):
    count = await database.fetch_val("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND ((table_name='agent_task_artifact' AND column_name IN ('run_id','task_id','input_hash','result_json','updated_at')) OR (table_name='agent_run' AND column_name='recovery_count' AND data_type='int'))")
    if count != 6:
        raise RuntimeError('子任务恢复表未迁移，请执行 python -m app.migrate')


async def apply_admin_user_migration(database):
    migration = MIGRATION.with_name('016_admin_user_edit.sql')
    checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v': migration.name})
            if previous and previous != checksum:
                raise RuntimeError('管理员用户编辑迁移校验和发生变化')
            for statement in migration.read_text(encoding='utf-8').split(';'):
                statement = statement.strip()
                if not statement:
                    continue
                match = re.fullmatch(r'ALTER TABLE (\w+) ADD COLUMN (\w+) .+', statement)
                if not match:
                    raise RuntimeError('无效的管理员用户迁移语句')
                exists = await connection.fetch_val("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=:t AND column_name=:c", {'t': match[1], 'c': match[2]})
                if not exists:
                    await connection.execute(statement)
            await connection.execute('INSERT IGNORE INTO agent_schema_migration(version,checksum) VALUES (:v,:c)', {'v': migration.name, 'c': checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def apply_category_migration(database):
    migration = MIGRATION.with_name('017_admin_categories.sql')
    checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v': migration.name})
            if previous and previous != checksum:
                raise RuntimeError('分类迁移校验和发生变化')
            indexes = await connection.fetch_all("SELECT column_name AS columnName,non_unique AS nonUnique FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='category' AND index_name='uq_category_parent_name' ORDER BY seq_in_index")
            if indexes:
                if [r['columnName'] for r in indexes] != ['parent_id','category_name'] or any(r['nonUnique'] != 0 for r in indexes):
                    raise RuntimeError('分类唯一索引结构不兼容')
            else:
                duplicates = await connection.fetch_val('SELECT COUNT(*) FROM (SELECT parent_id,category_name FROM category WHERE parent_id IS NOT NULL GROUP BY parent_id,category_name HAVING COUNT(*)>1) d')
                if duplicates:
                    raise RuntimeError('存在同一父分类下的重名分类，请人工确认后再迁移；不会自动删除或合并分类')
                await connection.execute(migration.read_text(encoding='utf-8').strip().rstrip(';'))
            await connection.execute('INSERT IGNORE INTO agent_schema_migration(version,checksum) VALUES (:v,:c)', {'v': migration.name, 'c': checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def apply_statistics_category_migration(database):
    migration = MIGRATION.with_name('018_statistics_and_category_management.sql')
    checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v': migration.name})
            if previous and previous != checksum:
                raise RuntimeError('统计与分类管理迁移校验和发生变化')
            for statement in migration.read_text(encoding='utf-8').split(';'):
                statement = statement.strip()
                if not statement: continue
                match = re.fullmatch(r'ALTER TABLE (\w+) ADD COLUMN (\w+) .+',statement)
                if match:
                    if await connection.fetch_val('SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=:t AND column_name=:c', {'t':match[1],'c':match[2]}):continue
                elif previous:
                    continue
                await connection.execute(statement)
            await connection.execute('INSERT IGNORE INTO agent_schema_migration(version,checksum) VALUES (:v,:c)', {'v':migration.name,'c':checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def apply_platform_completion(database):
    migration = MIGRATION.with_name('019_platform_completion.sql')
    checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v':migration.name})
            if previous:
                if previous != checksum: raise RuntimeError('平台补齐迁移校验和发生变化')
                return
            for sql in migration.read_text(encoding='utf-8').split(';'):
                if sql.strip(): await connection.execute(sql.strip())
            await connection.execute('INSERT INTO agent_schema_migration(version,checksum) VALUES (:v,:c)', {'v':migration.name,'c':checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def apply_service_boundaries(database):
    migration = MIGRATION.with_name('021_service_boundaries.sql')
    checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v':migration.name})
            if previous:
                if previous != checksum: raise RuntimeError('服务边界迁移校验和发生变化')
                return
            for sql in migration.read_text(encoding='utf-8').split(';'):
                sql = sql.strip()
                if not sql: continue
                if sql.startswith('ALTER TABLE agent_run ADD COLUMN data_source'):
                    if await connection.fetch_val("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_run' AND column_name='data_source'"): continue
                await connection.execute(sql)
            await connection.execute('INSERT INTO agent_schema_migration(version,checksum) VALUES (:v,:c)', {'v':migration.name,'c':checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")


async def check_service_boundaries(database):
    count=await database.fetch_val("""SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE()
        AND ((table_name='agent_run' AND column_name='data_source')
          OR (table_name='agent_admin_audit' AND column_name IN ('command_id','actor_id','kind','target')))""")
    if count!=5:
        raise RuntimeError('服务边界迁移未就绪，请执行 python scripts/migrate-service-boundaries.py')


if __name__ == "__main__":
    asyncio.run(main())
