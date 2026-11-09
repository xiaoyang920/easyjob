"""Two-step Auth signing-key rotation. Publish first, activate then restart Auth."""
import argparse,json,runpy,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main(action,folder):
    folder=Path(folder).resolve();private=folder/'auth-private.json'
    if not private.exists():raise SystemExit('Auth private key file is missing.')
    if action=='prepare':
        runpy.run_path(str(ROOT/'scripts/generate-auth-keys.py'))['generate'](folder/'next')
        data=json.loads((folder/'next/auth-public.json').read_text(encoding='utf-8'))
        target=folder/('auth-published-public-'+data['kid']+'.json')
        target.write_text(json.dumps(data),encoding='utf-8')
        print('Next public key published. Check JWKS, then activate and restart Auth.')
    else:
        old=json.loads(private.read_text(encoding='utf-8'));next_file=folder/'next/auth-private.json'
        if not next_file.exists():raise SystemExit('Prepare a new key first.')
        new=json.loads(next_file.read_text(encoding='utf-8'))
        if new['kid']==old['kid']:raise SystemExit('This key is already active.')
        pub={k:v for k,v in old.items()if k in ('kty','kid','use','alg','n','e')}
        (folder/('auth-published-public-'+old['kid']+'.json')).write_text(json.dumps(pub),encoding='utf-8')
        shutil.copyfile(next_file,private)
        (folder/'auth-public.json').write_text(json.dumps({k:v for k,v in new.items()if k in ('kty','kid','use','alg','n','e')}),encoding='utf-8')
        print('New signing key activated on disk. Restart Auth; retain old public keys at least 30 minutes plus clock skew.')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','activate']);parser.add_argument('--directory',default=str(ROOT/'temp/auth-keys'));args=parser.parse_args();main(args.action,args.directory)
