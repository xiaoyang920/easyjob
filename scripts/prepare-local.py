"""Generate ignored Java overrides from existing Python local secrets; never print them.

Run with python-agent/.venv/Scripts/python.exe. Does not migrate the database.
"""
import os
import secrets
import sys
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit
from uuid import uuid4

import yaml
from dotenv import dotenv_values, set_key

root = Path(__file__).resolve().parent.parent
excel_output = root / "temp/excel-runtime.yml"


def excel_http_status(port, path, key):
    connection = HTTPConnection("127.0.0.1", port, timeout=4)
    try:
        connection.request("GET", path, headers={"X-Excel-Key": key})
        with connection.getresponse() as response:
            return response.status
    finally:
        connection.close()


if sys.argv[1:] == ["--check-excel-db"]:
    import pymysql

    config = yaml.safe_load(excel_output.read_text(encoding="utf-8"))
    target = urlsplit((os.environ.get("EXCEL_DB_URL") or config["EXCEL_DB_URL"]).removeprefix("jdbc:"))
    if target.scheme != "mysql" or not target.hostname or not target.path.strip("/"):
        raise SystemExit("Excel database check requires a jdbc:mysql://host/database URL.")
    rsa_file = parse_qs(target.query).get("serverRSAPublicKeyFile", [None])[0]
    try:
        with pymysql.connect(host=target.hostname, port=target.port or 3306,
                user=os.environ.get("EXCEL_DB_USER", config["EXCEL_DB_USER"]),
                password=os.environ.get("EXCEL_DB_PASSWORD", config["EXCEL_DB_PASSWORD"]),
                database=unquote(target.path.lstrip("/")), charset="utf8mb4",
                server_public_key=Path(rsa_file).read_bytes() if rsa_file else None,
                connect_timeout=4, read_timeout=4, write_timeout=4) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT job_no FROM excel_export_job LIMIT 0")
    except pymysql.MySQLError as error:
        code = error.args[0] if error.args and isinstance(error.args[0], int) else "unknown"
        if code == 1146:
            raise SystemExit("Missing Excel task table (migration 032).") from None
        raise SystemExit(f"Could not query the Excel database (MySQL error {code}). Check Excel datasource settings.") from None
    except OSError:
        raise SystemExit("Could not read the configured MySQL public key file.") from None
    sys.exit(0)


if sys.argv[1:] in (["--check-excel-blog"], ["--check-excel-worker"]):
    config = yaml.safe_load(excel_output.read_text(encoding="utf-8"))
    key = os.environ.get("EASYJOB_EXCEL_SERVICE_KEY") or config["EASYJOB_EXCEL_SERVICE_KEY"]
    check_blog = sys.argv[1] == "--check-excel-blog"
    try:
        if check_blog:
            status = excel_http_status(8080, "/internal/excel/ready", key)
            if status != 204:
                raise SystemExit(f"Blog Excel readiness returned HTTP {status}. Check the running Blog version and Excel configuration.")
        else:
            # A random nonexistent job proves that authentication and the read path work without enqueuing a job.
            path = f"/internal/excel/jobs/{uuid4()}?ownerId=1"
            rejected = excel_http_status(8083, path, f"invalid-{uuid4()}")
            authenticated = excel_http_status(8083, path, key)
            if (rejected, authenticated) != (403, 404):
                raise SystemExit(f"Excel job probe returned HTTP {rejected} with an invalid key and {authenticated} with the configured key. Check the Excel process, shared key, and task table.")
    except (OSError, HTTPException):
        raise SystemExit(f"Could not reach {'Blog on port 8080' if check_blog else 'Excel on port 8083'}.") from None
    sys.exit(0)

env_file = root / "python-agent/.env"
if not env_file.exists():
    raise SystemExit("Create python-agent/.env with local database/API configuration first.")
values = dotenv_values(env_file)
runtime_env = env_file.with_name(".env.runtime.local")
local_values = dotenv_values(runtime_env) if runtime_env.exists() else {}
if sys.argv[1:] == ["--excel"]:
    previous = yaml.safe_load(excel_output.read_text(encoding="utf-8")) if excel_output.exists() else {}
    key = previous.get("EASYJOB_EXCEL_SERVICE_KEY") or secrets.token_urlsafe(48)
    effective_key = os.environ.get("EASYJOB_EXCEL_SERVICE_KEY") or key
    if len(effective_key.encode()) < 32:
        raise SystemExit("EASYJOB_EXCEL_SERVICE_KEY must contain at least 32 bytes.")
    database = {**values, **local_values}
    host = database.get("MYSQL_HOST") or "localhost"
    port = database.get("MYSQL_PORT") or "3306"
    name = database.get("MYSQL_DB") or "easyjob"
    url = f"jdbc:mysql://{host}:{port}/{name}?serverTimezone=UTC&useUnicode=true&characterEncoding=utf8&useSSL=false"
    if database.get("MYSQL_SERVER_RSA_PUBLIC_KEY"):
        url += "&serverRSAPublicKeyFile=" + quote(database["MYSQL_SERVER_RSA_PUBLIC_KEY"], safe="")
    config = {
        "EASYJOB_EXCEL_SERVICE_KEY": key,
        "EXCEL_DB_URL": url,
        "EXCEL_DB_USER": database.get("MYSQL_USER") or "root",
        "EXCEL_DB_PASSWORD": database.get("MYSQL_PASSWORD") or "",
    }
    excel_output.parent.mkdir(exist_ok=True)
    excel_output.write_text(yaml.safe_dump(config), encoding="utf-8")
    print("Prepared ignored Excel runtime configuration. Credentials were not printed.")
    sys.exit(0)

key = local_values.get("AGENT_SERVICE_KEY") or values.get("AGENT_SERVICE_KEY") or secrets.token_urlsafe(48)
if len(key.encode()) < 32:
    raise SystemExit("Existing AGENT_SERVICE_KEY is too short; set at least 32 bytes.")
for name, value in {
    "AGENT_SERVICE_KEY": key,
    "REDIS_HOST": "localhost", "REDIS_PORT": "6379", "REDIS_DB": "3", "REDIS_PASSWORD": "",
    "REDIS_STACK_HOST": "localhost", "REDIS_STACK_PORT": "6380", "REDIS_STACK_DB": "0", "REDIS_STACK_PASSWORD": "",
    "SERVICE_DISCOVERY_ENABLED": "true", "CONSUL_URL": "http://127.0.0.1:8500",
}.items():
    set_key(str(runtime_env), name, value)
host, port, database = values.get("MYSQL_HOST", "localhost"), values.get("MYSQL_PORT", "3306"), values.get("MYSQL_DB", "easyjob")
mysql_url = f"jdbc:mysql://{host}:{port}/{database}?serverTimezone=GMT%2B8&useUnicode=true&characterEncoding=utf8&useSSL=false"
rsa_key = local_values.get("MYSQL_SERVER_RSA_PUBLIC_KEY") or values.get("MYSQL_SERVER_RSA_PUBLIC_KEY")
if rsa_key:
    mysql_url += "&serverRSAPublicKeyFile=" + quote(rsa_key, safe="")
config = {
    "AGENT_SERVICE_KEY": key,
    "SERVICE_DISCOVERY_ENABLED": True,
    "spring": {
        "datasource": {
            "url": mysql_url,
            "username": values.get("MYSQL_USER", "root"), "password": values.get("MYSQL_PASSWORD", ""),
        },
        "data": {"redis": {"host": "localhost", "port": 6379, "database": 3, "password": ""}},
    },
}
deepseek_key = local_values.get("DEEPSEEK_API_KEY") or values.get("DEEPSEEK_API_KEY")
if deepseek_key:
    config['spring']['ai'] = {'deepseek': {'api-key': deepseek_key}}
config['deepseek'] = {'balance-alert': {
    'enabled': (local_values.get('DEEPSEEK_BALANCE_ALERT_ENABLED') or values.get('DEEPSEEK_BALANCE_ALERT_ENABLED') or 'false').lower() in ('true', '1', 'yes'),
    'currency': local_values.get('DEEPSEEK_BALANCE_ALERT_CURRENCY') or values.get('DEEPSEEK_BALANCE_ALERT_CURRENCY') or 'CNY',
    'threshold': local_values.get('DEEPSEEK_BALANCE_ALERT_THRESHOLD') or values.get('DEEPSEEK_BALANCE_ALERT_THRESHOLD') or '2.00',
    'recipient': local_values.get('DEEPSEEK_BALANCE_ALERT_RECIPIENT') or values.get('DEEPSEEK_BALANCE_ALERT_RECIPIENT') or '',
    'interval-seconds': int(local_values.get('DEEPSEEK_BALANCE_ALERT_INTERVAL_SECONDS') or values.get('DEEPSEEK_BALANCE_ALERT_INTERVAL_SECONDS') or '600'),
}}
config['agent'] = {'web-search': {
    'base-url': local_values.get('DEEPSEEK_TOOLS_BASE_URL') or values.get('DEEPSEEK_TOOLS_BASE_URL') or 'https://api.deepseek.com/v1',
    'enabled': (local_values.get('AGENT_WEB_SEARCH_ENABLED') or values.get('AGENT_WEB_SEARCH_ENABLED') or 'true').lower() in ('true', '1', 'yes'),
    'max-results': 5,
}}
output = root / "temp/application-runtime.yml"
output.parent.mkdir(exist_ok=True)
output.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
java_config = yaml.safe_load((root / 'src/main/resources/application.yml').read_text(encoding='utf-8'))
jwt = java_config.get('easyjob', {}).get('jwt', {}).get('secret-key')
if not jwt or str(jwt).startswith('${'):
    jwt = local_values.get('JWT_SECRET_KEY') or values.get('JWT_SECRET_KEY')
if not jwt or len(str(jwt).encode()) < 64:
    raise SystemExit('Set the existing Java JWT_SECRET_KEY (at least 64 bytes) before starting the gateway.')
(root / 'temp/gateway-runtime.yml').write_text(yaml.safe_dump({'easyjob': {'jwt': {'secret-key': jwt}}}), encoding='utf-8')
print("Prepared local runtime configuration. Secrets stored only in ignored local files.")
import runpy
runpy.run_path(str(root/'scripts/prepare-auth.py'),run_name='__main__')
