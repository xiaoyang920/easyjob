"""Shared runtime grants. Only supplied accounts are changed; no secrets logged."""
import re
import pymysql


def identifier(value):
    if not re.fullmatch(r'[a-zA-Z0-9_]+', value):
        raise ValueError('Unexpected SQL identifier')
    return '`' + value + '`'


def provision(connection, database, accounts, host='localhost'):
    if set(accounts) != {'auth', 'blog', 'agent'} or host not in ('localhost', '%'):
        raise ValueError('Unexpected runtime account scope')
    database = identifier(database)
    with connection.cursor() as cursor:
        cursor.execute('SHOW TABLES')
        tables = [row[0] for row in cursor.fetchall()]
        cursor.execute('SHOW COLUMNS FROM user_info')
        columns = [row[0] for row in cursor.fetchall()]
        auth_owned = {'email', 'password', 'role', 'status', 'auth_version', 'last_login_time', 'last_login_ip'}
        profile = [name for name in columns if name not in auth_owned and name != 'user_id']
        readable = [name for name in columns if name != 'password']
        agent_owned = {name for name in tables if name.startswith(('agent_', 'ai_', 'direct_chat_'))
                       or name in ('user_memory', 'user_memory_change', 'user_profile', 'maintenance_cursor')}
        agent_owned.discard('agent_schema_migration')
        for role, account in accounts.items():
            if not re.fullmatch(r'ej_' + role + r'_[a-z0-9_]{1,16}', account['name']):
                raise ValueError('Unexpected runtime account name')
            user = "'" + account['name'] + "'@'" + host + "'"
            cursor.execute('CREATE USER IF NOT EXISTS ' + user + ' IDENTIFIED BY %s', (account['password'],))
            cursor.execute('ALTER USER ' + user + ' IDENTIFIED BY %s', (account['password'],))
            cursor.execute('REVOKE ALL PRIVILEGES, GRANT OPTION FROM ' + user)
            if role == 'auth':
                cursor.execute(f'GRANT SELECT, INSERT ON {database}.user_info TO {user}')
                cursor.execute(f'GRANT UPDATE ({",".join(map(identifier, sorted(auth_owned)))}) ON {database}.user_info TO {user}')
                for table in ('auth_audit', 'auth_outbox'):
                    cursor.execute(f'GRANT SELECT,INSERT,UPDATE,DELETE ON {database}.{identifier(table)} TO {user}')
                continue
            cursor.execute(f'GRANT SELECT ({",".join(map(identifier, readable))}) ON {database}.user_info TO {user}')
            if role == 'blog':
                cursor.execute(f'GRANT UPDATE ({",".join(map(identifier, profile))}) ON {database}.user_info TO {user}')
            for table in tables:
                if table == 'user_info' or table.startswith('auth_'):
                    continue
                writable = (role == 'blog' and table != 'agent_schema_migration') or table in agent_owned
                privileges = 'SELECT,INSERT,UPDATE,DELETE' if writable else 'SELECT'
                cursor.execute(f'GRANT {privileges} ON {database}.{identifier(table)} TO {user}')


def verify(connection, role):
    """Empty reads and no-op writes exercise grants without changing any rows."""
    with connection.cursor() as probe:
        def denied(sql):
            try:
                probe.execute(sql)
            except pymysql.err.OperationalError as error:
                if error.args[0] not in (1142, 1143):
                    raise
            else:
                raise RuntimeError(f'{role} passed a forbidden database operation')

        probe.execute('SELECT user_id FROM user_info LIMIT 0')
        if role == 'auth':
            probe.execute('SELECT password FROM user_info LIMIT 0')
            probe.execute('UPDATE user_info SET auth_version=auth_version WHERE 1=0')
            probe.execute('SELECT event_id FROM auth_outbox LIMIT 0')
            denied('UPDATE user_info SET nick_name=nick_name WHERE 1=0')
            denied('SELECT article_id FROM article_info LIMIT 0')
        else:
            denied('SELECT password FROM user_info LIMIT 0')
            denied('UPDATE user_info SET password=password WHERE 1=0')
            denied('UPDATE user_info SET auth_version=auth_version WHERE 1=0')
            denied('SELECT event_id FROM auth_outbox LIMIT 0')
            denied('UPDATE agent_schema_migration SET version=version WHERE 1=0')
            probe.execute('SELECT article_id FROM article_info LIMIT 0')
            if role == 'blog':
                probe.execute('UPDATE user_info SET nick_name=nick_name WHERE 1=0')
            else:
                denied('UPDATE article_info SET title=title WHERE 1=0')
