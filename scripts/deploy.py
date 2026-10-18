"""Compose setup, consistent backups and restore into a new isolated project."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]
DEPLOY=ROOT/'deploy'
ENV_FILE=DEPLOY/'.env'
FILES=('database.sql','assets.tar.gz')

def docker():
    executable=shutil.which('docker')
    if not executable:
        candidate=Path('C:/Program Files/Docker/Docker/resources/bin/docker.exe')
        if candidate.exists():executable=str(candidate)
    if not executable:raise RuntimeError('Docker CLI is not installed')
    return executable

def command(project, *args):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,48}',project):raise ValueError('Invalid Compose project name')
    return [docker(),'compose','--env-file',str(ENV_FILE),'-f',str(DEPLOY/'compose.yml'),'-p',project,*args]

def run(project,*args,stdin=None,stdout=None):
    return subprocess.run(command(project,*args),stdin=stdin,stdout=stdout or subprocess.PIPE,stderr=subprocess.PIPE,check=True)

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def init_env():
    target=DEPLOY/'.env'
    values={'MYSQL_ROOT_PASSWORD':secrets.token_urlsafe(32),'MYSQL_PASSWORD':secrets.token_urlsafe(32),
            'RABBITMQ_PASSWORD':secrets.token_urlsafe(32),'AGENT_SERVICE_KEY':secrets.token_urlsafe(48),
            'JWT_SECRET_KEY':base64.b64encode(secrets.token_bytes(64)).decode()}
    text=(DEPLOY/'.env.example').read_text(encoding='utf-8')
    for key,value in values.items():text=text.replace(key+'=\n',key+'='+value+'\n')
    with target.open('x',encoding='utf-8') as stream:stream.write(text)
    try:target.chmod(0o600)
    except OSError:pass
    print('Created deploy/.env. Fill model keys and mail settings; secrets were not printed.')

def validate():
    # Validate the complete graph without loading or printing local credentials.
    env={**os.environ,**{key:'validation-placeholder-not-a-real-secret' for key in
        ['MYSQL_ROOT_PASSWORD','MYSQL_PASSWORD','RABBITMQ_PASSWORD','JWT_SECRET_KEY','AGENT_SERVICE_KEY','DEEPSEEK_API_KEY','ZHIPUAI_API_KEY']}}
    subprocess.run([docker(),'compose','--env-file',str(DEPLOY/'.env.example'),'-f',str(DEPLOY/'compose.yml'),'--profile','tools','config','--quiet'],env=env,check=True)
    print('Compose configuration is valid; no services were started.')

def es(project, method, path, body=None):
    args=['exec','-T','elasticsearch','curl','-fsS','-X',method,'http://localhost:9200/'+path]
    if body is not None:args+=['-H','Content-Type: application/json','-d',json.dumps(body)]
    return json.loads(run(project,*args).stdout)

def backup(project, output):
    directory=Path(output).resolve();directory.mkdir(parents=True,exist_ok=False)
    running=run(project,'ps','--status','running','--services').stdout.decode().split()
    writers=[s for s in ('web','gateway','blog','agent') if s in running]
    if not {'mysql','redis-stack','elasticsearch'}.issubset(running):raise RuntimeError('Backup requires healthy MySQL, Redis Stack and ES')
    locks=ROOT/'backups';locks.mkdir(exist_ok=True)
    lock=locks/('.'+project+'.backup.lock')
    with lock.open('x',encoding='utf-8') as stream:stream.write(str(os.getpid()))
    snapshot='backup-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')+'-'+secrets.token_hex(4)
    try:
        if writers:run(project,'stop','-t','330',*writers)
        with (directory/'database.sql').open('wb') as stream:
            run(project,'exec','-T','mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --triggers --events --hex-blob --set-gtid-purged=OFF --databases easyjob',stdout=stream)
        run(project,'exec','-T','redis-stack','redis-cli','SAVE')
        es(project,'PUT','_snapshot/easyjob-portable',{'type':'fs','settings':{'location':'/snapshots/'+snapshot,'compress':True}})
        response=es(project,'PUT',f'_snapshot/easyjob-portable/{snapshot}?wait_for_completion=true',{'include_global_state':False})
        if response.get('snapshot',{}).get('state')!='SUCCESS':raise RuntimeError('ES snapshot did not complete')
        with (directory/'assets.tar.gz').open('wb') as stream:
            run(project,'run','--rm','--no-deps','-T','backup','tar -czf - -C /data uploads checkpoint/dump.rdb es-snapshots/'+snapshot,stdout=stream)
        metadata={'format':1,'project':project,'created_at':datetime.now(timezone.utc).isoformat(),
                  'snapshot':snapshot,'files':{name:sha(directory/name) for name in FILES},
                  'scope':'quiesced SQL, uploads, checkpoint RDB, Elasticsearch snapshot; Redis cache and MQ rebuilt'}
        (directory/'manifest.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
        verify_backup(directory)
        es(project,'DELETE',f'_snapshot/easyjob-portable/{snapshot}')
        print('Backup verified: '+str(directory))
    finally:
        try:
            if writers:run(project,'start',*reversed(writers))
        finally:lock.unlink(missing_ok=True)

def verify_backup(directory):
    directory=Path(directory).resolve()
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format')!=1 or not re.fullmatch(r'backup-[0-9]{14}-[a-f0-9]{8}',manifest.get('snapshot','')):
        raise ValueError('Unsupported or malformed backup')
    if set(manifest.get('files',{}))!=set(FILES):raise ValueError('Incomplete backup manifest')
    for name in FILES:
        path=directory/name
        if not path.is_file() or path.is_symlink() or sha(path)!=manifest['files'][name]:raise ValueError('Backup checksum mismatch: '+name)
    total=0
    with tarfile.open(directory/'assets.tar.gz','r:gz') as archive:
        for member in archive:
            path=PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or '\\' in member.name or ':' in member.name:
                raise ValueError('Unsafe archive path')
            if not member.isfile() and not member.isdir():raise ValueError('Links and special files are not allowed')
            if not (path.parts and path.parts[0] in ('uploads','checkpoint','es-snapshots')):raise ValueError('Unexpected archive content')
            total+=member.size
            if total>200*1024**3:raise ValueError('Backup exceeds the 200 GiB restore limit')
    return manifest

def restore(project, directory):
    manifest=verify_backup(directory)
    if project==manifest['project']:raise ValueError('Restore must use a new project name')
    # Check stopped containers and volumes too, so a previous deployment is never overwritten.
    for resource,args in [('containers',['ps','-aq']),('volumes',['volume','ls','-q'])]:
        found=subprocess.run([docker(),*args,'--filter','label=com.docker.compose.project='+project],capture_output=True,check=True).stdout.strip()
        if found:raise ValueError('Restore target already has '+resource+'; choose a new project')
    directory=Path(directory).resolve()
    with (directory/'assets.tar.gz').open('rb') as stream:
        run(project,'run','--rm','--no-deps','-T','backup','tar -xzf - -C /data && chown -R 10001:10001 /data/uploads && chown -R 1000:0 /data/es-snapshots',stdin=stream)
    run(project,'up','-d','--wait','--wait-timeout','240','mysql','redis-stack','elasticsearch','redis','rabbitmq','consul')
    with (directory/'database.sql').open('rb') as stream:
        run(project,'exec','-T','mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot',stdin=stream)
    es(project,'PUT','_snapshot/easyjob-portable',{'type':'fs','settings':{'location':'/snapshots/'+manifest['snapshot'],'compress':True}})
    result=es(project,'POST',f"_snapshot/easyjob-portable/{manifest['snapshot']}/_restore?wait_for_completion=true",{'include_global_state':False})
    if result.get('snapshot',{}).get('shards',{}).get('failed',0):raise RuntimeError('ES restore has failed shards')
    run(project,'up','-d','--build','--wait','--wait-timeout','600')
    print('Restored into new project '+project+'. Old project and volumes were preserved.')

def main():
    global ENV_FILE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',default='easyjob-container')
    parser.add_argument('--env-file',type=Path,default=DEPLOY/'.env')
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('init-env');sub.add_parser('validate')
    for name in ('backup','restore'):
        item=sub.add_parser(name);item.add_argument('--directory',required=True);item.add_argument('--execute',action='store_true')
    item=sub.add_parser('verify');item.add_argument('--directory',required=True)
    args=parser.parse_args()
    ENV_FILE=args.env_file.resolve()
    if args.action=='init-env':init_env()
    elif args.action=='validate':validate()
    elif args.action=='verify':verify_backup(args.directory);print('Backup hashes and archive paths verified.')
    elif not args.execute:
        if args.action=='restore':verify_backup(args.directory)
        print(json.dumps({'action':args.action,'project':args.project,'directory':str(Path(args.directory).resolve()),
            'execution':'dry-run; add --execute to run','writers_pause':args.action=='backup','restore_requires_new_project':True},ensure_ascii=False,indent=2))
    elif args.action=='backup':backup(args.project,args.directory)
    else:restore(args.project,args.directory)

if __name__=='__main__':main()
