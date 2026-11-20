"""Shared runtime grants. Only supplied accounts are changed; no secrets logged."""
import re
import pymysql


def identifier(value):
    if not re.fullmatch(r'[a-zA-Z0-9_]+', value):
        raise ValueError('Unexpected SQL identifier')
    return '`' + value + '`'


def grant_space_customization(connection, database, blog_user):
    """Add just the space feature grants to an existing local Blog account."""
    if not re.fullmatch(r'ej_blog_[a-z0-9_]{1,16}', blog_user):
        raise ValueError('Unexpected local Blog runtime account')
    schema = identifier(database)
    user = f"'{blog_user}'@'localhost'"
    columns = 'space_banner_url, space_banner_position, space_banner_view'
    with connection.cursor() as cursor:
        cursor.execute(f'GRANT SELECT ({columns}), UPDATE ({columns}) ON {schema}.user_info TO {user}')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE (name, coin_price, sort_order, listed, version) ON {schema}.space_skin TO {user}')
        cursor.execute(f'GRANT SELECT, INSERT ON {schema}.user_space_skin TO {user}')
        for table in ('space_artwork', 'space_product_artwork'):
            cursor.execute(f'GRANT SELECT, INSERT ON {schema}.{table} TO {user}')
        cursor.execute(f'GRANT UPDATE (name, artist, version, withdrawn) ON {schema}.space_artwork TO {user}')
        cursor.execute(f'GRANT SELECT, INSERT, DELETE ON {schema}.user_equipped_artwork TO {user}')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {schema}.space_banner_review TO {user}')


def verify_space_customization(connection):
    with connection.cursor() as cursor:
        cursor.execute('SELECT space_banner_url, space_banner_position, space_banner_view FROM user_info LIMIT 0')
        cursor.execute('SELECT skin_id, name, coin_price, listed, sort_order, version FROM space_skin LIMIT 0')
        cursor.execute('SELECT skin_id FROM user_space_skin LIMIT 0')
        cursor.execute('SELECT artwork_id, artist, withdrawn, version, assets, settings FROM space_artwork LIMIT 0')
        cursor.execute('UPDATE space_artwork SET version=version WHERE 1=0')
        cursor.execute('SELECT artwork_id FROM space_product_artwork LIMIT 0')
        cursor.execute('SELECT artwork_id FROM user_equipped_artwork LIMIT 0')
        cursor.execute('SELECT review_id, view_json FROM space_banner_review LIMIT 0')
        cursor.execute('UPDATE space_skin SET version = version WHERE 1 = 0')


def provision(connection, database, accounts, host='localhost'):
    roles = set(accounts)
    if not {'auth', 'blog', 'agent'} <= roles <= {'auth', 'blog', 'agent', 'excel', 'index'} or host not in ('localhost', '%'):
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
            if role == 'index':
                # Advisory locks need a connection but no schema or table grants.
                continue
            if role == 'excel':
                cursor.execute(f'GRANT SELECT,INSERT,UPDATE ON {database}.excel_export_job TO {user}')
                continue
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
                if table in ('user_info', 'excel_export_job') or table.startswith('auth_'):
                    continue
                if table == 'space_banner_review' and role != 'blog':
                    continue
                writable = (role == 'blog' and table != 'agent_schema_migration') or table in agent_owned
                privileges = 'SELECT,INSERT,UPDATE,DELETE' if writable else 'SELECT'
                cursor.execute(f'GRANT {privileges} ON {database}.{identifier(table)} TO {user}')


def verify(connection, role, database=None):
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

        if role == 'index':
            probe.execute("SELECT GET_LOCK('easyjob_index_grant_probe', 0)")
            if probe.fetchone()[0] != 1:
                raise RuntimeError('Index role could not acquire an advisory lock')
            probe.execute("SELECT RELEASE_LOCK('easyjob_index_grant_probe')")
            if probe.fetchone()[0] != 1:
                raise RuntimeError('Index role could not release an advisory lock')
            denied(f'SELECT article_id FROM {identifier(database)}.article_info LIMIT 0')
            return
        if role == 'excel':
            probe.execute('SELECT job_no FROM excel_export_job LIMIT 0')
            probe.execute('UPDATE excel_export_job SET status=status WHERE 1=0')
            denied('DELETE FROM excel_export_job WHERE 1=0')
            denied('SELECT user_id FROM user_info LIMIT 0')
            return
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
