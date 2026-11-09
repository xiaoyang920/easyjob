"""One-shot grants after migrations; root only uses the private MySQL socket."""
import os
import pymysql
from auth_database_grants import provision, verify


def main():
    database = os.environ['MYSQL_DB']
    accounts = {role: {'name': f'ej_{role}_runtime', 'password': os.environ[role.upper() + '_DB_PASSWORD']}
                for role in ('auth', 'blog', 'agent')}
    if any(len(account['password']) < 32 for account in accounts.values()):
        raise ValueError('Runtime database passwords must have at least 32 characters')
    with pymysql.connect(unix_socket='/var/run/mysqld/mysqld.sock', user='root',
                         password=os.environ['MYSQL_ROOT_PASSWORD'], database=database, autocommit=True) as connection:
        provision(connection, database, accounts, host='%')
    for role, account in accounts.items():
        with pymysql.connect(host='mysql', port=3306, user=account['name'], password=account['password'],
                             database=database, autocommit=True) as connection:
            verify(connection, role)
    print('Runtime database roles and denied-operation checks passed.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Database permissions setup failed: ' + type(error).__name__)
