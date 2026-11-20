"""Create owned least-privilege local runtime users. Maintenance credentials stay separate.

Never prints passwords or SQL. Only users recorded in the ignored manifest are changed.
"""
import argparse,json,os,secrets,sys
from pathlib import Path
import pymysql,yaml
from dotenv import set_key
from auth_database_grants import grant_space_customization,provision,verify,verify_space_customization
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/python-agent'))
from app.config import settings
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--refresh-space-grants', action='store_true', help='Update only space customization grants on the owned local Blog account')
args = parser.parse_args()
manifest=ROOT/'temp/auth-database-users.json'
if args.refresh_space_grants and not manifest.exists():
    raise SystemExit('Local runtime account manifest is missing.')
if manifest.exists():data=json.loads(manifest.read_text(encoding='utf-8'))
else:
    suffix=secrets.token_hex(4)
    data={'owner':'easyjob-unified-auth','database':settings.MYSQL_DB,'users':{role:{'name':f'ej_{role}_{suffix}','password':secrets.token_urlsafe(32)}for role in ('auth','blog','agent')}}
    manifest.write_text(json.dumps(data),encoding='utf-8')
if data.get('owner')!='easyjob-unified-auth' or data.get('database')!=settings.MYSQL_DB:raise SystemExit('Runtime account manifest ownership mismatch.')
options=dict(host=settings.MYSQL_HOST,port=settings.MYSQL_PORT,database=settings.MYSQL_DB,autocommit=True)
public_key = os.environ.get('MYSQL_SERVER_RSA_PUBLIC_KEY')
if public_key:
    options['server_public_key'] = Path(public_key).read_bytes()
if args.refresh_space_grants:
    if settings.MYSQL_HOST not in ('localhost', '127.0.0.1', '::1'):
        raise SystemExit('The local Blog grant refresh requires a loopback MySQL connection.')
    blog = data['users']['blog']
    with pymysql.connect(**options, user=settings.MYSQL_USER, password=settings.MYSQL_PASSWORD) as connection:
        grant_space_customization(connection, settings.MYSQL_DB, blog['name'])
    with pymysql.connect(**options, user=blog['name'], password=blog['password']) as connection:
        verify_space_customization(connection)
    print('Blog space customization permissions verified.')
    sys.exit(0)
connection=pymysql.connect(**options,user=settings.MYSQL_USER,password=settings.MYSQL_PASSWORD)
try:
    provision(connection,settings.MYSQL_DB,data['users'])
finally:connection.close()
for role,account in data['users'].items():
    connection=pymysql.connect(**options,user=account['name'],password=account['password'])
    try:verify(connection,role)
    finally:connection.close()
for file,role in [('application-runtime.yml','blog'),('auth-runtime.yml','auth')]:
    path=ROOT/'temp'/file;config=yaml.safe_load(path.read_text(encoding='utf-8'));account=data['users'][role]
    config.setdefault('spring',{}).setdefault('datasource',{}).update(username=account['name'],password=account['password'])
    path.write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False),encoding='utf-8')
account=data['users']['agent']
set_key(ROOT/'services/python-agent/.env.runtime.local','AGENT_MYSQL_USER',account['name'])
set_key(ROOT/'services/python-agent/.env.runtime.local','AGENT_MYSQL_PASSWORD',account['password'])
print('Three owned runtime database users provisioned; allowed/forbidden column and table checks passed. Maintenance credentials unchanged.')
