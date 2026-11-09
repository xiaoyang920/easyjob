"""Generate persistent ignored RSA keys and auth runtime config, without printing credentials."""
import base64,json,secrets
from pathlib import Path
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa

root=Path(__file__).resolve().parents[1]
folder=root/'temp/auth-keys';folder.mkdir(parents=True,exist_ok=True)
def number(value):return base64.urlsafe_b64encode(value.to_bytes((value.bit_length()+7)//8,'big')).rstrip(b'=').decode()
def keypair(name):
    private=folder/(name+'-private.json');public=folder/(name+'-public.json')
    if private.exists():
        data=json.loads(private.read_text(encoding='utf-8'))
        if data.get('kty')!='RSA' or 'd' not in data:raise RuntimeError('Invalid existing key material')
    else:
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048).private_numbers();pub=key.public_numbers
        data={'kty':'RSA','kid':name+'-'+secrets.token_hex(8),'use':'sig','alg':'RS256',**{k:number(v) for k,v in dict(n=pub.n,e=pub.e,d=key.d,p=key.p,q=key.q,dp=key.dmp1,dq=key.dmq1,qi=key.iqmp).items()}}
        private.write_text(json.dumps(data),encoding='utf-8')
    public.write_text(json.dumps({k:v for k,v in data.items() if k in ('kty','kid','use','alg','n','e')}),encoding='utf-8')
    return str(private),str(public)
auth_private,auth_public=keypair('auth');gateway_private,gateway_public=keypair('gateway');blog_private,blog_public=keypair('blog-delegation')
runtime_path=root/'temp/application-runtime.yml';runtime=yaml.safe_load(runtime_path.read_text(encoding='utf-8'))
base=yaml.safe_load((root/'src/main/resources/application.yml').read_text(encoding='utf-8'))
gateway_path=root/'temp/gateway-runtime.yml';gateway=yaml.safe_load(gateway_path.read_text(encoding='utf-8')) if gateway_path.exists() else {}
secret_path=folder/'service-key.txt'
if not secret_path.exists():secret_path.write_text(secrets.token_urlsafe(48),encoding='utf-8')
service_key=secret_path.read_text(encoding='utf-8').strip()
common={'enabled':True,'base-url':'http://127.0.0.1:8081','issuer':'easyjob-auth','service-key':service_key,'gateway-public-key-file':gateway_public,'blog-private-key-file':blog_private}
runtime.setdefault('easyjob',{})['auth']=common
gateway.setdefault('easyjob',{})['auth']=common|{'gateway-private-key-file':gateway_private,'jwks-uri':'http://127.0.0.1:8081/api/auth/jwks'}
runtime_path.write_text(yaml.safe_dump(runtime,allow_unicode=True,sort_keys=False),encoding='utf-8')
gateway_path.write_text(yaml.safe_dump(gateway,allow_unicode=True,sort_keys=False),encoding='utf-8')
spring={k:runtime.get('spring',{}).get(k,base.get('spring',{}).get(k,{})) for k in ('datasource','data','mail','rabbitmq')}
spring['rabbitmq']=spring.get('rabbitmq',{})|{'publisher-confirm-type':'correlated'}
auth={'spring':spring,'auth':{'private-key-file':auth_private,'gateway-public-key-file':gateway_public,'service-key':service_key,'issuer':'easyjob-auth'}}
(root/'temp/auth-runtime.yml').write_text(yaml.safe_dump(auth,allow_unicode=True,sort_keys=False),encoding='utf-8')
# The Agent only receives a public key for Blog-issued delegation.
from dotenv import set_key
set_key(root/'python-agent/.env.runtime.local','AUTH_DELEGATION_ENABLED','true')
set_key(root/'python-agent/.env.runtime.local','BLOG_DELEGATION_PUBLIC_KEY_FILE',blog_public)
set_key(root/'python-agent/.env.runtime.local','GATEWAY_IDENTITY_PUBLIC_KEY_FILE',gateway_public)
set_key(root/'python-agent/.env.runtime.local','AUTH_SERVICE_BASE_URL','http://127.0.0.1:8081')
set_key(root/'python-agent/.env.runtime.local','AUTH_SERVICE_CHECK_KEY',service_key)
print('Prepared ignored Auth/Gateway RSA keys and runtime settings; existing keys retained.')
accounts=root/'temp/auth-database-users.json'
if accounts.exists():
    manifest=json.loads(accounts.read_text(encoding='utf-8'))
    if manifest.get('owner')!='easyjob-unified-auth':raise RuntimeError('Database account manifest ownership mismatch')
    for name,role in [('application-runtime.yml','blog'),('auth-runtime.yml','auth')]:
        path=root/'temp'/name;document=yaml.safe_load(path.read_text(encoding='utf-8'));account=manifest['users'][role]
        document['spring']['datasource'].update(username=account['name'],password=account['password'])
        path.write_text(yaml.safe_dump(document,allow_unicode=True,sort_keys=False),encoding='utf-8')
    account=manifest['users']['agent']
    set_key(root/'python-agent/.env.runtime.local','AGENT_MYSQL_USER',account['name'])
    set_key(root/'python-agent/.env.runtime.local','AGENT_MYSQL_PASSWORD',account['password'])
