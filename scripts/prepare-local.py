"""Generate ignored Java overrides from existing Python local secrets; never print them.

Run with python-agent/.venv/Scripts/python.exe. Does not migrate the database.
"""
import secrets
from pathlib import Path
from urllib.parse import quote

import yaml
from dotenv import dotenv_values, set_key

root = Path(__file__).resolve().parent.parent
env_file = root / "python-agent/.env"
if not env_file.exists():
    raise SystemExit("Create python-agent/.env with local database/API configuration first.")
values = dotenv_values(env_file)
runtime_env = env_file.with_name(".env.runtime.local")
local_values = dotenv_values(runtime_env) if runtime_env.exists() else {}
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
