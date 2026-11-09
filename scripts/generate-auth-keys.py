"""Generate RSA keys in an explicitly selected directory; retain existing private keys."""
import argparse,base64,json,secrets
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
def generate(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    def number(v):return base64.urlsafe_b64encode(v.to_bytes((v.bit_length()+7)//8,'big')).rstrip(b'=').decode()
    for name in ('auth','gateway','blog-delegation'):
        private=folder/(name+'-private.json');public=folder/(name+'-public.json')
        if private.exists():data=json.loads(private.read_text(encoding='utf-8'))
        else:
            key=rsa.generate_private_key(public_exponent=65537,key_size=2048).private_numbers();p=key.public_numbers
            data={'kty':'RSA','kid':name+'-'+secrets.token_hex(8),'use':'sig','alg':'RS256',**{k:number(v)for k,v in dict(n=p.n,e=p.e,d=key.d,p=key.p,q=key.q,dp=key.dmp1,dq=key.dmq1,qi=key.iqmp).items()}}
            private.write_text(json.dumps(data),encoding='utf-8')
            try:private.chmod(0o600)
            except OSError:pass
        public.write_text(json.dumps({k:v for k,v in data.items()if k in ('kty','kid','use','alg','n','e')}),encoding='utf-8')
    print('Auth key files prepared; existing private keys retained.')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');generate(parser.parse_args().directory)
